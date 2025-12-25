"""Job Browser tab for viewing and managing job applications."""

import logging
from pathlib import Path
from typing import Any

import streamlit as st

import constants
from modules.database import JobDatabase

logger = logging.getLogger(__name__)


def get_resume_version_pdf() -> list[str]:
    """Get list of resume PDF files from RESUME_FINAL_DIR folder.

    Returns:
        List of PDF filenames sorted alphabetically.
    """
    resume_folder = Path(constants.RESUME_FINAL_DIR)
    if not resume_folder.exists():
        resume_folder.mkdir(parents=True)
        return []

    resume_files = list(resume_folder.glob("*.*"))
    # Only show PDF files
    valid_extensions = {".pdf"}
    resume_files = [f for f in resume_files if f.suffix.lower() in valid_extensions]

    return sorted([f.name for f in resume_files])


def render_job_browser(
    db: JobDatabase, jobs: list[dict[str, Any]], total_count: int
) -> None:
    """Render the job browser tab.

    Args:
        db: Database instance.
        jobs: List of job dictionaries.
        total_count: Total number of jobs matching filters.
    """

    st.title("🎯 Job Application Tracker")

    # Pagination controls
    st.subheader("📄 Pagination")
    total_pages = max(
        1, (total_count + st.session_state.page_size - 1) // st.session_state.page_size
    )

    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 2])

    with col1:
        if st.button("⏮️ First", disabled=st.session_state.current_page == 1):
            st.session_state.current_page = 1
            st.rerun()

    with col2:
        if st.button("◀️ Previous", disabled=st.session_state.current_page == 1):
            st.session_state.current_page -= 1
            st.rerun()

    with col3:
        st.markdown(f"**Page {st.session_state.current_page} of {total_pages}**")

    with col4:
        if st.button("Next ▶️", disabled=st.session_state.current_page == total_pages):
            st.session_state.current_page += 1
            st.rerun()

    with col5:
        if st.button("Last ⏭️", disabled=st.session_state.current_page == total_pages):
            st.session_state.current_page = total_pages
            st.rerun()

    # Show job range
    start_idx = (st.session_state.current_page - 1) * st.session_state.page_size + 1
    end_idx = min(start_idx + len(jobs) - 1, total_count)
    st.caption(f"Showing jobs {start_idx}-{end_idx} of {total_count} total jobs")

    # Bulk selection and deletion/archiving
    if jobs:
        st.subheader("🗂️ Bulk Selection & Actions")

        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

        with col1:
            if st.button("✅ Select All Filtered", width="stretch"):
                st.session_state.selected_jobs = {j["id"] for j in jobs}
                st.rerun()

        with col2:
            if st.button("❌ Deselect All", width="stretch"):
                st.session_state.selected_jobs = set()
                st.session_state.confirm_delete = False
                st.rerun()

        with col3:
            selected_count = len(st.session_state.selected_jobs)
            st.metric("Selected", selected_count)

        with col4:
            if selected_count > 0:
                col_archive, col_delete = st.columns(2)

                with col_archive:
                    if st.button(
                        f"📦 Archive {selected_count}",
                        width="stretch",
                        key="bulk_archive",
                    ):
                        try:
                            cursor = db.conn.cursor()
                            job_ids = list(st.session_state.selected_jobs)
                            placeholders = ",".join(["?" for _ in job_ids])
                            cursor.execute(
                                f"UPDATE jobs SET archived = 1 WHERE id IN ({placeholders})",
                                job_ids,
                            )
                            db.conn.commit()
                            st.toast(f"✓ Archived {selected_count} job(s)")
                            st.session_state.selected_jobs = set()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error archiving jobs: {e}")

                with col_delete:
                    # Show delete button
                    if not st.session_state.confirm_delete:
                        if st.button(
                            f"🗑️ Delete {selected_count}",
                            type="primary",
                            width="stretch",
                            key="show_confirm",
                        ):
                            st.session_state.confirm_delete = True
                            st.rerun()

        # Show confirmation dialog if triggered
        if st.session_state.confirm_delete and selected_count > 0:
            st.warning(
                f"⚠️ **WARNING:** About to delete {selected_count} jobs. This cannot be undone!"
            )

            col_a, col_b, col_c = st.columns([1, 1, 2])

            with col_a:
                if st.button("✓ YES, DELETE", type="primary", key="do_delete"):
                    try:
                        cursor = db.conn.cursor()
                        job_ids = list(st.session_state.selected_jobs)

                        # Delete related records first (applications and interview stages)
                        placeholders = ",".join(["?" for _ in job_ids])

                        cursor.execute(
                            f"DELETE FROM applications WHERE job_id IN ({placeholders})",
                            job_ids,
                        )
                        deleted_apps = cursor.rowcount

                        cursor.execute(
                            f"DELETE FROM interview_stages WHERE job_id IN ({placeholders})",
                            job_ids,
                        )
                        deleted_stages = cursor.rowcount

                        cursor.execute(
                            f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids
                        )
                        deleted_jobs = cursor.rowcount

                        db.conn.commit()

                        st.toast(
                            f"✓ Deleted {deleted_jobs} jobs, {deleted_apps} applications, {deleted_stages} interview stages"
                        )

                        # Reset state
                        st.session_state.selected_jobs = set()
                        st.session_state.confirm_delete = False
                        st.rerun()

                    except Exception as e:
                        st.error(f"Error deleting jobs: {e}")

            with col_b:
                if st.button("✗ CANCEL", key="cancel_delete"):
                    st.session_state.confirm_delete = False
                    st.toast("Deletion cancelled")
                    st.rerun()

        # Jobs table
        st.subheader("📋 Jobs")

        st.info(
            "💡 Tip: Use filters above to narrow down jobs, then click 'Select All Filtered'. Click checkbox buttons to toggle individual selections."
        )

        for idx, job in enumerate(jobs):
            is_selected = job["id"] in st.session_state.selected_jobs

            # Use button-style selection
            selection_emoji = "☑️" if is_selected else "⭐"
            score_display = job["llm_score"] or 0

            # Site emoji
            site_emoji = {
                "indeed": "📄",
                "linkedin": "💼",
                "glassdoor": "🏢",
                "zip_recruiter": "📨",
                "google": "🔍",
            }.get(job.get("site", "").lower(), "🌐")

            # Create clickable header for selection
            col_select, col_content = st.columns([0.05, 0.95])

            with col_select:
                # Clickable button to toggle selection
                button_label = "☑️" if is_selected else "☐"
                if st.button(
                    button_label,
                    key=f"toggle_{job['id']}",
                    help="Click to select/deselect",
                ):
                    if is_selected:
                        st.session_state.selected_jobs.discard(job["id"])
                    else:
                        st.session_state.selected_jobs.add(job["id"])
                    # Reset confirmation state when changing selection
                    st.session_state.confirm_delete = False
                    st.rerun()

            with col_content:
                # Show selection status in expander title
                # Add application indicator and site to title
                applied_indicator = "✅ APPLIED" if job.get("application_date") else ""
                expander_title = f"{selection_emoji} {score_display}/10 {site_emoji} - {job['title']} @ {job['company']} - {job['location']} {applied_indicator}"

                with st.expander(expander_title, expanded=False):
                    col1, col2, col3 = st.columns([2, 1, 0.3])

                    with col1:
                        st.write(f"**ID:** {job['id']}")
                        st.write(
                            f"**Site:** {site_emoji} {job.get('site', 'Unknown').title()}"
                        )
                        st.write(f"**Posted:** {job['date_posted'] or 'Unknown'}")
                        st.write(
                            f"**Scraped:** {job['date_scraped'][:10] if job['date_scraped'] else 'Unknown'}"
                        )
                        st.write(f"**Type:** {job['job_type'] or 'N/A'}")

                        # URLs
                        if job["job_url"]:
                            st.write(f"**URL:** [{job['job_url']}]({job['job_url']})")
                        if job["job_url_direct"]:
                            st.write(
                                f"**Direct:** [{job['job_url_direct']}]({job['job_url_direct']})"
                            )

                        # Salary info if available
                        if job.get("min_amount") or job.get("max_amount"):
                            salary_text = ""
                            if job.get("min_amount") and job.get("max_amount"):
                                salary_text = f"{job['min_amount']:,.0f} - {job['max_amount']:,.0f}"
                            elif job.get("min_amount"):
                                salary_text = f"From {job['min_amount']:,.0f}"
                            elif job.get("max_amount"):
                                salary_text = f"Up to {job['max_amount']:,.0f}"

                            if salary_text:
                                st.write(
                                    f"**Salary:** {salary_text} {job.get('currency') or ''} ({job.get('interval') or 'N/A'})"
                                )

                        st.write("**LLM Reasoning:**")
                        st.write(job["llm_reasoning"] or "N/A")

                        # Show warning if description is missing
                        if (
                            not job.get("description")
                            or len(job.get("description", "")) < 50
                        ):
                            st.warning("⚠️ Description missing or incomplete")

                        with st.expander("📄 Full Description"):
                            st.markdown(
                                job["description"] or "No description available"
                            )

                        # Company info if available
                        if job.get("company_description"):
                            with st.expander("🏢 Company Info"):
                                if job.get("company_logo"):
                                    st.image(job["company_logo"], width=100)
                                st.write(job["company_description"])
                                if job.get("company_revenue"):
                                    st.write(f"**Revenue:** {job['company_revenue']}")
                                if job.get("company_num_employees"):
                                    st.write(
                                        f"**Employees:** {job['company_num_employees']}"
                                    )

                    with col2:
                        st.write("### Application")

                        if job.get("application_date"):
                            st.success(f"✅ Applied on {job['application_date'][:10]}")
                            st.write(f"**Resume:** {job.get('resume_version')}")
                            if job.get("resume_file_path"):
                                resume_path = Path(job["resume_file_path"])
                                if resume_path.exists():
                                    st.write(f"**File:** ✓ {resume_path.name}")
                                else:
                                    st.write(
                                        f"**File:** ⚠️ {resume_path.name} (not found)"
                                    )

                            # Interview stages
                            if job.get("stages"):
                                st.write("**Stages:**")
                                stages_list = job["stages"].split(",")
                                for stage in stages_list:
                                    st.write(f"• {stage}")

                            # Add new stage
                            with st.form(f"stage_{job['id']}"):
                                st.write("**Add Interview Stage**")
                                new_stage = st.selectbox(
                                    "Stage",
                                    [
                                        "",
                                        "no_response",
                                        "automatic_rejection",
                                        "phone_screen",
                                        "technical_interview",
                                        "behavioral_interview",
                                        "final_interview",
                                        "offer_received",
                                        "offer_accepted",
                                        "offer_declined",
                                        "rejected",
                                    ],
                                    format_func=lambda x: {
                                        "": "Select stage...",
                                        "no_response": "📭 No Response",
                                        "automatic_rejection": "❌ Automatic Rejection",
                                        "phone_screen": "📞 Phone Screen",
                                        "technical_interview": "💻 Technical Interview",
                                        "behavioral_interview": "🤝 Behavioral Interview",
                                        "final_interview": "🎯 Final Interview",
                                        "offer_received": "🎉 Offer Received",
                                        "offer_accepted": "✅ Offer Accepted",
                                        "offer_declined": "❌ Offer Declined",
                                        "rejected": "😞 Rejected After Interview",
                                    }.get(x, x),
                                    key=f"stage_select_{job['id']}",
                                )
                                stage_notes = st.text_area(
                                    "Notes", key=f"stage_notes_{job['id']}"
                                )
                                if st.form_submit_button("Add Stage"):
                                    if new_stage:
                                        db.add_interview_stage(
                                            job["id"], new_stage, stage_notes
                                        )
                                        st.toast("Stage added!")
                                        st.rerun()
                        else:
                            # Mark as applied - with resume file picker
                            with st.form(f"apply_{job['id']}"):
                                st.write("**Mark as Applied**")

                                # Get available resumes from folder
                                available_resumes = get_resume_version_pdf()

                                if available_resumes:
                                    selected_resume = st.selectbox(
                                        "Select Resume",
                                        options=available_resumes,
                                        key=f"resume_select_{job['id']}",
                                    )

                                    # Show full path - use RESUME_FINAL_DIR
                                    resume_full_path = str(
                                        Path(constants.RESUME_FINAL_DIR)
                                        / selected_resume
                                    )
                                    st.caption(f"📁 Full path: `{resume_full_path}`")

                                    # Extract version from filename (without extension)
                                    resume_version = Path(selected_resume).stem

                                else:
                                    st.warning("⚠️ No resumes found in 'Resumes' folder")
                                    st.info(
                                        "Please add resume files to the 'Resumes' folder"
                                    )
                                    selected_resume = None
                                    resume_version = "unknown"
                                    resume_full_path = ""

                                # Optional: Cover letter
                                cover_letter_path = st.text_input(
                                    "Cover Letter (optional)", key=f"cover_{job['id']}"
                                )

                                # Notes
                                notes = st.text_area(
                                    "Application Notes", key=f"notes_{job['id']}"
                                )

                                # Submit button
                                submit_disabled = not available_resumes
                                if st.form_submit_button(
                                    "Mark Applied", disabled=submit_disabled
                                ):
                                    if selected_resume:
                                        db.mark_applied(
                                            job["id"],
                                            resume_version,
                                            resume_full_path,
                                            cover_letter_path,
                                            notes,
                                        )
                                        st.toast("Marked as applied!")
                                        st.rerun()

                    with col3:
                        st.write("")
                        st.write("")
                        if st.button(
                            "📦", key=f"archive_{job['id']}", help="Archive this job"
                        ):
                            db.archive_job(job["id"])
                            st.session_state.selected_jobs.discard(job["id"])
                            st.toast("Archived!")
                            st.rerun()

                        if st.button(
                            "🗑️", key=f"del_{job['id']}", help="Delete this job"
                        ):
                            cursor = db.conn.cursor()
                            # Delete related records first
                            cursor.execute(
                                "DELETE FROM applications WHERE job_id = ?",
                                (job["id"],),
                            )
                            cursor.execute(
                                "DELETE FROM interview_stages WHERE job_id = ?",
                                (job["id"],),
                            )
                            cursor.execute(
                                "DELETE FROM jobs WHERE id = ?", (job["id"],)
                            )
                            db.conn.commit()
                            st.session_state.selected_jobs.discard(job["id"])
                            st.toast("Deleted!")
                            st.rerun()

    else:
        st.info("No jobs found with current filters")
