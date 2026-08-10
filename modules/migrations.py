"""Versioned SQLite schema migrations."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    """A single, ordered database schema migration."""

    version: int
    name: str
    upgrade: Callable[[sqlite3.Connection], None]


class MigrationRequiredError(RuntimeError):
    """Raised when an existing database requires user-approved migrations."""

    def __init__(self, current_version: int, migrations: list[Migration]) -> None:
        self.current_version = current_version
        self.migrations = migrations
        target_version = migrations[-1].version
        super().__init__(
            f"Database migration required (version {current_version} -> "
            f"{target_version})"
        )


class UnsupportedDatabaseVersionError(RuntimeError):
    """Raised when a database was created by a newer application version."""


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    cursor = connection.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_columns(
    connection: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    existing_columns = _table_columns(connection, table)
    for column, definition in columns.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_applications_to_resume_registry(
    connection: sqlite3.Connection,
) -> None:
    """Replace legacy application resume text/path columns with ``resume_id``."""
    columns = _table_columns(connection, "applications")
    legacy_columns = {"resume_version", "resume_file_path"}
    if not legacy_columns.issubset(columns):
        return

    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE applications_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            application_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            resume_id INTEGER,
            cover_letter_path TEXT,
            notes TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id),
            FOREIGN KEY (resume_id) REFERENCES resumes(id)
        )
    """)
    cursor.execute("""
        SELECT id, job_id, application_date, resume_version,
               resume_file_path, cover_letter_path, notes
        FROM applications
        ORDER BY application_date ASC, id ASC
    """)
    legacy_rows = cursor.fetchall()
    resume_ids: dict[str, int] = {}

    for row in legacy_rows:
        (
            application_id,
            job_id,
            application_date,
            resume_version,
            resume_file_path,
            cover_letter_path,
            notes,
        ) = row
        resume_name = (resume_version or "").strip()
        resume_id = None
        if resume_name:
            resume_id = resume_ids.get(resume_name)
            if resume_id is None:
                existing = cursor.execute(
                    "SELECT id, path FROM resumes WHERE name = ?",
                    (resume_name,),
                ).fetchone()
                if existing:
                    if (existing[1] or "") != (resume_file_path or ""):
                        raise sqlite3.IntegrityError(
                            f"Legacy resume name {resume_name!r} maps to multiple paths"
                        )
                    resume_id = existing[0]
                else:
                    suffix = str(resume_file_path or "").lower()
                    kind = "tex" if suffix.endswith(".tex") else "pdf"
                    cursor.execute(
                        """
                        INSERT INTO resumes (name, path, kind, created_at)
                        VALUES (?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                        """,
                        (
                            resume_name,
                            resume_file_path or "",
                            kind,
                            application_date,
                        ),
                    )
                    resume_id = cursor.lastrowid
                resume_ids[resume_name] = resume_id

        cursor.execute(
            """
            INSERT INTO applications_new
                (id, job_id, application_date, resume_id,
                 cover_letter_path, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                job_id,
                application_date,
                resume_id,
                cover_letter_path,
                notes,
            ),
        )

    migrated_count = cursor.execute("SELECT COUNT(*) FROM applications_new").fetchone()[
        0
    ]
    if migrated_count != len(legacy_rows):
        raise sqlite3.IntegrityError("Application migration row count mismatch")

    cursor.execute("DROP TABLE applications")
    cursor.execute("ALTER TABLE applications_new RENAME TO applications")
    violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise sqlite3.IntegrityError(
            f"Foreign key violations after application migration: {violations}"
        )
    logger.info(
        "Migrated %d applications and registered %d legacy resumes",
        len(legacy_rows),
        len(resume_ids),
    )


def _migration_001_current_schema(connection: sqlite3.Connection) -> None:
    """Create or upgrade the schema used before version tracking was added."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT UNIQUE NOT NULL,
            site TEXT,
            job_url_direct TEXT,
            title TEXT,
            company TEXT,
            company_linkedin_id INTEGER,
            location TEXT,
            date_posted DATE,
            date_scraped DATETIME DEFAULT CURRENT_TIMESTAMP,
            job_type TEXT,
            salary_source TEXT,
            interval TEXT,
            min_amount REAL,
            max_amount REAL,
            currency TEXT,
            is_remote BOOLEAN,
            job_level TEXT,
            job_function TEXT,
            description TEXT,
            company_industry TEXT,
            company_url TEXT,
            company_logo TEXT,
            company_url_direct TEXT,
            company_addresses TEXT,
            company_num_employees TEXT,
            company_revenue TEXT,
            company_description TEXT,
            llm_score INTEGER,
            llm_reasoning TEXT,
            heuristic_score REAL,
            job_hash TEXT,
            extracted_skills TEXT,
            matched_skills TEXT,
            partial_skills TEXT,
            missing_skills TEXT,
            archived BOOLEAN DEFAULT 0
        )
    """)
    _ensure_columns(
        connection,
        "jobs",
        {
            "site": "TEXT",
            "job_url_direct": "TEXT",
            "title": "TEXT",
            "company": "TEXT",
            "company_linkedin_id": "INTEGER",
            "location": "TEXT",
            "date_posted": "DATE",
            "date_scraped": "DATETIME",
            "job_type": "TEXT",
            "salary_source": "TEXT",
            "interval": "TEXT",
            "min_amount": "REAL",
            "max_amount": "REAL",
            "currency": "TEXT",
            "is_remote": "BOOLEAN",
            "job_level": "TEXT",
            "job_function": "TEXT",
            "description": "TEXT",
            "company_industry": "TEXT",
            "company_url": "TEXT",
            "company_logo": "TEXT",
            "company_url_direct": "TEXT",
            "company_addresses": "TEXT",
            "company_num_employees": "TEXT",
            "company_revenue": "TEXT",
            "company_description": "TEXT",
            "llm_score": "INTEGER",
            "llm_reasoning": "TEXT",
            "heuristic_score": "REAL",
            "job_hash": "TEXT",
            "extracted_skills": "TEXT",
            "matched_skills": "TEXT",
            "partial_skills": "TEXT",
            "missing_skills": "TEXT",
            "archived": "BOOLEAN DEFAULT 0",
        },
    )

    connection.execute("""
        CREATE TABLE IF NOT EXISTS interview_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            stage_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS resume_tailoring_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            base_template TEXT NOT NULL,
            output_path TEXT,
            edits_json TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)
    _ensure_columns(
        connection,
        "resume_tailoring_runs",
        {"model_base_url": "TEXT", "model_name": "TEXT"},
    )
    connection.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('tex', 'pdf')),
            source_tailoring_run_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            archived BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY (source_tailoring_run_id)
                REFERENCES resume_tailoring_runs(id) ON DELETE SET NULL
        )
    """)

    _migrate_applications_to_resume_registry(connection)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            application_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            resume_id INTEGER,
            cover_letter_path TEXT,
            notes TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id),
            FOREIGN KEY (resume_id) REFERENCES resumes(id)
        )
    """)

    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_job_hash ON jobs(job_hash) "
        "WHERE job_hash IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_company_hash ON jobs(company, job_hash) "
        "WHERE job_hash IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_date_hash ON jobs(date_scraped, job_hash) "
        "WHERE job_hash IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_archived ON jobs(archived)",
        "CREATE INDEX IF NOT EXISTS idx_resume_tailoring_runs_job_id "
        "ON resume_tailoring_runs(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_applications_resume_id "
        "ON applications(resume_id)",
        "CREATE INDEX IF NOT EXISTS idx_resumes_archived_kind_name "
        "ON resumes(archived, kind, name)",
        "CREATE INDEX IF NOT EXISTS idx_resumes_source_tailoring_run_id "
        "ON resumes(source_tailoring_run_id)",
    )
    for statement in indexes:
        connection.execute(statement)


