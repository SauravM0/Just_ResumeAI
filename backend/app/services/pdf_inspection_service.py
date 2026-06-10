"""PDF text extraction and page-count helpers for final ATS validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class PDFInspectionResult(BaseModel):
    text: str = ""
    page_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class PDFInspectionError(RuntimeError):
    """Raised when a generated PDF cannot be inspected."""


def inspect_pdf(pdf_path: str) -> PDFInspectionResult:
    path = Path(pdf_path)
    if not path.exists():
        raise PDFInspectionError(f"PDF file not found: {path}")

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PDFInspectionError("pypdf is required for PDF text extraction and page counting.") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise PDFInspectionError(f"Could not read generated PDF: {exc}") from exc

    warnings: list[str] = []
    page_text: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            warnings.append(f"Could not extract text from page {index}: {exc}")
            text = ""
        page_text.append(text)

    combined = "\n".join(part.strip() for part in page_text if part and part.strip()).strip()
    if not combined:
        warnings.append("No extractable text was found in the generated PDF.")

    return PDFInspectionResult(
        text=combined,
        page_count=len(reader.pages),
        warnings=warnings,
    )
