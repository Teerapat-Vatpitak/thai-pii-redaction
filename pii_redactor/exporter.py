"""Export final de-anonymized output to file (Step 8).

Formats: txt, pdf_text
Pre-export validation checks halt flag, path writability, format support.
"""

from dataclasses import dataclass
from pathlib import Path

from pii_redactor.models import ReverseResult
from pii_redactor.output_validator import ValidationResult

# Thai-capable TrueType font for pdf_text export. Falls back to reportlab's
# built-in Helvetica (Latin-only) if not found -- Thai glyphs simply won't
# render in that case, same trade-off examples/make_sample_pdf.py accepts.
_THAI_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\sarabun-v17-latin_latin-ext_thai_vietnamese-regular.ttf",
    "/usr/share/fonts/truetype/thai/Sarabun-Regular.ttf",
    # fonts-thai-tlwg (Debian/Ubuntu, incl. CI + Docker): Laksaman is the
    # TH Sarabun New derivative the package actually ships.
    "/usr/share/fonts/truetype/tlwg/Laksaman.ttf",
]
_PDF_TEXT_FONT_NAME = "Sarabun"


@dataclass
class ExportResult:
    """Result of successful export."""

    output_path: Path
    format: str  # "txt" | "pdf_text"
    byte_size: int
    warnings: list[str]


class ExportError(Exception):
    """Raised when export cannot proceed (critical flag, unwritable path, unsupported format)."""

    pass


def _check_pre_export(
    validation_result: ValidationResult,
    output_path: Path,
    fmt: str,
    overwrite: bool,
) -> None:
    """
    Pre-export validation checks.

    Raises ExportError if:
    - validation_result.halt is True
    - fmt not in {"txt", "pdf_text"}
    - output file exists and overwrite=False
    - output directory not writable
    """
    if validation_result.halt:
        raise ExportError("Export blocked: validation_result.halt=True (layer3 integrity failure)")

    if fmt not in {"txt", "pdf_text"}:
        raise ExportError(f"Unsupported format: {fmt!r}. Supported: txt, pdf_text")

    if output_path.exists() and not overwrite:
        raise ExportError(
            f"Output file already exists: {output_path}. Use overwrite=True to replace."
        )

    # Check parent directory writable
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Try creating a temp probe
        probe = output_path.parent / ".write_probe"
        probe.touch()
        probe.unlink()
    except (PermissionError, OSError) as e:
        raise ExportError(f"Output directory not writable: {e}")


def _export_txt(text: str, output_path: Path) -> int:
    """Write text to .txt file. Returns byte size."""
    encoded = text.encode("utf-8")
    output_path.write_bytes(encoded)
    return len(encoded)


def _register_thai_font() -> str:
    """Register a Thai-capable TTF with reportlab; fall back to Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = next((f for f in _THAI_FONT_CANDIDATES if Path(f).exists()), None)
    if font_path is None:
        return "Helvetica"

    if _PDF_TEXT_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_PDF_TEXT_FONT_NAME, font_path))
    return _PDF_TEXT_FONT_NAME


def _export_pdf_text(text: str, output_path: Path) -> int:
    """Create a simple text-based PDF using reportlab. Returns byte size."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    font_name = _register_thai_font()

    c = canvas.Canvas(str(output_path), pagesize=letter)
    page_width, page_height = letter
    c.setFont(font_name, 11)

    # Split into lines and insert at fixed positions.
    # Use a simple layout: start from (50, height - 72) with line height 14,
    # matching the previous top-down layout (fitz used a top-left origin;
    # reportlab uses bottom-left, hence the page_height flip).
    x = 50
    y = page_height - 72
    line_height = 14

    lines = text.split("\n")
    for line in lines:
        if y < 50:
            c.showPage()
            c.setFont(font_name, 11)
            y = page_height - 72
        c.drawString(x, y, line)
        y -= line_height

    c.save()
    return output_path.stat().st_size


def export(
    reverse_result: ReverseResult,
    validation_result: ValidationResult,
    output_path: str,
    *,
    fmt: str = "txt",
    overwrite: bool = False,
) -> ExportResult:
    """
    Export final de-anonymized output to file.

    Pre-export checks:
    1. validation_result.halt == True → raise ExportError
    2. output path not writable → raise ExportError
    3. fmt not in {"txt", "pdf_text"} → raise ExportError
    4. output file exists and overwrite=False → raise ExportError

    Args:
        reverse_result: Final text output with real data restored
        validation_result: 3-layer validation result
        output_path: Path to write output file
        fmt: Output format ("txt" or "pdf_text")
        overwrite: If True, replace existing file; otherwise raise ExportError

    Returns:
        ExportResult with output path, format, byte size, and warnings

    Raises:
        ExportError: If any pre-export check fails
    """
    path = Path(output_path)
    warnings = []

    # Pre-export checks
    _check_pre_export(validation_result, path, fmt, overwrite)

    # Collect Layer 2 warnings (non-halting flags)
    if not validation_result.layer2_completeness_ok:
        warnings.extend([f for f in validation_result.flags if "incomplete" in f or "residue" in f])

    text = reverse_result.text

    if fmt == "txt":
        byte_size = _export_txt(text, path)
    elif fmt == "pdf_text":
        byte_size = _export_pdf_text(text, path)

    return ExportResult(
        output_path=path,
        format=fmt,
        byte_size=byte_size,
        warnings=warnings,
    )
