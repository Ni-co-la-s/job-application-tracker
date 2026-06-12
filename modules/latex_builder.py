"""LaTeX PDF build utilities for resume tailoring."""

import shutil
import subprocess
import tempfile
from pathlib import Path


class LatexBuildError(Exception):
    """Raised when LaTeX compilation fails."""


def build_pdf(
    tex_source: str,
    template_dir: Path | None = None,
    engine: str = "auto",
    timeout: int = 120,
) -> bytes:
    """Compile LaTeX source to PDF bytes in an isolated temporary directory.

    The full template folder is copied into the temp directory first, then
    ``resume.tex`` is overwritten with ``tex_source``. This preserves local
    assets such as .cls/.sty files, fonts, images, and subfolders while keeping
    generated artifacts out of the source template directory.
    """
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        if template_dir and template_dir.is_dir():
            shutil.copytree(template_dir, work, dirs_exist_ok=True)

        (work / "resume.tex").write_text(tex_source, encoding="utf-8")
        cmd = _resolve_engine(engine)

        try:
            proc = subprocess.run(
                cmd,
                cwd=work,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise LatexBuildError(f"Build tool not found on PATH: {cmd[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LatexBuildError("Compilation timed out.") from exc

        pdf = work / "resume.pdf"
        if proc.returncode != 0 or not pdf.exists():
            log = work / "resume.log"
            text = (
                log.read_text(errors="ignore")
                if log.exists()
                else (proc.stdout + proc.stderr)
            )
            errs = "\n".join(line for line in text.splitlines() if line.startswith("!"))
            raise LatexBuildError(errs or "Unknown LaTeX error; see full log.")

        return pdf.read_bytes()


def _resolve_engine(engine: str) -> list[str]:
    """Resolve the requested LaTeX engine to a subprocess command."""
    if engine in ("auto", "tectonic") and shutil.which("tectonic"):
        return ["tectonic", "resume.tex"]

    if shutil.which("latexmk"):
        flag = {"xe": "-pdfxe", "lua": "-pdflua"}.get(engine, "-pdf")
        return ["latexmk", flag, "-interaction=nonstopmode", "resume.tex"]

    raise LatexBuildError(
        "No LaTeX engine found. Install Tectonic or a TeX distribution."
    )
