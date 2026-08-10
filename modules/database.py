"""Database module for job application tracker."""

import sqlite3
from typing import Any

from constants import JOBS_DB
from modules.migrations import (
    MigrationRequiredError,
    apply_pending_migrations,
    get_pending_migrations,
    get_schema_version,
    has_existing_schema,
)


class JobDatabase:
    """Database handler for job applications."""

    def __init__(
        self,
        db_path: str = JOBS_DB,
        *,
        allow_migrations: bool = False,
    ) -> None:
        """Initialize the connection and ensure the schema is current.

        Args:
            db_path: Path to SQLite database file.
            allow_migrations: Apply pending migrations to an existing database.
                Empty databases are initialized without approval because they
                contain no user data to back up.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            pending = get_pending_migrations(self.conn)
            if pending and has_existing_schema(self.conn) and not allow_migrations:
                raise MigrationRequiredError(
                    current_version=get_schema_version(self.conn),
                    migrations=pending,
                )
            apply_pending_migrations(self.conn)
        except Exception:
            self.conn.close()
            raise

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
                "company_linkedin_id",
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
        resume_id: int,
        cover_letter_path: str | None = None,
        notes: str | None = None,
        application_date: str | None = None,
    ) -> None:
        """Mark a job as applied.

        Args:
            job_id: ID of the job to mark as applied.
            resume_id: Registry ID of the resume used.
            cover_letter_path: Optional path to cover letter file.
            notes: Optional application notes.
            application_date: Optional application date (YYYY-MM-DD format).
                             If None, uses current timestamp.
        """
        cursor = self.conn.cursor()

        if application_date:
            cursor.execute(
                """
                INSERT INTO applications (job_id, resume_id,
                                          cover_letter_path, notes, application_date)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    job_id,
                    resume_id,
                    cover_letter_path,
                    notes,
                    application_date,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO applications (job_id, resume_id,
                                          cover_letter_path, notes)
                VALUES (?, ?, ?, ?)
            """,
                (job_id, resume_id, cover_letter_path, notes),
            )
        self.conn.commit()

    def add_interview_stage(
        self,
        job_id: int,
        stage: str,
        notes: str | None = None,
        stage_date: str | None = None,
    ) -> None:
        """Add an interview stage for a job.

        Args:
            job_id: ID of the job.
            stage: Interview stage (e.g., 'phone_screen', 'technical_interview').
            notes: Optional notes about the interview stage.
            stage_date: Optional stage date (YYYY-MM-DD format).
                       If None, uses current timestamp.
        """
        cursor = self.conn.cursor()

        if stage_date:
            cursor.execute(
                """
                INSERT INTO interview_stages (job_id, stage, notes, stage_date)
                VALUES (?, ?, ?, ?)
            """,
                (job_id, stage, notes, stage_date),
            )
        else:
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
        sort_by: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get jobs with optional filters and pagination.

        Args:
            filters: Dictionary of filter criteria.
            limit: Maximum number of jobs to return.
            offset: Number of jobs to skip.
            sort_by: Sorting option (e.g., "date_desc", "date_asc", "score_desc", "score_asc").

        Returns:
            Tuple of (list of job dictionaries, total count).
        """
        # Base query for jobs
        query = """
            SELECT j.*, 
                a.application_date,
                a.resume_id,
                r.name AS resume_name,
                r.path AS resume_path,
                r.name AS resume_version,
                r.path AS resume_file_path,
                GROUP_CONCAT(i.stage || ' (' || i.stage_date || ')') as stages
            FROM jobs j
            LEFT JOIN applications a ON j.id = a.job_id
            LEFT JOIN resumes r ON a.resume_id = r.id
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
            if filters.get("title_text"):
                query += " AND j.title LIKE ?"
                params.append(f"%{filters['title_text']}%")
            if filters.get("description_text"):
                query += " AND j.description LIKE ?"
                params.append(f"%{filters['description_text']}%")

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

        query += " GROUP BY j.id"

        if sort_by == "date_desc":
            query += " ORDER BY j.date_scraped DESC"
        elif sort_by == "date_asc":
            query += " ORDER BY j.date_scraped ASC"
        elif sort_by == "score_desc":
            query += " ORDER BY j.llm_score DESC"
        elif sort_by == "score_asc":
            query += " ORDER BY j.llm_score ASC"
        else:
            query += " ORDER BY j.date_scraped DESC, j.llm_score DESC"

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
            if filters.get("title_text"):
                count_query += " AND j.title LIKE ?"
                count_params.append(f"%{filters['title_text']}%")
            if filters.get("description_text"):
                count_query += " AND j.description LIKE ?"
                count_params.append(f"%{filters['description_text']}%")

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

    def get_job_by_id(self, job_id: int) -> dict[str, Any] | None:
        """Get a single job by ID.

        Args:
            job_id: ID of the job to fetch.

        Returns:
            Job dictionary or None if not found.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

    def get_application_by_job_id(self, job_id: int) -> dict[str, Any] | None:
        """Get application data for a job.

        Args:
            job_id: ID of the job.

        Returns:
            Application dictionary or None if not found.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT a.*, r.name AS resume_name, r.path AS resume_path,
                   r.kind AS resume_kind, r.archived AS resume_archived
            FROM applications a
            LEFT JOIN resumes r ON r.id = a.resume_id
            WHERE a.job_id = ?
            """,
            (job_id,),
        )
        row = cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

    def save_resume_tailoring_run(
        self,
        job_id: int,
        base_template: str,
        output_path: str,
        edits_json: str,
        model_base_url: str | None = None,
        model_name: str | None = None,
        *,
        commit: bool = True,
    ) -> int:
        """Insert one saved resume tailoring run record.

        Args:
            job_id: ID of the job being tailored for.
            base_template: Name of the LaTeX template folder.
            output_path: Saved PDF path.
            edits_json: JSON snapshot of final applied edits.

        Returns:
            New saved tailoring run ID.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO resume_tailoring_runs
                (job_id, base_template, output_path, edits_json,
                 model_base_url, model_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                base_template,
                output_path,
                edits_json,
                model_base_url,
                model_name,
            ),
        )
        if commit:
            self.conn.commit()
        return cursor.lastrowid

    def get_resume_tailoring_runs_for_job(self, job_id: int) -> list[dict[str, Any]]:
        """Get tailoring runs for a job, newest first."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM resume_tailoring_runs
            WHERE job_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (job_id,),
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_resume_tailoring_run(self, run_id: int) -> dict[str, Any] | None:
        """Get a single resume tailoring run by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM resume_tailoring_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

    def create_resume(
        self,
        name: str,
        path: str,
        kind: str,
        source_tailoring_run_id: int | None = None,
        *,
        commit: bool = True,
    ) -> int:
        """Register one managed resume and return its ID."""
        if kind not in {"tex", "pdf"}:
            raise ValueError("Resume kind must be 'tex' or 'pdf'")
        cursor = self.conn.execute(
            """
            INSERT INTO resumes (name, path, kind, source_tailoring_run_id)
            VALUES (?, ?, ?, ?)
            """,
            (name.strip(), path, kind, source_tailoring_run_id),
        )
        if commit:
            self.conn.commit()
        return cursor.lastrowid

    def get_resume(self, resume_id: int) -> dict[str, Any] | None:
        """Return one resume with tailoring/job provenance."""
        cursor = self.conn.execute(
            """
            SELECT r.*, tr.job_id AS tailored_job_id,
                   tr.model_name, tr.model_base_url,
                   j.title AS tailored_job_title, j.company AS tailored_job_company
            FROM resumes r
            LEFT JOIN resume_tailoring_runs tr
                ON tr.id = r.source_tailoring_run_id
            LEFT JOIN jobs j ON j.id = tr.job_id
            WHERE r.id = ?
            """,
            (resume_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(zip((item[0] for item in cursor.description), row))

    def list_resumes(
        self,
        archive_status: str = "active",
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """List registry resumes alphabetically with optional filters."""
        query = """
            SELECT r.*, tr.job_id AS tailored_job_id,
                   tr.model_name, tr.model_base_url,
                   j.title AS tailored_job_title, j.company AS tailored_job_company,
                   (SELECT COUNT(*) FROM applications a WHERE a.resume_id = r.id)
                       AS application_count
            FROM resumes r
            LEFT JOIN resume_tailoring_runs tr
                ON tr.id = r.source_tailoring_run_id
            LEFT JOIN jobs j ON j.id = tr.job_id
            WHERE 1=1
        """
        params: list[Any] = []
        if archive_status == "active":
            query += " AND r.archived = 0"
        elif archive_status == "archived":
            query += " AND r.archived = 1"
        if kind:
            query += " AND r.kind = ?"
            params.append(kind)
        query += " ORDER BY lower(r.name), r.id"
        cursor = self.conn.execute(query, params)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_application_resume_options(self, job_id: int) -> list[dict[str, Any]]:
        """Return active PDFs, prioritizing resumes tailored for ``job_id``."""
        cursor = self.conn.execute(
            """
            SELECT r.*, tr.job_id AS tailored_job_id,
                   CASE WHEN tr.job_id = ? THEN 1 ELSE 0 END AS matches_job
            FROM resumes r
            LEFT JOIN resume_tailoring_runs tr
                ON tr.id = r.source_tailoring_run_id
            WHERE r.archived = 0 AND r.kind = 'pdf'
            ORDER BY CASE WHEN tr.job_id = ? THEN 0 ELSE 1 END,
                     lower(r.name), r.id
            """,
            (job_id, job_id),
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def set_resume_archived(self, resume_id: int, archived: bool) -> None:
        """Archive or unarchive a resume."""
        self.conn.execute(
            "UPDATE resumes SET archived = ? WHERE id = ?",
            (int(archived), resume_id),
        )
        self.conn.commit()

    def count_resume_applications(self, resume_id: int) -> int:
        """Return how many applications reference a resume."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE resume_id = ?", (resume_id,)
        ).fetchone()[0]

    def delete_resume_record(self, resume_id: int, *, commit: bool = True) -> None:
        """Delete an unused resume record, refusing referenced resumes."""
        usage_count = self.count_resume_applications(resume_id)
        if usage_count:
            raise ValueError(
                f"Resume is used by {usage_count} application(s) and cannot be deleted"
            )
        self.conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
        if commit:
            self.conn.commit()

    def get_resume_counts(self) -> dict[str, int]:
        """Return compact registry counts for the dashboard sidebar."""
        row = self.conn.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN archived = 0 AND kind = 'pdf' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN archived = 0 AND kind = 'tex' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN archived = 1 THEN 1 ELSE 0 END)
            FROM resumes
            """
        ).fetchone()
        return {
            "total": row[0] or 0,
            "active_pdf": row[1] or 0,
            "active_tex": row[2] or 0,
            "archived": row[3] or 0,
        }

    def get_interview_stages_by_job_id(self, job_id: int) -> list[dict[str, Any]]:
        """Get all interview stages for a job.

        Args:
            job_id: ID of the job.

        Returns:
            List of interview stage dictionaries.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM interview_stages WHERE job_id = ? ORDER BY stage_date",
            (job_id,),
        )

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def update_job(self, job_id: int, updates: dict[str, Any]) -> None:
        """Update editable job fields.

        Args:
            job_id: ID of the job to update.
            updates: Dictionary of field names and values to update.
        """
        if not updates:
            return

        # Only allow updating editable fields
        editable_fields = {
            "title",
            "company",
            "location",
            "job_type",
            "description",
            "min_amount",
            "max_amount",
            "currency",
            "interval",
            "job_url",
            "job_url_direct",
            "site",
            "date_posted",
            "salary_source",
            "company_industry",
            "company_url",
            "company_logo",
            "company_url_direct",
            "company_addresses",
            "company_num_employees",
            "company_revenue",
            "company_description",
            "job_level",
            "job_function",
            "is_remote",
        }

        # Filter to only editable fields
        filtered_updates = {k: v for k, v in updates.items() if k in editable_fields}

        if not filtered_updates:
            return

        # Build update query
        set_clause = ", ".join([f"{field} = ?" for field in filtered_updates.keys()])
        values = list(filtered_updates.values()) + [job_id]

        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
        self.conn.commit()

    def update_application(self, job_id: int, updates: dict[str, Any]) -> None:
        """Update application fields.

        Args:
            job_id: ID of the job.
            updates: Dictionary of field names and values to update.
        """
        if not updates:
            return

        cursor = self.conn.cursor()

        # Check if application exists
        cursor.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,))
        existing = cursor.fetchone()

        if existing:
            # Update existing application
            editable_fields = {
                "application_date",
                "resume_id",
                "cover_letter_path",
                "notes",
            }
            filtered_updates = {
                k: v for k, v in updates.items() if k in editable_fields
            }

            if filtered_updates:
                set_clause = ", ".join(
                    [f"{field} = ?" for field in filtered_updates.keys()]
                )
                values = list(filtered_updates.values()) + [job_id]
                cursor.execute(
                    f"UPDATE applications SET {set_clause} WHERE job_id = ?", values
                )
                self.conn.commit()
        else:
            # Create new application if it doesn't exist
            fields = ["job_id"] + list(updates.keys())
            placeholders = ", ".join(["?" for _ in fields])
            values = [job_id] + list(updates.values())

            cursor.execute(
                f"INSERT INTO applications ({', '.join(fields)}) VALUES ({placeholders})",
                values,
            )
            self.conn.commit()

    def update_interview_stage(self, stage_id: int, updates: dict[str, Any]) -> None:
        """Update an interview stage.

        Args:
            stage_id: ID of the stage to update.
            updates: Dictionary of field names and values to update.
        """
        if not updates:
            return

        editable_fields = {"stage", "stage_date", "notes"}
        filtered_updates = {k: v for k, v in updates.items() if k in editable_fields}

        if not filtered_updates:
            return

        set_clause = ", ".join([f"{field} = ?" for field in filtered_updates.keys()])
        values = list(filtered_updates.values()) + [stage_id]

        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE interview_stages SET {set_clause} WHERE id = ?", values)
        self.conn.commit()

    def delete_interview_stage(self, stage_id: int) -> None:
        """Delete an interview stage.

        Args:
            stage_id: ID of the stage to delete.
        """
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM interview_stages WHERE id = ?", (stage_id,))
        self.conn.commit()
