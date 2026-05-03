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

    def __init__(
        self,
        message: str,
        errors: list[str],
        generated_tex_path: str | None = None,
        warnings: list[str] | None = None,
        pdflatex_excerpt: str | None = None,
        line_number: int | None = None,
        raw_output: str | None = None,
    ):
        super().__init__(message)
        self.errors = errors
        self.generated_tex_path = generated_tex_path
        self.warnings = warnings or []
        self.pdflatex_excerpt = pdflatex_excerpt
        self.line_number = line_number
        self.raw_output = raw_output

    def response_errors(self) -> list[str]:
        if not self.errors:
            return ["PDF compilation failed. You can open the LaTeX editor, fix the source, and try again."]
        return self.errors


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
            errors=["The LaTeX source contains a command that is not allowed for safe PDF compilation."],
            raw_output="; ".join(f"Banned LaTeX pattern detected: {pattern}" for pattern in matches),
        )


def _assert_no_empty_itemize(latex_source: str) -> None:
    """Reject empty itemize environments before pdflatex can fail with missing item."""
    compact_source = re.sub(r"(?m)^\s*%.*$", "", latex_source)
    if "\\begin{document}" in compact_source:
        compact_source = compact_source.split("\\begin{document}", 1)[1]
    if re.search(r"\\resumeItemListStart\s*\\resumeItemListEnd", compact_source, re.DOTALL):
        raise PDFCompileError(
            "Invalid LaTeX detected",
            errors=["Empty resume item list detected before PDF compilation."],
        )

    empty_itemize = re.search(
        r"\\begin\{itemize\}(?:\[[^\]]*\])?(?P<body>.*?)\\end\{itemize\}",
        compact_source,
        re.DOTALL,
    )
    while empty_itemize:
        body = empty_itemize.group("body")
        if not re.search(r"\\item\b|\\resumeSubheading\b|\\resumeProjectHeading\b", body):
            raise PDFCompileError(
                "Invalid LaTeX detected",
                errors=["Empty itemize environment detected before PDF compilation."],
            )
        empty_itemize = re.search(
            r"\\begin\{itemize\}(?:\[[^\]]*\])?(?P<body>.*?)\\end\{itemize\}",
            compact_source[empty_itemize.end():],
            re.DOTALL,
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
    cleanup_old_output_files(max_age_hours=24, keep_current_session_id=session_id)

    settings = get_settings()
    output_dir = Path(settings.LATEX_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    tex_filename = f"resume_{session_id}_{uuid.uuid4().hex[:6]}.tex"
    generated_tex_path = output_dir / tex_filename

    _assert_safe_latex(latex_source)
    _assert_no_empty_itemize(latex_source)

    generated_tex_path.write_text(latex_source, encoding="utf-8")

    if not shutil.which("pdflatex"):
        raise PDFCompileError(
            "Local pdflatex is not installed. Install TeX Live / pdflatex on the server.",
            errors=["Local pdflatex is not installed. Install TeX Live / pdflatex on the server."],
            generated_tex_path=str(generated_tex_path),
        )

    pdf_filename = f"resume_{session_id}_{uuid.uuid4().hex[:6]}.pdf"
    final_pdf_path = output_dir / pdf_filename

    try:
        with tempfile.TemporaryDirectory(prefix=f"resume_{session_id}_") as tmpdir:
            tmpdir_path = Path(tmpdir)
            tex_path = tmpdir_path / "main.tex"
            pdf_path = tmpdir_path / "main.pdf"
            log_path = tmpdir_path / "main.log"

            shutil.copy2(generated_tex_path, tex_path)

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
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
                except asyncio.TimeoutError as exc:
                    process.kill()
                    await process.communicate()
                    raise PDFCompileError(
                        "pdflatex timed out",
                        errors=["PDF compilation timed out after 45 seconds."],
                        generated_tex_path=str(generated_tex_path),
                    ) from exc

                if process.returncode != 0:
                    out_text = stdout.decode(errors="replace")
                    err_text = stderr.decode(errors="replace")
                    raw_output = _read_compile_output(log_path, out_text, err_text)
                    errors = _parse_latex_errors(raw_output)
                    line_number = _parse_latex_line_number(raw_output)
                    excerpt = _latex_excerpt(raw_output, line_number)
                    warnings = _parse_latex_warnings_from_text(raw_output)
                    logger.error(
                        "[%s] pdflatex failed with code %s. tex=%s line=%s errors=%s output=%s",
                        session_id,
                        process.returncode,
                        generated_tex_path,
                        line_number,
                        errors,
                        raw_output[-4000:],
                    )

                    raise PDFCompileError(
                        f"pdflatex exited with code {process.returncode}",
                        errors=_friendly_latex_errors(errors, line_number),
                        generated_tex_path=str(generated_tex_path),
                        warnings=warnings,
                        pdflatex_excerpt=excerpt,
                        line_number=line_number,
                        raw_output=raw_output,
                    )

            if not pdf_path.exists():
                raise PDFCompileError(
                    "PDF file was not created",
                    errors=["Unknown compilation error"],
                    generated_tex_path=str(generated_tex_path),
                )

            warnings = _parse_latex_warnings(log_path) if log_path.exists() else []
            shutil.copy2(pdf_path, final_pdf_path)

        logger.info(f"[{session_id}] PDF compilation completed: {final_pdf_path}")
        return str(final_pdf_path), warnings

    except PDFCompileError:
        raise
    except Exception as e:
        logger.exception("Unexpected error during PDF compilation")
        raise PDFCompileError(
            f"Compilation failed: {e}",
            errors=[str(e)],
            generated_tex_path=str(generated_tex_path),
        )


def _read_compile_output(log_path: Path, stdout: str, stderr: str) -> str:
    parts: list[str] = []
    if log_path.exists():
        try:
            parts.append(log_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            parts.append("Could not parse log file")
    parts.extend([stdout, stderr])
    return "\n".join(part for part in parts if part)


def _parse_latex_errors(content: str) -> list[str]:
    """Extract error messages from pdflatex output/log content."""
    errors = []
    try:
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("!"):
                err_msg = line.strip()
                if i + 1 < len(lines) and lines[i+1].startswith("l."):
                    err_msg += f" (at {lines[i+1].strip()})"
                errors.append(err_msg)
    except Exception:
        errors.append("Could not parse log file")
    return errors or ["Unknown LaTeX error"]


def _friendly_latex_errors(errors: list[str], line_number: int | None) -> list[str]:
    friendly: list[str] = []
    for error in errors:
        lower = error.lower()
        if "missing item" in lower:
            friendly.append("A bullet list is malformed. Try regenerating or editing the LaTeX around the listed line.")
        elif "undefined control sequence" in lower:
            friendly.append("The LaTeX source contains an unsupported command or unescaped special text.")
        elif "runaway argument" in lower or "paragraph ended before" in lower:
            friendly.append("The LaTeX source has mismatched braces or a malformed field.")
        elif "emergency stop" in lower:
            friendly.append("pdflatex stopped early because the LaTeX source is invalid.")
        elif error and error != "Unknown LaTeX error":
            friendly.append(error)
    if not friendly:
        friendly.append("PDF compilation failed. Open the LaTeX editor, review the source, and try compiling again.")
    if line_number:
        friendly[0] = f"{friendly[0]} Approximate line: {line_number}."
    return _dedupe(friendly)[:5]


def _parse_latex_line_number(content: str) -> int | None:
    matches = re.findall(r"(?m)^l\.(\d+)\s", content)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def _latex_excerpt(content: str, line_number: int | None) -> str | None:
    lines = content.splitlines()
    if not lines:
        return None
    if line_number:
        for index, line in enumerate(lines):
            if line.startswith(f"l.{line_number} "):
                start = max(0, index - 3)
                end = min(len(lines), index + 4)
                return "\n".join(lines[start:end])[:1200]
    bang_index = next((index for index, line in enumerate(lines) if line.startswith("!")), None)
    if bang_index is None:
        return "\n".join(lines[-12:])[:1200]
    start = max(0, bang_index - 2)
    end = min(len(lines), bang_index + 6)
    return "\n".join(lines[start:end])[:1200]


def _parse_latex_warnings(log_path: Path) -> list[str]:
    """Extract warning messages from pdflatex log file."""
    warnings = []
    if not log_path.exists():
        return []
    try:
        warnings = _parse_latex_warnings_from_text(log_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return warnings[:20]


def _parse_latex_warnings_from_text(content: str) -> list[str]:
    warnings = []
    for line in content.splitlines():
        if "Warning" in line or "Overfull" in line or "Underfull" in line:
            warnings.append(line.strip())
    return warnings[:20]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def cleanup_old_output_files(max_age_hours: int = 24, keep_current_session_id: str | None = None) -> int:
    """
    Clean up old LaTeX and PDF files from the output directory.

    Args:
        max_age_hours: Maximum age of files to keep (default: 24 hours)
        keep_current_session_id: Session ID to always keep (prevents deletion before download)

    Returns:
        Number of files deleted
    """
    import time

    settings = get_settings()
    output_dir = Path(settings.LATEX_OUTPUT_DIR)

    if not output_dir.exists():
        return 0

    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted_count = 0
    extensions_to_clean = {'.tex', '.pdf', '.aux', '.log', '.out', '.gz'}

    try:
        for file_path in output_dir.iterdir():
            if not file_path.is_file():
                continue

            if file_path.suffix not in extensions_to_clean:
                continue

            file_age = current_time - file_path.stat().st_mtime
            if file_age < max_age_seconds:
                continue

            is_current_session = False
            if keep_current_session_id:
                if keep_current_session_id in file_path.name:
                    is_current_session = True

            if is_current_session:
                continue

            try:
                file_path.unlink()
                deleted_count += 1
                logger.info(f"Cleaned up old output file: {file_path.name}")
            except OSError as e:
                logger.warning(f"Failed to delete old output file {file_path.name}: {e}")

    except Exception as e:
        logger.error(f"Error during output cleanup: {e}")

    return deleted_count
