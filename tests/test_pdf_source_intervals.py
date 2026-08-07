"""Adversarial contracts for authoritative PDF source-to-box intervals."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from pii_redactor.models import Entity, EntityRegistry, WordBbox

SYNTHETIC_MARKER = "synthetic-marker"


def _entity(start: int, text: str = SYNTHETIC_MARKER, *, entity_id: str = "synthetic") -> Entity:
    return Entity(
        entity_id=entity_id,
        redact_type="TB",
        data_type="NAME",
        span=(start, start + len(text)),
        score=1.0,
        original_text=text,
    )


def _registry(*entities: Entity) -> EntityRegistry:
    return EntityRegistry(entities=list(entities), fp_count=0, tb_count=len(entities))


def _box(
    text: str,
    *,
    page: int,
    x: float,
    source_span: tuple[int, int] | None,
    y: float = 72.0,
) -> WordBbox:
    box = WordBbox(
        text=text,
        page=page,
        x=x,
        y=y,
        width=max(12.0, len(text) * 6.0),
        height=12.0,
    )
    # This assignment keeps the tests runnable against the unchanged base,
    # where WordBbox has not gained the field yet.
    box.source_span = source_span
    return box


def _mapped_x(registry: EntityRegistry, boxes: list[WordBbox]) -> list[list[float]]:
    from pii_redactor.redactor import _map_entities_to_boxes

    return [[box.x for box in mapped] for mapped in _map_entities_to_boxes(registry, boxes)]


def _make_pdf(tmp_path: Path, pages: list[list[tuple[float, float, str]]]) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path = tmp_path / "source-intervals.pdf"
    output = canvas.Canvas(str(path), pagesize=letter)
    output.setFont("Helvetica", 12)
    for page_index, rows in enumerate(pages):
        for x, top, text in rows:
            output.drawString(x, letter[1] - top, text)
        if page_index + 1 < len(pages):
            output.showPage()
            output.setFont("Helvetica", 12)
    output.save()
    return path


def _is_solid_black(pdf_path: Path, page_index: int, box: WordBbox) -> bool:
    import pypdfium2 as pdfium

    from pii_redactor.redactor import RENDER_SCALE

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        image = document[page_index].render(scale=RENDER_SCALE).to_pil().convert("L")
    finally:
        document.close()
    region = image.crop(
        (
            int(box.x * RENDER_SCALE),
            int(box.y * RENDER_SCALE),
            int((box.x + box.width) * RENDER_SCALE),
            int((box.y + box.height) * RENDER_SCALE),
        )
    )
    return bool(region.width and region.height and region.getextrema()[1] < 10)


def test_repeated_identical_boxes_use_only_the_selected_source_occurrence():
    gap = len(SYNTHETIC_MARKER) + 1
    boxes = [
        _box(SYNTHETIC_MARKER, page=1, x=10, source_span=(0, len(SYNTHETIC_MARKER))),
        _box(
            SYNTHETIC_MARKER,
            page=1,
            x=110,
            source_span=(gap, gap + len(SYNTHETIC_MARKER)),
        ),
    ]

    assert _mapped_x(_registry(_entity(0)), boxes) == [[10]]


def test_identical_values_at_distinct_offsets_are_independently_selected():
    gap = len(SYNTHETIC_MARKER) + 1
    boxes = [
        _box(SYNTHETIC_MARKER, page=1, x=10, source_span=(0, len(SYNTHETIC_MARKER))),
        _box(
            SYNTHETIC_MARKER,
            page=1,
            x=110,
            source_span=(gap, gap + len(SYNTHETIC_MARKER)),
        ),
    ]

    assert _mapped_x(
        _registry(_entity(0, entity_id="first"), _entity(gap, entity_id="second")),
        boxes,
    ) == [[10], [110]]


def test_same_value_on_another_page_cannot_match_the_wrong_page():
    gap = len(SYNTHETIC_MARKER) + 2
    boxes = [
        _box(SYNTHETIC_MARKER, page=1, x=10, source_span=(0, len(SYNTHETIC_MARKER))),
        _box(
            SYNTHETIC_MARKER,
            page=2,
            x=210,
            source_span=(gap, gap + len(SYNTHETIC_MARKER)),
        ),
    ]

    assert _mapped_x(_registry(_entity(gap)), boxes) == [[210]]


def test_prefix_and_suffix_similarity_do_not_widen_selection():
    longer = f"{SYNTHETIC_MARKER}-tail"
    second_start = len(SYNTHETIC_MARKER) + 1
    boxes = [
        _box(SYNTHETIC_MARKER, page=1, x=10, source_span=(0, len(SYNTHETIC_MARKER))),
        _box(
            longer,
            page=1,
            x=110,
            source_span=(second_start, second_start + len(longer)),
        ),
    ]

    assert _mapped_x(_registry(_entity(0)), boxes) == [[10]]


def test_overlapping_and_adjacent_source_fragments_map_deterministically():
    boxes = [
        _box("abcde", page=1, x=10, source_span=(0, 5)),
        _box("defgh", page=1, x=50, source_span=(3, 8)),
        _box("ij", page=1, x=90, source_span=(8, 10)),
    ]
    first = _entity(2, "cdef", entity_id="overlap")
    second = _entity(8, "ij", entity_id="adjacent")

    assert _mapped_x(_registry(first, second), boxes) == [[10, 50], [90]]


def test_entity_crossing_boxes_and_newline_maps_every_fragment():
    text = "alpha\nbeta"
    boxes = [
        _box("alpha", page=1, x=10, source_span=(0, 5)),
        _box("beta", page=1, x=60, source_span=(6, 10)),
    ]

    assert _mapped_x(_registry(_entity(0, text)), boxes) == [[10, 60]]


def test_thai_combining_characters_keep_python_character_offsets():
    text = "ก\u0e49า"
    boxes = [_box(text, page=1, x=10, source_span=(0, len(text)))]

    assert _mapped_x(_registry(_entity(0, text)), boxes) == [[10]]


def test_conflicting_pages_for_the_same_source_interval_fail_closed():
    boxes = [
        _box(SYNTHETIC_MARKER, page=1, x=10, source_span=(0, len(SYNTHETIC_MARKER))),
        _box(SYNTHETIC_MARKER, page=2, x=20, source_span=(0, len(SYNTHETIC_MARKER))),
    ]

    with pytest.raises(Exception) as excinfo:
        _mapped_x(_registry(_entity(0)), boxes)

    assert type(excinfo.value).__name__ == "PdfSourceMappingError"
    assert SYNTHETIC_MARKER not in str(excinfo.value)


def test_malformed_inconsistent_and_uncovered_intervals_fail_closed():
    from pii_redactor.redactor import PdfSourceMappingError, _map_entities_to_boxes

    cases = [
        (_registry(_entity(0, "alpha")), [_box("alpha", page=1, x=10, source_span=(0, 4))]),
        (_registry(_entity(0, "alpha")), [_box("omega", page=1, x=10, source_span=(0, 5))]),
        (_registry(_entity(0, "alpha")), [_box("alph", page=1, x=10, source_span=(0, 4))]),
    ]

    for registry, boxes in cases:
        with pytest.raises(PdfSourceMappingError) as excinfo:
            _map_entities_to_boxes(registry, boxes)
        assert "alpha" not in str(excinfo.value)


def test_box_page_outside_the_document_fails_closed():
    from pii_redactor.redactor import PdfSourceMappingError, _map_entities_to_boxes

    box = _box("alpha", page=2, x=10, source_span=(0, 5))
    with pytest.raises(PdfSourceMappingError):
        _map_entities_to_boxes(_registry(_entity(0, "alpha")), [box], page_count=1)


def test_text_extractors_return_exact_source_slices_on_each_page(tmp_path):
    from pii_redactor.ingest.text_extractor import _extract_pdf_pypdfium2, extract

    source = _make_pdf(
        tmp_path,
        [
            [(50, 72, "alpha  beta"), (50, 96, "line two")],
            [(50, 72, "gamma delta")],
        ],
    )

    for text, boxes in (
        extract(source, "pdf_text")[:2],
        _extract_pdf_pypdfium2(source),
    ):
        assert boxes
        assert {box.page for box in boxes} == {1, 2}
        assert "\r\n" not in text
        assert "\n" in text
        for box in boxes:
            assert box.source_span is not None
            start, end = box.source_span
            assert text[start:end] == box.text
        page_one_end = max(box.source_span[1] for box in boxes if box.page == 1)
        page_two_start = min(box.source_span[0] for box in boxes if box.page == 2)
        assert page_one_end < page_two_start
        assert "\n\n" in text[page_one_end:page_two_start]


def test_pdfplumber_keeps_thai_combining_character_offsets(tmp_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    from pii_redactor.ingest.text_extractor import extract

    font_path = (
        Path(__file__).resolve().parents[1]
        / "pii_redactor"
        / "fonts"
        / "IBMPlexSansThaiLooped-Regular.ttf"
    )
    font_name = "AIGuardSyntheticThaiIntervals"
    pdfmetrics.registerFont(TTFont(font_name, font_path))
    source = tmp_path / "thai-combining.pdf"
    output = canvas.Canvas(str(source), pagesize=letter)
    output.setFont(font_name, 12)
    marker = "ก\u0e49า"
    output.drawString(50, letter[1] - 72, f"{marker} ทดสอบ")
    output.save()

    text, boxes, _meta = extract(source, "pdf_text")

    start = text.index(marker)
    marker_boxes = [
        box
        for box in boxes
        if box.source_span is not None
        and box.source_span[0] < start + len(marker)
        and start < box.source_span[1]
    ]
    assert marker_boxes
    assert all(text[slice(*box.source_span)] == box.text for box in marker_boxes)


def test_real_redaction_leaves_the_undetected_identical_occurrence_untouched(tmp_path):
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.redactor import redact_pdf

    source = _make_pdf(
        tmp_path,
        [
            [
                (50, 72, SYNTHETIC_MARKER),
                (50, 120, SYNTHETIC_MARKER),
            ]
        ],
    )
    text, boxes, _meta = extract(source, "pdf_text")
    starts = [index for index in range(len(text)) if text.startswith(SYNTHETIC_MARKER, index)]
    marker_boxes = [box for box in boxes if box.text == SYNTHETIC_MARKER]
    assert len(starts) == len(marker_boxes) == 2
    for box, start in zip(marker_boxes, starts):
        box.source_span = (start, start + len(SYNTHETIC_MARKER))

    output = tmp_path / "one-occurrence-redacted.pdf"
    redact_pdf(str(source), _registry(_entity(starts[0])), boxes, str(output))

    assert _is_solid_black(output, 0, marker_boxes[0])
    assert not _is_solid_black(output, 0, marker_boxes[1])


def test_real_redaction_does_not_cross_page_boundaries(tmp_path):
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.redactor import redact_pdf

    source = _make_pdf(
        tmp_path,
        [
            [(50, 72, SYNTHETIC_MARKER)],
            [(50, 72, SYNTHETIC_MARKER)],
        ],
    )
    text, boxes, _meta = extract(source, "pdf_text")
    starts = [index for index in range(len(text)) if text.startswith(SYNTHETIC_MARKER, index)]
    marker_boxes = [box for box in boxes if box.text == SYNTHETIC_MARKER]
    assert len(starts) == len(marker_boxes) == 2
    for box, start in zip(marker_boxes, starts):
        box.source_span = (start, start + len(SYNTHETIC_MARKER))

    output = tmp_path / "page-two-redacted.pdf"
    redact_pdf(str(source), _registry(_entity(starts[1])), boxes, str(output))

    assert not _is_solid_black(output, 0, marker_boxes[0])
    assert _is_solid_black(output, 1, marker_boxes[1])


def test_unmappable_interval_fails_before_output_and_drops_input_graph(tmp_path):
    from pii_redactor.redactor import redact_pdf

    source = _make_pdf(tmp_path, [[(50, 72, SYNTHETIC_MARKER)]])
    output = tmp_path / "must-not-exist.pdf"
    box = _box(SYNTHETIC_MARKER, page=1, x=50, source_span=None)

    with pytest.raises(Exception) as excinfo:
        redact_pdf(str(source), _registry(_entity(0)), [box], str(output))

    error = excinfo.value
    assert type(error).__name__ == "PdfSourceMappingError"
    assert SYNTHETIC_MARKER not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    traceback = error.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module.startswith("pii_redactor."):
            assert SYNTHETIC_MARKER not in repr(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next
    assert not output.exists()


def test_http_mapping_failure_keeps_the_existing_fixed_v2_error(
    client,
    tmp_path,
    monkeypatch,
):
    from app import server

    source = _make_pdf(tmp_path, [[(50, 72, SYNTHETIC_MARKER)]])
    box = _box(SYNTHETIC_MARKER, page=1, x=50, source_span=None)
    entity = _entity(0)
    monkeypatch.setattr(server, "detect_source_type", lambda _path: "pdf_text")
    monkeypatch.setattr(server, "extract", lambda *_args: (SYNTHETIC_MARKER, [box], {}))
    monkeypatch.setattr(server, "detect_all", lambda _text: [entity])

    response = client.post(
        "/api/redact-pdf",
        files={"pdf_file": ("synthetic.pdf", source.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "status": 500,
        "category": "internal",
        "count": 0,
        "retryable": False,
    }
    assert SYNTHETIC_MARKER not in response.text


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.server import app

    return TestClient(
        app,
        base_url="http://localhost",
        headers={"X-AIGuard-Contract-Version": "2"},
    )
