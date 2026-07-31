"""Build three safe test inputs from each official blank form.

The source files do not change. All added values are synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODALITIES = ("digital", "print_like", "degraded")
DEFAULT_CORPUS = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path("benchmark/reports/gov-forms-phase2/inputs")
SYNTHETIC_BANNER = "SYNTHETIC TEST INPUT - NO REAL PERSONAL DATA"
TEXT_LAYER_SENTINEL = "." * 20
DEGRADED_ROTATION_DEGREES = 0.65


@dataclass(frozen=True)
class CorpusRow:
    form_code: str
    modality: str
    document: str
    expectations: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_pdf(path: Path, scale: float):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        return [
            (
                page.render(scale=scale).to_pil().convert("RGB"),
                tuple(float(v) for v in page.get_size()),
            )
            for page in doc
        ]
    finally:
        doc.close()


def _canvas(path: Path, page_size: tuple[float, float]):
    from reportlab.pdfgen import canvas

    return canvas.Canvas(
        str(path),
        pagesize=page_size,
        pageCompression=1,
        invariant=1,
    )


def _register_font(corpus_dir: Path) -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_name = "GovFormSynthetic"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        font_path = corpus_dir.parents[3] / "pii_redactor" / "fonts"
        font_path /= "IBMPlexSansThaiLooped-Regular.ttf"
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    return font_name


def _write_digital(
    source: Path,
    output: Path,
    form: dict,
    corpus_dir: Path,
) -> None:
    from PIL import ImageDraw, ImageFont
    from reportlab.lib.colors import black
    from reportlab.lib.utils import ImageReader

    pages = _render_pdf(source, scale=2.0)
    font_name = _register_font(corpus_dir)
    c = _canvas(output, pages[0][1])
    c.setCreator("AI Guard deterministic government-form probe")
    c.setTitle(f"Synthetic {form['code']} probe input")

    for page_number, (image, (width, height)) in enumerate(pages, start=1):
        c.setPageSize((width, height))
        draw = ImageDraw.Draw(image)
        draw.text(
            (24, 4),
            SYNTHETIC_BANNER,
            fill=(115, 115, 115),
            font=ImageFont.load_default(),
        )
        c.drawImage(ImageReader(image), 0, 0, width=width, height=height)

        page_fields = [field for field in form["synthetic_fields"] if field["page"] == page_number]
        if not page_fields:
            # Keep an empty image page as a digital PDF. Do not add words.
            text = c.beginText(12, 12)
            text.setTextRenderMode(3)
            text.setFont("Helvetica", 6)
            text.textOut(TEXT_LAYER_SENTINEL)
            c.drawText(text)

        c.setFillColor(black)
        for field in page_fields:
            c.setFont(font_name, field.get("font_size", 9))
            c.drawString(field["x"], height - field["y"], field["value"])
        c.showPage()
    c.save()


def _write_image_pdf(
    images,
    output: Path,
) -> None:
    from reportlab.lib.utils import ImageReader

    c = _canvas(output, images[0][1])
    c.setCreator("AI Guard deterministic government-form probe")
    for image, (width, height) in images:
        c.setPageSize((width, height))
        c.drawImage(ImageReader(image), 0, 0, width=width, height=height)
        c.showPage()
    c.save()


def _degrade(image):
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    gray = ImageOps.grayscale(image)
    small = gray.resize(
        (max(1, round(gray.width * 0.68)), max(1, round(gray.height * 0.68))),
        Image.Resampling.LANCZOS,
    )
    restored = small.resize(gray.size, Image.Resampling.BILINEAR)
    rotated = restored.rotate(
        DEGRADED_ROTATION_DEGREES,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor=245,
    )
    softened = (
        ImageEnhance.Contrast(rotated).enhance(0.82).filter(ImageFilter.GaussianBlur(radius=0.45))
    )

    # Use fixed JPEG settings. Do not add random noise.
    encoded = io.BytesIO()
    softened.save(
        encoded,
        format="JPEG",
        quality=58,
        subsampling=2,
        optimize=False,
        progressive=False,
    )
    encoded.seek(0)
    return Image.open(encoded).convert("RGB")


def _base_region(field: dict[str, Any], font_name: str) -> dict[str, float | int]:
    from reportlab.pdfbase import pdfmetrics

    font_size = field.get("font_size", 9)
    ascent, descent = pdfmetrics.getAscentDescent(font_name, font_size)
    return {
        "page": int(field["page"]),
        "x": float(field["x"]),
        "y": float(field["y"] - ascent),
        "width": float(pdfmetrics.stringWidth(field["value"], font_name, font_size)),
        "height": float(ascent - descent),
    }


def _rotate_region(
    region: dict[str, float | int],
    page_size: tuple[float, float],
) -> dict[str, float | int]:
    angle = math.radians(DEGRADED_ROTATION_DEGREES)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    center_x = page_size[0] / 2
    center_y = page_size[1] / 2

    def rotate(x: float, y: float) -> tuple[float, float]:
        offset_x = x - center_x
        offset_y = y - center_y
        return (
            center_x + cosine * offset_x + sine * offset_y,
            center_y - sine * offset_x + cosine * offset_y,
        )

    x = float(region["x"])
    y = float(region["y"])
    width = float(region["width"])
    height = float(region["height"])
    corners = (
        rotate(x, y),
        rotate(x + width, y),
        rotate(x, y + height),
        rotate(x + width, y + height),
    )
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return {
        "page": region["page"],
        "x": min(xs),
        "y": min(ys),
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
    }


def _field_region(
    field: dict[str, Any],
    modality: str,
    page_sizes: list[tuple[float, float]],
    font_name: str,
) -> dict[str, float | int]:
    region = _base_region(field, font_name)
    if modality == "degraded":
        region = _rotate_region(region, page_sizes[field["page"] - 1])
    return {
        key: value if key == "page" else round(float(value), 6) for key, value in region.items()
    }


def _write_expectations(
    path: Path,
    form: dict,
    modality: str,
    page_sizes: list[tuple[float, float]],
    font_name: str,
) -> None:
    payload = {
        "meta": {
            "form_code": form["code"],
            "form_name": form["name"],
            "modality": modality,
            "synthetic_only": True,
            "provenance": (
                "Official blank form identified by manifest SHA-256; values are "
                "fabricated constants declared in that manifest."
            ),
            "region_space": "pdf_points_top_left",
        },
        "layout": form["layout"],
        "fields": [
            {
                "field": field["field"],
                "value": field["value"],
                "type": field["type"],
                "region": _field_region(field, modality, page_sizes, font_name),
            }
            for field in form["synthetic_fields"]
        ],
        "decoys": form["decoys"],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def generate_corpus(corpus_dir: str | Path, output_dir: str | Path) -> list[CorpusRow]:
    """Generate nine inputs after checking each source hash."""

    corpus_dir = Path(corpus_dir)
    output_dir = Path(output_dir)
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    rows: list[CorpusRow] = []
    font_name = _register_font(corpus_dir)

    for form in manifest["forms"]:
        source = corpus_dir / form["official_path"]
        actual = _sha256(source)
        if actual != form["artifact_sha256"]:
            raise ValueError(
                f"official source hash mismatch for {source}: "
                f"expected {form['artifact_sha256']}, got {actual}"
            )

        form_dir = output_dir / form["slug"]
        form_dir.mkdir(parents=True, exist_ok=True)
        digital = form_dir / f"{form['slug']}-digital.pdf"
        _write_digital(source, digital, form, corpus_dir)

        digital_pages = _render_pdf(digital, scale=2.0)
        print_like = form_dir / f"{form['slug']}-print-like.pdf"
        _write_image_pdf(digital_pages, print_like)

        degraded = form_dir / f"{form['slug']}-degraded.pdf"
        degraded_pages = [(_degrade(image), size) for image, size in digital_pages]
        _write_image_pdf(degraded_pages, degraded)
        page_sizes = [size for _image, size in digital_pages]

        documents = {
            "digital": digital,
            "print_like": print_like,
            "degraded": degraded,
        }
        for modality in MODALITIES:
            expected = form_dir / f"{form['slug']}-{modality}.expected.json"
            _write_expectations(
                expected,
                form,
                modality,
                page_sizes,
                font_name,
            )
            rows.append(
                CorpusRow(
                    form_code=form["code"],
                    modality=modality,
                    document=documents[modality].relative_to(output_dir).as_posix(),
                    expectations=expected.relative_to(output_dir).as_posix(),
                )
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    rows = generate_corpus(args.corpus_dir, args.output_dir)
    for row in rows:
        print(f"{row.form_code}\t{row.modality}\t{row.document}\t{row.expectations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
