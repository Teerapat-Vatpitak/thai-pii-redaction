"""AI Guard — Thai PII redaction pipeline CLI (PSU FTC 2026)."""
import argparse
import sys


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
    print(f"Entities detected: {len(result.entity_registry.entities)} "
          f"(FP={result.entity_registry.fp_count}, TB={result.entity_registry.tb_count})")

    if result.export_result:
        print(f"Output written: {result.export_result.output_path} "
              f"({result.export_result.byte_size} bytes)")
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


def main():
    parser = argparse.ArgumentParser(
        prog="ai_guard",
        description="AI Guard — Thai PII redaction pipeline (PSU FTC 2026)",
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
