"""AI Guard — Thai PII redaction pipeline CLI."""

import argparse
import json
import sys
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
    from pii_redactor.detectors.aggregate import dedupe_spans
    from pii_redactor.detectors.fp_detector import detect_fp
    from pii_redactor.detectors.tb_detector import detect_tb
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

    # Resolve FP/TB span overlaps (FP wins, checksum-backed) before counting —
    # the same central rule the pipeline/web path use. Summing raw len(fp)+
    # len(tb) double-counts a value both detectors matched (e.g. an ID the NER
    # also tags), inflating the total past the risk-level thresholds.
    merged = dedupe_spans(detect_fp(text) + detect_tb(text))
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

    blob = json.dumps(receipt, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(blob + "\n", encoding="utf-8")
        print(f"Receipt written: {args.output}")
    else:
        print(blob)

    if args.pdf:
        from pii_redactor.receipt_pdf import render_receipt

        Path(args.pdf).write_bytes(render_receipt(receipt))
        print(f"Receipt PDF written: {args.pdf}")


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
    issue_parser.set_defaults(func=cmd_receipt_issue)

    verify_parser = receipt_sub.add_parser("verify", help="Verify a receipt against its file")
    verify_parser.add_argument("receipt", help="Receipt JSON path")
    verify_parser.add_argument("file", help="The original file the receipt was issued for")
    verify_parser.set_defaults(func=cmd_receipt_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
