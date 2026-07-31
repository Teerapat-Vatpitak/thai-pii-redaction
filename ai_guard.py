"""AI Guard — Thai PII redaction pipeline CLI."""

import argparse
import json
import sys
import types
from pathlib import Path


def cmd_sanitize(args):
    """Run full pipeline on a file."""
    from pii_redactor.ai_client import FakeLLMProvider, OllamaProvider
    from pii_redactor.pipeline import run_pipeline

    # Select provider
    if args.provider == "fake" or args.provider is None:
        provider = FakeLLMProvider()
    elif args.provider == "ollama":
        provider = OllamaProvider()
    elif args.provider == "claude":
        from pii_redactor.ai_client import ClaudeProvider

        provider = ClaudeProvider()
    else:
        print(f"Unknown provider: {args.provider}", file=sys.stderr)
        sys.exit(1)

    try:
        result = run_pipeline(
            input_path=args.file,
            output_path=args.output,
            fmt=args.fmt or "txt",
            provider=provider,
            overwrite=args.overwrite,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Session: {result.session_id}")
    print(
        f"Entities detected: {len(result.entity_registry.entities)} "
        f"(FP={result.entity_registry.fp_count}, TB={result.entity_registry.tb_count})"
    )

    if result.export_result:
        print(
            f"Output written: {result.export_result.output_path} "
            f"({result.export_result.byte_size} bytes)"
        )
    else:
        # The MASKED text (what you'd paste into an external AI), NOT
        # reverse_result.text — that is the re-identified output, which under
        # the fake provider is just the original PII echoed back.
        print("--- Sanitized Output ---")
        print(result.pseudonymized_text)

    if result.validation_result.flags:
        print(f"Warnings: {result.validation_result.flags}", file=sys.stderr)


def cmd_report(args):
    """Generate a PII risk report for a file (no redaction)."""
    from pii_redactor.detectors.aggregate import detect_all
    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_cleaner import clean
    from pii_redactor.ingest.text_extractor import extract

    try:
        source_type = detect_source_type(args.file)
        extracted_text, _bboxes, _meta = extract(args.file, source_type)
        clean_result = clean(extracted_text)
        text = clean_result.text
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Failed to read file: {e}", file=sys.stderr)
        sys.exit(1)

    merged = detect_all(text)
    fp_entities = [e for e in merged if e.redact_type == "FP"]
    tb_entities = [e for e in merged if e.redact_type != "FP"]

    print(f"=== PII Risk Report: {args.file} ===")
    print(f"Total entities detected: {len(merged)}")
    print(f"  Structured PII (FP): {len(fp_entities)}")
    print(f"  Name/Address/Date (TB): {len(tb_entities)}")

    if fp_entities:
        print("\nStructured PII types:")
        type_counts = {}
        for e in fp_entities:
            type_counts[e.data_type] = type_counts.get(e.data_type, 0) + 1
        for dtype, count in sorted(type_counts.items()):
            print(f"  {dtype}: {count}")

    if tb_entities:
        print("\nNamed entity types:")
        type_counts = {}
        for e in tb_entities:
            type_counts[e.data_type] = type_counts.get(e.data_type, 0) + 1
        for dtype, count in sorted(type_counts.items()):
            print(f"  {dtype}: {count}")

    total = len(fp_entities) + len(tb_entities)
    if total == 0:
        risk = "Low"
    elif total <= 5:
        risk = "Medium"
    else:
        risk = "High"

    print(f"\nRisk Level: {risk}")


def cmd_receipt_issue(args):
    """Issue a PDPA มาตรา 39 processing receipt for a file."""
    from pii_redactor.receipt import build_receipt

    # Both destinations are checked before the pipeline runs, not after.
    # Failing fast costs the user nothing, and it keeps a bad --pdf path from
    # being discovered once the JSON is already on disk — a run that leaves
    # half a receipt behind is worse than one that refuses to start. A receipt
    # is evidence someone kept on purpose, so clobbering one silently would be
    # the odd behaviour; `sanitize --overwrite` already sets that convention.
    for path in (args.output, args.pdf):
        if not path:
            continue
        target = Path(path)
        if target.exists() and not args.overwrite:
            print(f"Error: {path} already exists (use --overwrite)", file=sys.stderr)
            sys.exit(1)
        parent = target.parent
        if not parent.is_dir():
            print(f"Error: {parent} is not a directory", file=sys.stderr)
            sys.exit(1)

    try:
        receipt = build_receipt(
            args.file,
            purpose=args.purpose,
            controller=args.controller,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Failed to issue receipt: {e}", file=sys.stderr)
        sys.exit(1)

    # Both artifacts are rendered before either is written. A bad --pdf path
    # used to surface after the JSON had already landed, so the run ended with
    # a success line, a raw traceback, and half a receipt on disk.
    blob = json.dumps(receipt, ensure_ascii=False, indent=2)
    pdf_bytes = None
    if args.pdf:
        from pii_redactor.receipt_pdf import render_receipt

        pdf_bytes = render_receipt(receipt)

    try:
        if args.output:
            Path(args.output).write_text(blob + "\n", encoding="utf-8")
        if pdf_bytes is not None:
            Path(args.pdf).write_bytes(pdf_bytes)
    except OSError as e:
        print(f"Error: cannot write receipt: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        print(f"Receipt written: {args.output}")
    else:
        print(blob)
    if pdf_bytes is not None:
        print(f"Receipt PDF written: {args.pdf}")


def _print_breach_summary(result, payload):
    """Short Thai summary: counts only, no PII value, no filename beyond the
    basenames breach.py already limits itself to. Thai punctuation uses spaces,
    never Western colons/semicolons (see cmd_receipt_verify's output)."""
    print(f"ประเมินแล้ว {result.files_assessed}/{result.files_total} ไฟล์")
    print(f"ประเภทข้อมูลที่พบ {len(payload['types'])} ประเภท")
    subjects = payload["subjects"]
    if subjects["no_strong_identifiers"]:
        # subjects_min/max are both 0 here only because no strong identifier
        # (id/passport/phone/email) was found -- that is not the same claim as
        # "nobody was affected", so the headline says so instead of a 0-0 range.
        print("ไม่พบตัวระบุแบบเข้ม จึงประมาณจำนวนเจ้าของข้อมูลไม่ได้")
    else:
        print(f"ประมาณการจำนวนเจ้าของข้อมูลที่ได้รับผลกระทบ {subjects['min']}-{subjects['max']} คน")
    print(f"ระดับความเสี่ยงสูงสุด {payload['risk']['max_grade']}")


def _scrub_known_paths(message, paths):
    """Fold every spelling of each caller-given path (as given, resolved, both
    slash directions) down to its bare basename.

    Mirrors `breach._short_reason`'s per-file path scrub, but applied to a
    corpus-level failure (e.g. a `PermissionError` raised while scanning a
    directory) that escapes `assess_breach` itself -- any of `args.paths`
    could be the one embedded in the exception's own message, not just a
    single file, so every one of them is scrubbed."""
    for raw in paths:
        path = Path(raw)
        basename = path.name
        spellings = {str(path)}
        try:
            spellings.add(str(path.resolve()))
        except OSError:
            pass
        for spelling in list(spellings):
            spellings.add(spelling.replace("\\", "/"))
            spellings.add(spelling.replace("/", "\\"))
        for spelling in spellings:
            if spelling and spelling != basename:
                message = message.replace(spelling, basename)
    return message


def cmd_breach_assess(args):
    """Assess a set of files for a PDPA มาตรา 37(4) breach notification."""
    from pii_redactor.breach import NoFilesAssessedError, assess_breach

    # --pdf is checked before the assessment runs, same reasoning as receipt
    # issue: a run that discovers a missing renderer after already writing the
    # JSON leaves a half-finished result on disk. `render_breach_pdf` is Task
    # 3's contract: given the assessment dict and an output path, it writes
    # the PDF itself (no bytes returned here to write).
    render_breach_pdf = None
    if args.pdf:
        try:
            from pii_redactor.breach_pdf import render_breach_pdf
        except ImportError:
            print(
                "Error: --pdf requires pii_redactor/breach_pdf.py, which is not yet available",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        result = assess_breach(args.paths, recursive=args.recursive)
    except NoFilesAssessedError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(
            f"Assessment failed to run: {_scrub_known_paths(str(e), args.paths)}", file=sys.stderr
        )
        sys.exit(1)

    payload = result.to_json_dict()

    # PDF before JSON: if the PDF write fails, nothing must be left behind.
    # The reverse order used to let a successful -o JSON survive a failed
    # --pdf, so exit 1 (a hard failure) still left an artifact on disk. The
    # mirror image is just as much a half-state: if the PDF write SUCCEEDS
    # and the JSON write then fails, a complete assessment PDF is left on
    # disk for a run that reports a hard failure and never mentions it. So on
    # any OSError here, a PDF this run wrote is deleted (best-effort) before
    # the error is reported.
    try:
        if render_breach_pdf is not None:
            render_breach_pdf(payload, args.pdf)
        if args.output:
            Path(args.output).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    except OSError as e:
        removed_pdf = False
        if render_breach_pdf is not None:
            pdf_path = Path(args.pdf)
            if pdf_path.exists():
                try:
                    pdf_path.unlink()
                    removed_pdf = True
                except OSError:
                    pass
        note = " -- deleted the assessment PDF already written this run" if removed_pdf else ""
        print(f"Error: cannot write assessment: {e}{note}", file=sys.stderr)
        sys.exit(1)

    _print_breach_summary(result, payload)
    if render_breach_pdf is not None:
        print(f"Assessment PDF written: {args.pdf}")
    if args.output:
        print(f"Assessment written: {args.output}")

    skipped = payload["files"]["skipped"]
    if skipped["count"]:
        print(f"ข้ามไฟล์ที่นามสกุลไม่รองรับ {skipped['count']} ไฟล์")
        for name in skipped["basenames"]:
            print(f"  - {name}")

    if result.files_failed:
        print(f"ไม่สำเร็จ {len(result.files_failed)} ไฟล์", file=sys.stderr)
        for failed in result.files_failed:
            print(f"  - {failed.basename} {failed.reason}", file=sys.stderr)
        sys.exit(2)


def cmd_receipt_verify(args):
    """Re-run a file and report whether it still matches its receipt."""
    from pii_redactor.receipt import verify_receipt

    try:
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Error: cannot read receipt {args.receipt}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = verify_receipt(receipt, args.file)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Verification failed to run: {e}", file=sys.stderr)
        sys.exit(1)

    if result.ok:
        print("ยืนยันได้ เอกสารและผลการตรวจตรงกับใบรับรอง")
    else:
        print(f"ยืนยันไม่ได้ ({result.outcome})")
    # Printed on both paths: on a match these lines are the environment that
    # differed anyway, which is the more interesting half of a passing check.
    for difference in result.differences:
        print(f"  - {difference}")

    if not result.ok:
        sys.exit(1)


def _usage_error_exits_one(self, message):
    """argparse's own default usage-error exit code is 2, but the breach
    verb's spec assigns 2 to "partial failure" (some files failed) and 1 to
    "usage error" -- a scripted caller needs to tell "you typed it wrong"
    apart from "some inputs failed". Bound onto `breach`-tree parsers only
    (see `main()`), so no other verb's usage-error exit code changes."""
    self.print_usage(sys.stderr)
    self.exit(1, f"{self.prog}: error: {message}\n")


class _BreachSubcommandParser(argparse.ArgumentParser):
    """Used as `parser_class=` for `breach`'s own nested subparsers action, so
    every parser it constructs (currently just `assess`) exits 1 on a usage
    error instead of argparse's stock 2. `breach_parser` itself (the outer
    "breach" level, whose required-subcommand check fires before this class
    is ever involved) gets the same behavior via a direct instance-level
    `error` bind in `main()` -- it is built by the shared top-level
    subparsers action alongside `sanitize`/`report`/`receipt`, so it cannot
    be given a different `parser_class` without affecting those too."""

    error = _usage_error_exits_one


def main():
    parser = argparse.ArgumentParser(
        prog="ai_guard",
        description="AI Guard — Thai PII redaction pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # sanitize subcommand
    sanitize_parser = subparsers.add_parser("sanitize", help="Sanitize a file")
    sanitize_parser.add_argument("file", help="Input file path")
    sanitize_parser.add_argument("--output", "-o", help="Output file path")
    sanitize_parser.add_argument("--fmt", choices=["txt", "pdf_text"], default="txt")
    sanitize_parser.add_argument("--provider", choices=["fake", "ollama", "claude"], default="fake")
    sanitize_parser.add_argument("--overwrite", action="store_true")
    sanitize_parser.set_defaults(func=cmd_sanitize)

    # report subcommand
    report_parser = subparsers.add_parser("report", help="Generate PII risk report")
    report_parser.add_argument("file", help="Input file path")
    report_parser.set_defaults(func=cmd_report)

    # receipt subcommand — issue and verify, deliberately one command apart.
    # A receipt nobody can check is a claim, not a record.
    receipt_parser = subparsers.add_parser(
        "receipt", help="Issue or verify a PDPA มาตรา 39 processing receipt"
    )
    receipt_sub = receipt_parser.add_subparsers(dest="receipt_command", required=True)

    issue_parser = receipt_sub.add_parser("issue", help="Issue a receipt for a file")
    issue_parser.add_argument("file", help="Input file path")
    issue_parser.add_argument(
        "--output", "-o", help="Write the receipt JSON here (default: stdout)"
    )
    issue_parser.add_argument("--pdf", help="Also render the receipt as a PDF at this path")
    issue_parser.add_argument("--purpose", help="Purpose of processing (PDPA s.39)")
    issue_parser.add_argument("--controller", help="Data controller (PDPA s.39)")
    issue_parser.add_argument("--overwrite", action="store_true")
    issue_parser.set_defaults(func=cmd_receipt_issue)

    verify_parser = receipt_sub.add_parser("verify", help="Verify a receipt against its file")
    verify_parser.add_argument("receipt", help="Receipt JSON path")
    verify_parser.add_argument("file", help="The original file the receipt was issued for")
    verify_parser.set_defaults(func=cmd_receipt_verify)

    # breach subcommand — one verb (assess) today, mirrors receipt's
    # sub-subparser shape so a future verb has somewhere to go.
    breach_parser = subparsers.add_parser(
        "breach", help="Assess files for a PDPA มาตรา 37(4) breach notification"
    )
    # Instance-level bind, not a parser_class swap: breach_parser is built by
    # the SAME top-level `subparsers` action as sanitize_parser/report_parser/
    # receipt_parser, so giving it a different class there would change those
    # too. Binding `error` directly on this one instance leaves every other
    # verb's parser (including receipt_parser and its own issue/verify
    # children) on argparse's stock exit-2 usage-error behavior.
    breach_parser.error = types.MethodType(_usage_error_exits_one, breach_parser)
    breach_sub = breach_parser.add_subparsers(
        dest="breach_command", required=True, parser_class=_BreachSubcommandParser
    )

    assess_parser = breach_sub.add_parser("assess", help="Assess files or directories")
    assess_parser.add_argument("paths", nargs="+", help="File or directory paths to assess")
    assess_parser.add_argument(
        "--output", "-o", help="Write the assessment JSON here (also prints a summary)"
    )
    assess_parser.add_argument("--pdf", help="Also render the assessment as a PDF at this path")
    assess_parser.add_argument(
        "--recursive", action="store_true", help="Scan directory paths recursively"
    )
    assess_parser.set_defaults(func=cmd_breach_assess)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
