"""Managed resume file ingestion and deletion services."""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import constants
from modules.database import JobDatabase
from modules.latex_builder import build_pdf


class ResumeRegistryError(Exception):
    """Raised when a resume cannot be safely ingested or deleted."""


def normalize_resume_name(value: str) -> str:
    """Return a filesystem-safe, non-empty registry name."""
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", value.strip())
    name = re.sub(r"\s+", " ", name).strip(" ._-")
    if not name:
        raise ResumeRegistryError("Enter a valid resume name.")
    return name


def import_pdf(db: JobDatabase, name: str, data: bytes) -> int:
    """Copy a PDF upload into the managed final directory and register it."""
    clean_name = normalize_resume_name(name)
    destination = Path(constants.RESUME_FINAL_DIR) / f"{clean_name}.pdf"
    _assert_available(db, clean_name, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    try:
        return db.create_resume(clean_name, str(destination), "pdf")
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def import_standalone_tex(
    db: JobDatabase, name: str, data: bytes, timeout: int = 120
) -> int:
    """Validate and ingest one standalone resume.tex project."""
    clean_name = normalize_resume_name(name)
    destination = Path(constants.RESUME_TEX_DIR) / clean_name
    _assert_available(db, clean_name, destination)
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir) / "project"
        project_root.mkdir()
        tex_path = project_root / "resume.tex"
        tex_path.write_bytes(data)
        _validate_tex_project(project_root, tex_path, timeout)
        return _move_project_and_register(db, clean_name, project_root, destination)


def import_tex_zip(db: JobDatabase, name: str, data: bytes, timeout: int = 120) -> int:
    """Safely extract, validate, and ingest a zipped LaTeX project."""
    clean_name = normalize_resume_name(name)
    destination = Path(constants.RESUME_TEX_DIR) / clean_name
    _assert_available(db, clean_name, destination)
    with tempfile.TemporaryDirectory() as temp_dir:
        extraction_root = Path(temp_dir) / "extracted"
        extraction_root.mkdir()
        archive_path = Path(temp_dir) / "upload.zip"
        archive_path.write_bytes(data)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract(archive, extraction_root)
        except zipfile.BadZipFile as exc:
            raise ResumeRegistryError(
                "The uploaded file is not a valid ZIP archive."
            ) from exc

        matches = [
            path for path in extraction_root.rglob("resume.tex") if path.is_file()
        ]
        if not matches:
            raise ResumeRegistryError("No resume.tex found in the uploaded archive.")
        if len(matches) > 1:
            raise ResumeRegistryError(
                "Multiple resume.tex files were found; upload one unambiguous project."
            )
        tex_path = matches[0]
        project_root = tex_path.parent
        _validate_tex_project(project_root, tex_path, timeout)
        return _move_project_and_register(db, clean_name, project_root, destination)


def delete_managed_resume(db: JobDatabase, resume_id: int) -> None:
    """Delete an unused resume record and its managed file or project folder."""
    resume = db.get_resume(resume_id)
    if not resume:
        raise ResumeRegistryError("Resume not found.")
    usage_count = db.count_resume_applications(resume_id)
    if usage_count:
        raise ResumeRegistryError(
            f"This resume is used by {usage_count} application(s) and cannot be deleted."
        )

    path = Path(resume["path"])
    db.delete_resume_record(resume_id)
    try:
        if resume["kind"] == "tex":
            project_dir = path if path.is_dir() else path.parent
            if project_dir.exists():
                shutil.rmtree(project_dir)
        elif path.exists():
            path.unlink()
    except OSError as exc:
        raise ResumeRegistryError(
            f"The registry entry was deleted, but the managed file could not be removed: {exc}"
        ) from exc


def _assert_available(db: JobDatabase, name: str, destination: Path) -> None:
    if db.conn.execute("SELECT 1 FROM resumes WHERE name = ?", (name,)).fetchone():
        raise ResumeRegistryError(f"A resume named {name!r} already exists.")
    if destination.exists():
        raise ResumeRegistryError(f"Managed destination already exists: {destination}")


def _validate_tex_project(project_root: Path, tex_path: Path, timeout: int) -> None:
    try:
        source = tex_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ResumeRegistryError("resume.tex must be UTF-8 encoded.") from exc
    build_pdf(source, template_dir=project_root, engine="auto", timeout=timeout)


def _move_project_and_register(
    db: JobDatabase, name: str, project_root: Path, destination: Path
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(project_root, destination)
    tex_path = destination / "resume.tex"
    try:
        return db.create_resume(name, str(tex_path), "tex")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    """Extract regular ZIP members while rejecting traversal and symlinks."""
    for info in archive.infolist():
        member = PurePosixPath(info.filename.replace("\\", "/"))
        if member.is_absolute() or ".." in member.parts:
            raise ResumeRegistryError(f"Unsafe ZIP path: {info.filename}")
        if member.parts and ":" in member.parts[0]:
            raise ResumeRegistryError(f"Unsafe ZIP path: {info.filename}")
        mode = info.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            raise ResumeRegistryError(
                "Symbolic links are not allowed in resume archives."
            )
        target = destination.joinpath(*member.parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
