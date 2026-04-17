"""
PDF compile service — compiles LaTeX source to PDF.

For MVP, this uses a subprocess call to pdflatex.
Production upgrade: use a Docker-based LaTeX compiler or an API service.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


class PDFCompileError(Exception):
    """Raised when LaTeX compilation fails."""

    def __init__(self, message: str, errors: list[str]):
        super().__init__(message)
        self.errors = errors


async def compile_pdf(
    latex_source: str,
    session_id: str,
) -> tuple[str, list[str]]:
    """
    Compile LaTeX source to PDF.

    Args:
        latex_source: Full LaTeX document source.
        session_id: Session ID for output file naming.

    Returns:
        Tuple of (pdf_file_path, compile_warnings).

    Raises:
        PDFCompileError: If compilation fails.
    """
    settings = get_settings()
    output_dir = Path(settings.LATEX_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write LaTeX source to temp file
    tex_filename = f"resume_{session_id}_{uuid.uuid4().hex[:6]}.tex"
    tex_path = output_dir / tex_filename
    pdf_path = tex_path.with_suffix(".pdf")
    log_path = tex_path.with_suffix(".log")

    tex_path.write_text(latex_source, encoding="utf-8")

    try:
        # Run pdflatex twice (for references/formatting)
        for pass_num in range(2):
            process = await asyncio.create_subprocess_exec(
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={output_dir}",
                str(tex_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0 and pass_num == 1:
                # Parse errors from log
                errors = _parse_latex_errors(log_path)
                raise PDFCompileError(
                    f"pdflatex exited with code {process.returncode}",
                    errors=errors,
                )

        # Check PDF was created
        if not pdf_path.exists():
            raise PDFCompileError("PDF file was not created", errors=["Unknown compilation error"])

        # Parse warnings from log
        warnings = _parse_latex_warnings(log_path)

        logger.info(f"[{session_id}] PDF compiled: {pdf_path}")
        return str(pdf_path), warnings

    except PDFCompileError:
        raise
    except Exception as e:
        raise PDFCompileError(f"Compilation failed: {e}", errors=[str(e)])
    finally:
        # Clean up aux files (keep .tex and .pdf)
        for ext in [".aux", ".out", ".log"]:
            aux_file = tex_path.with_suffix(ext)
            if aux_file.exists():
                try:
                    aux_file.unlink()
                except OSError:
                    pass


def _parse_latex_errors(log_path: Path) -> list[str]:
    """Extract error messages from pdflatex log file."""
    errors = []
    if not log_path.exists():
        return ["Log file not found"]
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            if line.startswith("!"):
                errors.append(line.strip())
    except Exception:
        errors.append("Could not parse log file")
    return errors or ["Unknown LaTeX error"]


def _parse_latex_warnings(log_path: Path) -> list[str]:
    """Extract warning messages from pdflatex log file."""
    warnings = []
    if not log_path.exists():
        return []
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            if "Warning" in line or "Overfull" in line or "Underfull" in line:
                warnings.append(line.strip())
    except Exception:
        pass
    return warnings[:20]
