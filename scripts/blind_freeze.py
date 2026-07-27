"""Freeze a blind-corpus draft: validate, encrypt, and write the lock file.

Usage (PowerShell, from the repo root):

    $env:PYTHONUTF8='1'
    .\\.venv\\Scripts\\python.exe scripts\\blind_freeze.py `
        --draft C:\\path\\outside\\repo\\blind-v1.draft.jsonl `
        --key-file C:\\path\\outside\\repo\\blind-v1.key

The draft plaintext and the key file must both live OUTSIDE the repository.
Validation errors are printed as (doc_id, error-kind) only — never values.
On success this writes ``benchmark/data/<version>.enc`` and
``benchmark/data/<version>.lock.json``, which are the only corpus artifacts
that belong in git. Back up the key file and the plaintext somewhere that is
not this repository (password manager / offline storage): losing the key
orphans the blob.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import blind


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="blind_freeze")
    ap.add_argument("--draft", required=True, help="plaintext draft JSONL, outside the repo")
    ap.add_argument("--key-file", required=True, help="hex key file, outside the repo")
    ap.add_argument("--version", default=blind.BLIND_VERSION)
    ap.add_argument("--reveal-budget", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="re-freeze an existing version")
    args = ap.parse_args(argv)

    key_path = Path(args.key_file)
    if not key_path.exists():
        blind.generate_key(key_path)
        print(f"generated new key file: {key_path}")

    try:
        lock = blind.freeze(
            args.draft,
            key_path,
            version=args.version,
            reveal_budget=args.reveal_budget,
            force=args.force,
        )
    except blind.BlindError as exc:
        print(f"freeze failed: {exc}", file=sys.stderr)
        return 1

    print(f"frozen {lock['version']}: {lock['documents']} documents")
    print(f"  slices: {lock['slice_counts']}")
    print(f"  types:  {lock['type_counts']}")
    print(f"  plaintext_sha256:  {lock['plaintext_sha256']}")
    print(f"  ciphertext_sha256: {lock['ciphertext_sha256']}")
    print("Back up the key file AND the plaintext outside this repository now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
