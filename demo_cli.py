#!/usr/bin/env python
"""Interactive demo: paste text, get sanitized output."""
import sys


def main():
    print("AI Guard Demo — Thai PII Redaction Pipeline")
    print("Paste text below (Ctrl+D to finish):")
    text = sys.stdin.read()

    if not text.strip():
        print("No input provided.", file=sys.stderr)
        sys.exit(1)

    from pii_redactor.pipeline import run_pipeline
    from pii_redactor.ai_client import FakeLLMProvider

    try:
        result = run_pipeline(text=text, provider=FakeLLMProvider())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n--- Pseudonymized (for AI) ---")
    print(result.pseudonymized_text)

    print("\n--- Restored Output ---")
    print(result.reverse_result.text)

    print(f"\nEntities: {len(result.entity_registry.entities)} "
          f"(FP={result.entity_registry.fp_count}, TB={result.entity_registry.tb_count})")


if __name__ == "__main__":
    main()
