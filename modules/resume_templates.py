"""Helpers for discovering and reading LaTeX resume templates."""

import re
from pathlib import Path

import constants


def list_latex_templates() -> list[str]:
    """Return template names under Resumes/tex/<name>/ with a resume.tex file."""
    tex_root = Path(constants.RESUME_TEX_DIR)
    if not tex_root.exists():
        tex_root.mkdir(parents=True, exist_ok=True)
        return []

    templates = [
        path.name
        for path in tex_root.iterdir()
        if path.is_dir() and (path / "resume.tex").exists()
    ]
    return sorted(templates)


def get_template_dir(template_name: str) -> Path:
    """Return the template directory for a template name."""
    return Path(constants.RESUME_TEX_DIR) / template_name


def read_template_tex(template_name: str) -> str:
    """Read the full resume.tex source for a template."""
    tex_path = get_template_dir(template_name) / "resume.tex"
    return tex_path.read_text(encoding="utf-8")


def extract_document_body(tex_source: str) -> str:
    """Extract LaTeX body between begin/end document, falling back to whole file."""
    match = re.search(
        r"\\begin\{document\}(?P<body>.*?)\\end\{document\}",
        tex_source,
        flags=re.DOTALL,
    )
    if not match:
        return tex_source
    return match.group("body").strip()
