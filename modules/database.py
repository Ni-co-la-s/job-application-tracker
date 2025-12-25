"""Database module for job application tracker."""

import logging
import sqlite3
from typing import Any

from constants import JOBS_DB

logger = logging.getLogger(__name__)


class JobDatabase:
    """Database handler for job applications."""

    def __init__(self, db_path: str = JOBS_DB) -> None:
        """Initialize database connection and create tables.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_url TEXT UNIQUE NOT NULL,
                site TEXT,
                job_url_direct TEXT,
                title TEXT,
                company TEXT,
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

                -- scoring / pipeline
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

        # Applications table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            application_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            resume_version TEXT,
            resume_file_path TEXT,
            cover_letter_path TEXT,
            notes TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
        """)

        # Interview stages table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS interview_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            stage_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
        """)

        # Status options:
        # - no_response
        # - automatic_rejection
        # - phone_screen
        # - technical_interview
        # - behavioral_interview
        # - final_interview
        # - offer_received
        # - offer_accepted
        # - offer_declined
        # - rejected

        self.conn.commit()

        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_hash 
            ON jobs(job_hash) 
            WHERE job_hash IS NOT NULL
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_company_hash 
            ON jobs(company, job_hash) 
            WHERE job_hash IS NOT NULL
        """)

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_date_hash 
        ON jobs(date_scraped, job_hash) 
        WHERE job_hash IS NOT NULL
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_archived 
            ON jobs(archived)
        """)

        self.conn.commit()

    def insert_job(self, job_data: dict[str, Any]) -> int:
        """Insert or update a job.

        Args:
            job_data: Dictionary containing job data.

        Returns:
            Job ID (existing or new).
        """
        cursor = self.conn.cursor()

        # Check if job exists
        cursor.execute("SELECT id FROM jobs WHERE job_url = ?", (job_data["job_url"],))
        existing = cursor.fetchone()

        if existing:
            # Update existing
            job_id = existing[0]
            # Build update query dynamically based on provided fields
            update_fields = []
            update_values = []

            # Fields that can be updated (excluding id and job_url)
            updateable_fields = [
                "site",
                "job_url_direct",
                "title",
                "company",
                "location",
                "date_posted",
                "job_type",
                "salary_source",
                "interval",
                "min_amount",
                "max_amount",
                "currency",
                "is_remote",
                "job_level",
                "job_function",
                "description",
                "company_industry",
                "company_url",
                "company_logo",
                "company_url_direct",
                "company_addresses",
                "company_num_employees",
                "company_revenue",
                "company_description",
                "llm_score",
                "llm_reasoning",
                "job_hash",
                "extracted_skills",
                "matched_skills",
                "partial_skills",
                "missing_skills",
                "heuristic_score",
            ]

            for field in updateable_fields:
                if field in job_data:
                    update_fields.append(f"{field} = ?")
                    update_values.append(job_data.get(field))

            # Add job_id as the last parameter
            update_values.append(job_id)

            if update_fields:
                cursor.execute(
                    f"""
                    UPDATE jobs SET
                    {", ".join(update_fields)}
                    WHERE id = ?
                """,
                    update_values,
                )
        else:
            # Insert new
            fields = list(job_data.keys())
            placeholders = ",".join(["?" for _ in fields])
            cursor.execute(
                f"""
                INSERT INTO jobs ({",".join(fields)})
                VALUES ({placeholders})
            """,
                list(job_data.values()),
            )
            job_id = cursor.lastrowid

        self.conn.commit()
        return job_id

    def mark_applied(
        self,
        job_id: int,
        resume_version: str,
        resume_path: str,
        cover_letter_path: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Mark a job as applied.

        Args:
            job_id: ID of the job to mark as applied.
            resume_version: Version identifier of the resume used.
            resume_path: Path to the resume file.
            cover_letter_path: Optional path to cover letter file.
            notes: Optional application notes.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO applications (job_id, resume_version, resume_file_path, cover_letter_path, notes)
            VALUES (?, ?, ?, ?, ?)
        """,
            (job_id, resume_version, resume_path, cover_letter_path, notes),
        )
        self.conn.commit()

    def add_interview_stage(
        self, job_id: int, stage: str, notes: str | None = None
    ) -> None:
        """Add an interview stage for a job.

        Args:
            job_id: ID of the job.
            stage: Interview stage (e.g., 'phone_screen', 'technical_interview').
            notes: Optional notes about the interview stage.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO interview_stages (job_id, stage, notes)
            VALUES (?, ?, ?)
        """,
            (job_id, stage, notes),
        )
        self.conn.commit()

    def get_all_jobs(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get jobs with optional filters and pagination.

        Args:
            filters: Dictionary of filter criteria.
            limit: Maximum number of jobs to return.
            offset: Number of jobs to skip.

        Returns:
            Tuple of (list of job dictionaries, total count).
        """
        # Base query for jobs
        query = """
            SELECT j.*, 
                a.application_date,
                a.resume_version,
                a.resume_file_path,
                GROUP_CONCAT(i.stage || ' (' || i.stage_date || ')') as stages
            FROM jobs j
            LEFT JOIN applications a ON j.id = a.job_id
            LEFT JOIN interview_stages i ON j.id = i.job_id
            WHERE 1=1
        """
        params: list[Any] = []

        if filters:
            # Score filters
            if filters.get("min_score") is not None:
                query += " AND j.llm_score >= ?"
                params.append(filters["min_score"])
            if filters.get("max_score") is not None:
                query += " AND j.llm_score <= ?"
                params.append(filters["max_score"])

            # Site filter
            if filters.get("sites"):
                placeholders = ",".join(["?" for _ in filters["sites"]])
                query += f" AND j.site IN ({placeholders})"
                params.extend(filters["sites"])

            # Text filters
            if filters.get("company"):
                query += " AND j.company LIKE ?"
                params.append(f"%{filters['company']}%")
            if filters.get("location"):
                query += " AND j.location LIKE ?"
                params.append(f"%{filters['location']}%")

            # Application status
            if filters.get("applied"):
                query += " AND a.id IS NOT NULL"
            if filters.get("not_applied"):
                query += " AND a.id IS NULL"

            # Date filters
            if filters.get("date_from"):
                query += " AND j.date_scraped >= ?"
                params.append(filters["date_from"])
            if filters.get("date_to"):
                query += " AND j.date_scraped <= ?"
                params.append(filters["date_to"] + " 23:59:59")

            if filters.get("show_archived") == "active":
                query += " AND j.archived = 0"
            elif filters.get("show_archived") == "archived":
                query += " AND j.archived = 1"

        query += " GROUP BY j.id ORDER BY j.date_scraped DESC, j.llm_score DESC"

        # Add pagination if specified
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
            if offset is not None:
                query += " OFFSET ?"
                params.append(offset)

        cursor = self.conn.cursor()
        cursor.execute(query, params)

        columns = [desc[0] for desc in cursor.description]
        jobs = [dict(zip(columns, row)) for row in cursor.fetchall()]

        # Get total count for pagination
        count_query = """
            SELECT COUNT(DISTINCT j.id)
            FROM jobs j
            LEFT JOIN applications a ON j.id = a.job_id
            LEFT JOIN interview_stages i ON j.id = i.job_id
            WHERE 1=1
        """
        count_params: list[Any] = []

        if filters:
            # Score filters
            if filters.get("min_score") is not None:
                count_query += " AND j.llm_score >= ?"
                count_params.append(filters["min_score"])
            if filters.get("max_score") is not None:
                count_query += " AND j.llm_score <= ?"
                count_params.append(filters["max_score"])

            # Site filter
            if filters.get("sites"):
                placeholders = ",".join(["?" for _ in filters["sites"]])
                count_query += f" AND j.site IN ({placeholders})"
                count_params.extend(filters["sites"])

            # Text filters
            if filters.get("company"):
                count_query += " AND j.company LIKE ?"
                count_params.append(f"%{filters['company']}%")
            if filters.get("location"):
                count_query += " AND j.location LIKE ?"
                count_params.append(f"%{filters['location']}%")

            # Application status
            if filters.get("applied"):
                count_query += " AND a.id IS NOT NULL"
            if filters.get("not_applied"):
                count_query += " AND a.id IS NULL"

            # Date filters
            if filters.get("date_from"):
                count_query += " AND j.date_scraped >= ?"
                count_params.append(filters["date_from"])
            if filters.get("date_to"):
                count_query += " AND j.date_scraped <= ?"
                count_params.append(filters["date_to"] + " 23:59:59")

            # Archive filter
            if filters.get("show_archived") == "active":
                count_query += " AND j.archived = 0"
            elif filters.get("show_archived") == "archived":
                count_query += " AND j.archived = 1"

        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()[0]

        return jobs, total_count

    def archive_job(self, job_id: int) -> None:
        """Archive a job.

        Args:
            job_id: ID of the job to archive.
        """
        cursor = self.conn.cursor()
        cursor.execute("UPDATE jobs SET archived = 1 WHERE id = ?", (job_id,))
        self.conn.commit()

    def unarchive_job(self, job_id: int) -> None:
        """Unarchive a job.

        Args:
            job_id: ID of the job to unarchive.
        """
        cursor = self.conn.cursor()
        cursor.execute("UPDATE jobs SET archived = 0 WHERE id = ?", (job_id,))
        self.conn.commit()

    def get_read_only_conn(self) -> sqlite3.Connection:
        """Get a read-only SQLite connection.

        Returns:
            Read-only SQLite connection.
        """
        # URI=True allows the ?mode=ro parameter
        return sqlite3.connect(
            f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False
        )
