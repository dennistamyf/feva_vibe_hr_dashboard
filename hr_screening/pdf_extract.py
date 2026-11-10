"""Local PDF text extraction.

Only extractable text is accepted. A PDF that cannot be opened or yields no
text raises a named error; it is never silently skipped.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from .errors import PdfExtractionError


def extract_pdf_text(path: Path) -> str:
    """Return the text of one PDF or raise ``PdfExtractionError``."""

    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise PdfExtractionError(f"CV PDF not found: {pdf_path.name} ({pdf_path})")

    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted:
            raise PdfExtractionError(
                f"CV PDF is encrypted and cannot be read: {pdf_path.name}"
            )
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages).replace("\x00", "").strip()
    except PdfExtractionError:
        raise
    except Exception as exc:  # pypdf raises several parser-specific types
        raise PdfExtractionError(
            f"CV PDF could not be read: {pdf_path.name} "
            f"({type(exc).__name__})."
        ) from exc

    if not text:
        raise PdfExtractionError(
            f"CV PDF contains no extractable text: {pdf_path.name}. "
            "The run was stopped before evaluating this candidate."
        )
    return text