MIGRATIONS = (
    Migration(
        1,
        "Create the current schema and migrate the resume registry",
        _migration_001_current_schema,
    ),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version


def get_schema_version(connection: sqlite3.Connection) -> int:
    """Return the database's recorded schema version."""
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def get_pending_migrations(connection: sqlite3.Connection) -> list[Migration]:
    """Return migrations newer than the database schema version."""
    current_version = get_schema_version(connection)
    if current_version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedDatabaseVersionError(
            f"Database schema version {current_version} is newer than this "
            f"application supports ({CURRENT_SCHEMA_VERSION})"
        )
    return [
        migration for migration in MIGRATIONS if migration.version > current_version
    ]


def has_existing_schema(connection: sqlite3.Connection) -> bool:
    """Return whether the database already contains application tables."""
    return (
        connection.execute(
            """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        LIMIT 1
        """
        ).fetchone()
        is not None
    )


def apply_pending_migrations(connection: sqlite3.Connection) -> list[Migration]:
    """Apply every pending migration, each in its own transaction."""
    applied: list[Migration] = []
    for migration in get_pending_migrations(connection):
        try:
            connection.execute("BEGIN IMMEDIATE")
            migration.upgrade(connection)
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        applied.append(migration)
        logger.info(
            "Applied database migration %d: %s", migration.version, migration.name
        )
    return applied


def create_migration_backup(
    database_path: str | Path,
    backup_directory: str | Path | None = None,
) -> Path:
    """Create and verify a consistent SQLite backup before migration."""
    source_path = Path(database_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {source_path}")

    destination_directory = (
        Path(backup_directory).resolve()
        if backup_directory is not None
        else source_path.parent / "backups"
    )
    destination_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    destination_path = destination_directory / (
        f"{source_path.stem}_before_migration_{timestamp}{source_path.suffix or '.db'}"
    )

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {result}")
    except Exception:
        destination.close()
        source.close()
        destination_path.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        source.close()

    return destination_path
