from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from scripts.native_host_identity import ExtensionIdentity, load_extension_identity

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "native_host" / "synthetic-extension-identity.json"
PRODUCTION_IDENTITY = ROOT / "config" / "chrome-extension-identity.json"


def _derived_id(public_key: str) -> str:
    digest = hashlib.sha256(base64.b64decode(public_key, validate=True)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)


def test_synthetic_identity_is_public_only_self_consistent_and_explicitly_nonproduction():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert raw["classification"] == "synthetic_test_only"
    assert raw["extension_id"] == _derived_id(raw["public_key"])
    assert raw["origin"] == f"chrome-extension://{raw['extension_id']}/"
    encoded = FIXTURE.read_text(encoding="utf-8").casefold()
    assert "private key" not in encoded
    assert "private_key" not in encoded


def test_owner_approved_production_identity_is_exact_and_self_consistent():
    raw = json.loads(PRODUCTION_IDENTITY.read_text(encoding="utf-8"))
    decoded = base64.b64decode(raw["public_key"], validate=True)

    assert raw["classification"] == "production_owner_approved"
    assert hashlib.sha256(decoded).hexdigest() == (
        "a39caad436c5f7fa97937c90304b666c02f37c16a30607e985c9ec653b9dc256"
    )
    assert raw["extension_id"] == _derived_id(raw["public_key"])
    assert raw["extension_id"] == "kdjmkknedgmfphpkjhjdhmjadaelgggm"
    assert raw["origin"] == "chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/"
    encoded = PRODUCTION_IDENTITY.read_text(encoding="utf-8").casefold()
    assert "begin public key" not in encoded
    assert "private key" not in encoded
    assert "private_key" not in encoded


def test_identity_loader_accepts_production_identity_without_test_override():
    identity = load_extension_identity(PRODUCTION_IDENTITY)

    assert identity.extension_id == "kdjmkknedgmfphpkjhjdhmjadaelgggm"
    assert identity.origin == "chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/"
    assert identity.classification == "production_owner_approved"


def test_identity_loader_rejects_test_identity_without_an_explicit_acceptance_flag():
    with pytest.raises(ValueError, match="production identity required"):
        load_extension_identity(FIXTURE)


def test_identity_loader_accepts_the_isolated_fixture_only_when_explicitly_enabled():
    identity = load_extension_identity(FIXTURE, allow_synthetic=True)
    assert identity == ExtensionIdentity(
        extension_id="efocdbdljgaaiflfleofbjpenncenhee",
        origin="chrome-extension://efocdbdljgaaiflfleofbjpenncenhee/",
        public_key=json.loads(FIXTURE.read_text(encoding="utf-8"))["public_key"],
        classification="synthetic_test_only",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("extension_id", "a" * 32),
        ("origin", "chrome-extension://" + "a" * 32 + "/"),
        ("origin", "chrome-extension://*/"),
        ("public_key", "not-base64"),
        ("classification", "owner_says_ok"),
    ],
)
def test_identity_loader_rejects_mismatched_broad_or_unproven_values(tmp_path, field, value):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw[field] = value
    candidate = tmp_path / "identity.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_extension_identity(candidate, allow_synthetic=True)


def test_identity_loader_rejects_unknown_fields(tmp_path):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["private_key"] = "forbidden"
    candidate = tmp_path / "identity.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="identity fields"):
        load_extension_identity(candidate, allow_synthetic=True)
