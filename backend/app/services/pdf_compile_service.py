"""
PDF compile service — compiles LaTeX source to PDF.

For MVP, this uses a subprocess call to pdflatex.
Production upgrade: use a Docker-based LaTeX compiler or an API service.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
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


_BANNED_LATEX_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (r"\\input\b", re.compile(r"\\input\b", re.IGNORECASE)),
    (r"\\include\b", re.compile(r"\\include\b", re.IGNORECASE)),
    (r"\\openin\b", re.compile(r"\\openin\b", re.IGNORECASE)),
    (r"\\openout\b", re.compile(r"\\openout\b", re.IGNORECASE)),
    (r"\\read\b", re.compile(r"\\read\b", re.IGNORECASE)),
    (r"\\write18\b", re.compile(r"\\write18\b", re.IGNORECASE)),
    (r"\\write\b", re.compile(r"\\write\b", re.IGNORECASE)),
    (r"\\immediate\b", re.compile(r"\\immediate\b", re.IGNORECASE)),
    (r"\\usepackage\s*\{\s*shellesc\s*\}", re.compile(r"\\usepackage\s*\{\s*shellesc\s*\}", re.IGNORECASE)),
    (r"\\catcode\b", re.compile(r"\\catcode\b", re.IGNORECASE)),
    (r"\\newread\b", re.compile(r"\\newread\b", re.IGNORECASE)),
    (r"\\newwrite\b", re.compile(r"\\newwrite\b", re.IGNORECASE)),
]


def _assert_safe_latex(latex_source: str) -> None:
    """Reject LaTeX that attempts file access, shell escape, or primitive I/O."""
    matches = [
        pattern_text
        for pattern_text, pattern in _BANNED_LATEX_PATTERNS
        if pattern.search(latex_source)
    ]
    if matches:
        raise PDFCompileError(
            "Unsafe LaTeX detected",
            errors=[f"Banned LaTeX pattern detected: {pattern}" for pattern in matches],
        )


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
    _assert_safe_latex(latex_source)

    settings = get_settings()
    output_dir = Path(settings.LATEX_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("pdflatex"):
        raise PDFCompileError(
            "Local pdflatex is not installed. Install TeX Live / pdflatex on the server.",
            errors=["Local pdflatex is not installed. Install TeX Live / pdflatex on the server."],
        )

    pdf_filename = f"resume_{session_id}_{uuid.uuid4().hex[:6]}.pdf"
    final_pdf_path = output_dir / pdf_filename

    try:
        with tempfile.TemporaryDirectory(prefix=f"resume_{session_id}_") as tmpdir:
            tmpdir_path = Path(tmpdir)
            tex_path = tmpdir_path / "main.tex"
            pdf_path = tmpdir_path / "main.pdf"
            log_path = tmpdir_path / "main.log"

            tex_path.write_text(latex_source, encoding="utf-8")

            logger.info(f"[{session_id}] Using local pdflatex for compilation.")
            for pass_num in range(2):
                process = await asyncio.create_subprocess_exec(
                    "pdflatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-no-shell-escape",
                    f"-output-directory={tmpdir_path}",
                    "main.tex",
                    cwd=str(tmpdir_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    errors = _parse_latex_errors(log_path)
                    if not errors or errors == ["Log file not found"]:
                        out_text = stdout.decode(errors="replace")
                        err_text = stderr.decode(errors="replace")
                        errors = [line for line in (out_text + err_text).splitlines() if line.startswith("!")]

                    raise PDFCompileError(
                        f"pdflatex exited with code {process.returncode}",
                        errors=errors or ["Unknown LaTeX compilation error"],
                    )

            if not pdf_path.exists():
                raise PDFCompileError("PDF file was not created", errors=["Unknown compilation error"])

            warnings = _parse_latex_warnings(log_path) if log_path.exists() else []
            shutil.copy2(pdf_path, final_pdf_path)

        logger.info(f"[{session_id}] PDF compilation completed: {final_pdf_path}")
        return str(final_pdf_path), warnings

    except PDFCompileError:
        raise
    except Exception as e:
        logger.exception("Unexpected error during PDF compilation")
        raise PDFCompileError(f"Compilation failed: {e}", errors=[str(e)])


def _parse_latex_errors(log_path: Path) -> list[str]:
    """Extract error messages from pdflatex log file."""
    errors = []
    if not log_path.exists():
        return ["Log file not found"]
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("!"):
                # Include the next line if it looks like context
                err_msg = line.strip()
                if i + 1 < len(lines) and lines[i+1].startswith("l."):
                    err_msg += f" (at {lines[i+1].strip()})"
                errors.append(err_msg)
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
