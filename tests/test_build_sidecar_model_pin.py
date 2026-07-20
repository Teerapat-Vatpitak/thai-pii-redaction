"""REL-2: the PyThaiNLP NER model is fetched from an upstream corpus host at
build time and baked into the attested exe, outside the hash-pinned lockfile
chain. build_sidecar.py must verify its SHA256 against a pin recorded in the
repo, so a tampered upstream model cannot be bundled and then attested as
"built from this repo at this tag".
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "build_sidecar", ROOT / "scripts" / "build_sidecar.py"
)
build_sidecar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_sidecar)

MODEL = "thai-ner-1-4.crfsuite"


def _write(data_dir: Path, name: str, content: bytes) -> Path:
    p = data_dir / name
    p.write_bytes(content)
    return p


def test_pin_map_covers_the_ner_model():
    """The CRF model must actually be pinned — an empty map would make the
    verification a no-op."""
    assert MODEL in build_sidecar.PINNED_DATA_SHA256
    assert len(build_sidecar.PINNED_DATA_SHA256[MODEL]) == 64


def test_verify_accepts_matching_hash(tmp_path):
    content = b"pretend-model-bytes"
    _write(tmp_path, MODEL, content)
    pins = {MODEL: hashlib.sha256(content).hexdigest()}
    build_sidecar.verify_pinned_data(tmp_path, pins=pins, required=(MODEL,))


def test_verify_rejects_tampered_model(tmp_path):
    """A model whose bytes changed upstream must hard-fail the build."""
    _write(tmp_path, MODEL, b"tampered-model-bytes")
    pins = {MODEL: hashlib.sha256(b"the-known-good-bytes").hexdigest()}
    with pytest.raises(SystemExit) as exc:
        build_sidecar.verify_pinned_data(tmp_path, pins=pins, required=(MODEL,))
    assert MODEL in str(exc.value)


def test_verify_rejects_missing_required_model(tmp_path):
    """Refusing to ship is better than silently bundling nothing."""
    pins = {MODEL: "0" * 64}
    with pytest.raises(SystemExit):
        build_sidecar.verify_pinned_data(tmp_path, pins=pins, required=(MODEL,))


def test_verify_ignores_unpinned_files(tmp_path):
    """Files with no pin (e.g. the machine-specific db.json catalog) are skipped
    rather than failing the build."""
    content = b"model"
    _write(tmp_path, MODEL, content)
    _write(tmp_path, "db.json", b'{"local":"catalog"}')
    pins = {MODEL: hashlib.sha256(content).hexdigest()}
    build_sidecar.verify_pinned_data(tmp_path, pins=pins, required=(MODEL,))


def test_rejects_an_unpinned_model_alongside_the_pinned_one(tmp_path):
    """REL-2 gap: pythainlp's download() never unlinks a superseded model, so a
    newer thai-ner-1-5.crfsuite can sit next to the pinned 1-4. data_args()
    bundles EVERY non-.pth file, so an unpinned model would ride into the
    attested exe even though the pinned one verified clean."""
    content = b"model"
    _write(tmp_path, MODEL, content)
    _write(tmp_path, "thai-ner-1-5.crfsuite", b"unpinned-attacker-bytes")
    pins = {MODEL: hashlib.sha256(content).hexdigest()}
    with pytest.raises(SystemExit) as exc:
        build_sidecar.verify_pinned_data(tmp_path, pins=pins, required=(MODEL,))
    assert "thai-ner-1-5.crfsuite" in str(exc.value)


def test_recorded_pin_matches_the_real_model_when_present():
    """If this machine has the model downloaded, the pin in the repo must match
    it — otherwise the pin is stale and every build would fail."""
    pythainlp_tools = pytest.importorskip("pythainlp.tools")
    data_dir = Path(pythainlp_tools.get_pythainlp_data_path())
    model = data_dir / MODEL
    if not model.is_file():
        pytest.skip("NER model not downloaded on this machine")
    actual = hashlib.sha256(model.read_bytes()).hexdigest()
    assert actual == build_sidecar.PINNED_DATA_SHA256[MODEL], (
        "recorded pin does not match the local model; re-pin deliberately only "
        "after confirming why upstream changed"
    )
