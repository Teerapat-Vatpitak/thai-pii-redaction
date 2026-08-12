"""Strict public Chrome Extension identity loading for package builds."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

_FIELDS = {
    "schema_version",
    "classification",
    "extension_id",
    "origin",
    "public_key",
    "provenance",
}
_EXTENSION_ID = re.compile(r"[a-p]{32}", re.ASCII)
_CLASSIFICATIONS = {"production_owner_approved", "synthetic_test_only"}


@dataclass(frozen=True)
class ExtensionIdentity:
    extension_id: str
    origin: str
    public_key: str
    classification: str


def _derive_extension_id(public_key: bytes) -> str:
    digest = hashlib.sha256(public_key).hexdigest()[:32]
    return "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)


def load_extension_identity(
    path: Path,
    *,
    allow_synthetic: bool = False,
) -> ExtensionIdentity:
    """Load an exact public identity and reject unproven or broad values."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid extension identity") from exc
    if not isinstance(raw, dict) or set(raw) != _FIELDS:
        raise ValueError("invalid extension identity fields")
    if raw["schema_version"] != 1:
        raise ValueError("invalid extension identity schema")
    if raw["classification"] not in _CLASSIFICATIONS:
        raise ValueError("invalid extension identity classification")
    if raw["classification"] != "production_owner_approved" and not allow_synthetic:
        raise ValueError("production identity required")
    if not isinstance(raw["provenance"], str) or not raw["provenance"].strip():
        raise ValueError("extension identity provenance required")
    extension_id = raw["extension_id"]
    origin = raw["origin"]
    public_key = raw["public_key"]
    if not isinstance(extension_id, str) or _EXTENSION_ID.fullmatch(extension_id) is None:
        raise ValueError("invalid extension ID")
    if origin != f"chrome-extension://{extension_id}/":
        raise ValueError("invalid extension origin")
    if not isinstance(public_key, str) or not (128 <= len(public_key) <= 8192):
        raise ValueError("invalid extension public key")
    try:
        decoded = base64.b64decode(public_key, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid extension public key") from exc
    if not (128 <= len(decoded) <= 4096) or decoded[:1] != b"\x30":
        raise ValueError("invalid extension public key")
    if base64.b64encode(decoded).decode("ascii") != public_key:
        raise ValueError("noncanonical extension public key")
    if _derive_extension_id(decoded) != extension_id:
        raise ValueError("extension ID does not match public key")
    return ExtensionIdentity(
        extension_id=extension_id,
        origin=origin,
        public_key=public_key,
        classification=raw["classification"],
    )
