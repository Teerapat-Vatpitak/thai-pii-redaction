"""Build three safe test inputs from each official blank form.

The source files do not change. All added values are synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

MODALITIES = ("digital", "print_like", "degraded")
DEFAULT_CORPUS = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path("benchmark/reports/gov-forms-phase2/inputs")


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
    from reportlab.lib.colors import Color, black
    from reportlab.lib.utils import ImageReader

    pages = _render_pdf(source, scale=2.0)
    font_name = _register_font(corpus_dir)
    c = _canvas(output, pages[0][1])
    c.setCreator("AI Guard deterministic government-form probe")
    c.setTitle(f"Synthetic {form['code']} probe input")

    for page_number, (image, (width, height)) in enumerate(pages, start=1):
        c.setPageSize((width, height))
        c.drawImage(ImageReader(image), 0, 0, width=width, height=height)

        # Keep every digital page on the text-layer path.
        c.setFillColor(Color(0.45, 0.45, 0.45))
        c.setFont("Helvetica", 6)
        c.drawString(12, height - 12, "SYNTHETIC TEST INPUT - NO REAL PERSONAL DATA")

        c.setFillColor(black)
        for field in form["synthetic_fields"]:
            if field["page"] != page_number:
                continue
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
        0.65,
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


def _write_expectations(path: Path, form: dict, modality: str) -> None:
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
        },
        "layout": form["layout"],
        "fields": [
            {
                "field": field["field"],
                "value": field["value"],
                "type": field["type"],
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

        documents = {
            "digital": digital,
            "print_like": print_like,
            "degraded": degraded,
        }
        for modality in MODALITIES:
            expected = form_dir / f"{form['slug']}-{modality}.expected.json"
            _write_expectations(expected, form, modality)
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
