"""Job Edit Panel for editing job details, applications, and interview stages."""

import datetime
import logging
from typing import Any

import streamlit as st

from modules.database import JobDatabase
from modules.interview_stages_loader import (
    get_stage_options,
    format_stage_option,
)

logger = logging.getLogger(__name__)


def render_edit_panel(db: JobDatabase, job_id: int, jobs: list[dict[str, Any]]) -> None:
    """Render the edit panel for a job.

    Args:
        db: Database instance.
        job_id: ID of the job being edited.
        jobs: List of all jobs (for the condensed list).
    """
    # Load job data
    job = db.get_job_by_id(job_id)
    if not job:
        st.error("Job not found!")
        if st.button("❌ Close"):
            st.session_state.editing_job_id = None
            st.rerun()
        return

    application = db.get_application_by_job_id(job_id)
    stages = db.get_interview_stages_by_job_id(job_id)

    st.header(f"✏️ Editing: {job['title']} @ {job['company']}")

    # Create tabs for different sections
    tab1, tab2, tab3 = st.tabs(["Job Details", "Application", "Interview Stages"])

    # TAB 1: Job Details
    with tab1:
        st.subheader("Editable Fields")

        col1, col2 = st.columns(2)
        with col1:
            title = st.text_input(
                "Title", value=job.get("title") or "", key="edit_title"
            )
            company = st.text_input(
                "Company", value=job.get("company") or "", key="edit_company"
            )
            location = st.text_input(
                "Location", value=job.get("location") or "", key="edit_location"
            )
            job_type = st.text_input(
                "Job Type", value=job.get("job_type") or "", key="edit_job_type"
            )
            site = st.text_input("Site", value=job.get("site") or "", key="edit_site")
            job_url = st.text_input(
                "Job URL", value=job.get("job_url") or "", key="edit_job_url"
            )
            job_url_direct = st.text_input(
                "Job URL Direct",
                value=job.get("job_url_direct") or "",
                key="edit_job_url_direct",
            )

        with col2:
            job_level = st.text_input(
                "Job Level", value=job.get("job_level") or "", key="edit_job_level"
            )
            job_function = st.text_input(
                "Job Function",
                value=job.get("job_function") or "",
                key="edit_job_function",
            )

            date_posted_value = None
            if job.get("date_posted"):
                try:
                    date_posted_value = datetime.datetime.strptime(
                        job["date_posted"], "%Y-%m-%d"
                    ).date()
                except Exception as e:
                    logger.warning(f"Failed to parse date_posted: {e}")
            date_posted = st.date_input(
                "Date Posted", value=date_posted_value, key="edit_date_posted"
            )

            is_remote = st.checkbox(
                "Is Remote", value=bool(job.get("is_remote")), key="edit_is_remote"
            )

        # Salary information section
        st.subheader("Salary Information")
        col1, col2 = st.columns(2)
        with col1:
            min_amount = st.number_input(
                "Min Amount",
                value=float(job.get("min_amount") or 0),
                step=1000.0,
                min_value=0.0,
                key="edit_min_amount",
            )
            currency = st.text_input(
                "Currency", value=job.get("currency") or "", key="edit_currency"
            )
            salary_source = st.text_input(
                "Salary Source",
                value=job.get("salary_source") or "",
                key="edit_salary_source",
            )
        with col2:
            max_amount = st.number_input(
                "Max Amount",
                value=float(job.get("max_amount") or 0),
                step=1000.0,
                min_value=0.0,
                key="edit_max_amount",
            )
            interval = st.text_input(
                "Interval", value=job.get("interval") or "", key="edit_interval"
            )

        # Company fields
        st.subheader("Company Information")
        col1, col2 = st.columns(2)
        with col1:
            company_industry = st.text_input(
                "Company Industry",
                value=job.get("company_industry") or "",
                key="edit_company_industry",
            )
            company_url = st.text_input(
                "Company URL",
                value=job.get("company_url") or "",
                key="edit_company_url",
            )
            company_logo = st.text_input(
                "Company Logo",
                value=job.get("company_logo") or "",
                key="edit_company_logo",
            )
            company_url_direct = st.text_input(
                "Company URL Direct",
                value=job.get("company_url_direct") or "",
                key="edit_company_url_direct",
            )
        with col2:
            company_addresses = st.text_input(
                "Company Addresses",
                value=job.get("company_addresses") or "",
                key="edit_company_addresses",
            )
            company_num_employees = st.text_input(
                "Company Num Employees",
                value=job.get("company_num_employees") or "",
                key="edit_company_num_employees",
            )
            company_revenue = st.text_input(
                "Company Revenue",
                value=job.get("company_revenue") or "",
                key="edit_company_revenue",
            )

        # Text areas
        description = st.text_area(
            "Description",
            value=job.get("description") or "",
            height=300,
            key="edit_description",
        )
        company_description = st.text_area(
            "Company Description",
            value=job.get("company_description") or "",
            height=300,
            key="edit_company_description",
        )

        # Read-only fields
        st.subheader("Read-Only Fields (System Generated)")
        col1, col2 = st.columns(2)
        with col1:
            st.text(f"ID: {job['id']}")
            st.text(f"Date Scraped: {job.get('date_scraped', 'N/A')}")
            st.text(f"LLM Score: {job.get('llm_score', 'N/A')}")
            st.text(f"Heuristic Score: {job.get('heuristic_score', 'N/A')}")
        with col2:
            st.text(
                f"Job Hash: {job.get('job_hash', 'N/A')[:20] if job.get('job_hash') else 'N/A'}..."
            )
            st.text(f"Archived: {job.get('archived', 0)}")

        if job.get("llm_reasoning"):
            with st.expander("LLM Reasoning"):
                st.write(job["llm_reasoning"])

        if job.get("extracted_skills"):
            with st.expander("Extracted Skills"):
                st.write(job["extracted_skills"])

        if job.get("matched_skills"):
            with st.expander("Matched Skills"):
                st.write(job["matched_skills"])
        if job.get("partial_skills"):
            with st.expander("Partial Skills"):
                st.write(job["partial_skills"])

        if job.get("missing_skills"):
            with st.expander("Missing Skills"):
                st.write(job["missing_skills"])

    # TAB 2: Application
    with tab2:
        if application:
            st.subheader("Edit Application")

            # Date input
            app_date_value = None
            if application.get("application_date"):
                try:
                    app_date_value = datetime.datetime.strptime(
                        application["application_date"][:10], "%Y-%m-%d"
                    ).date()
                except Exception as e:
                    logger.warning(f"Failed to parse application_date: {e}")

            application_date = st.date_input(
                "Application Date", value=app_date_value, key="edit_app_date"
            )

            resume_version = st.text_input(
                "Resume Version",
                value=application.get("resume_version") or "",
                key="edit_resume_version",
            )
            resume_file_path = st.text_input(
                "Resume File Path",
                value=application.get("resume_file_path") or "",
                key="edit_resume_file_path",
            )
            cover_letter_path = st.text_input(
                "Cover Letter Path",
                value=application.get("cover_letter_path") or "",
                key="edit_cover_letter_path",
            )
            notes = st.text_area(
                "Notes", value=application.get("notes") or "", key="edit_app_notes"
            )
        else:
            st.info("No application data yet")

    # TAB 3: Interview Stages
    with tab3:
        st.subheader("Interview Stages")

        if stages:
            for idx, stage in enumerate(stages):
                with st.expander(
                    f"{format_stage_option(stage['stage'])} - {stage['stage_date'][:10] if stage['stage_date'] else 'N/A'}",
                    expanded=False,
                ):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        # Get stage options and find current index
                        stage_options = get_stage_options()
                        current_stage = stage["stage"]
                        try:
                            current_idx = stage_options.index(current_stage)
                        except ValueError:
                            current_idx = 0

                        new_stage = st.selectbox(
                            "Stage Type",
                            options=stage_options,
                            index=current_idx,
                            format_func=format_stage_option,
                            key=f"edit_stage_type_{stage['id']}",
                        )

                        # Date input
                        stage_date_value = None
                        if stage.get("stage_date"):
                            try:
                                stage_date_value = datetime.datetime.strptime(
                                    stage["stage_date"][:10], "%Y-%m-%d"
                                ).date()
                            except Exception as e:
                                logger.warning(f"Failed to parse stage_date: {e}")
                        new_stage_date = st.date_input(
                            "Stage Date",
                            value=stage_date_value,
                            key=f"edit_stage_date_{stage['id']}",
                        )

                        new_notes = st.text_area(
                            "Notes",
                            value=stage.get("notes") or "",
                            key=f"edit_stage_notes_{stage['id']}",
                        )

                        # Update button for this stage
                        if st.button(
                            "💾 Update Stage", key=f"update_stage_{stage['id']}"
                        ):
                            try:
                                updates = {
                                    "stage": new_stage,
                                    "stage_date": new_stage_date.strftime("%Y-%m-%d"),
                                    "notes": new_notes,
                                }
                                db.update_interview_stage(stage["id"], updates)
                                st.toast("✓ Stage updated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error updating stage: {e}")

                    with col2:
                        st.write("")
                        st.write("")
                        if st.button("🗑️ Delete", key=f"delete_stage_{stage['id']}"):
                            try:
                                db.delete_interview_stage(stage["id"])
                                st.toast("✓ Stage deleted!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error deleting stage: {e}")
        else:
            st.info("No interview stages yet")

        # Add new stage
        st.subheader("Add New Stage")
        with st.form(f"add_stage_{job_id}"):
            new_stage = st.selectbox(
                "Stage Type",
                options=get_stage_options(),
                format_func=format_stage_option,
                key="new_stage_type",
            )
            new_stage_date = st.date_input(
                "Stage Date", value=datetime.date.today(), key="new_stage_date"
            )
            new_stage_notes = st.text_area("Notes", key="new_stage_notes")

            if st.form_submit_button("➕ Add Stage"):
                try:
                    db.add_interview_stage(
                        job_id,
                        new_stage,
                        new_stage_notes,
                        new_stage_date.strftime("%Y-%m-%d"),
                    )
                    st.toast("✓ Stage added!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding stage: {e}")

    # Save and Cancel buttons
    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                # Collect all job updates
                job_updates = {
                    "title": title,
                    "company": company,
                    "location": location,
                    "job_type": job_type,
                    "site": site,
                    "job_url": job_url,
                    "job_url_direct": job_url_direct,
                    "salary_source": salary_source,
                    "currency": currency,
                    "interval": interval,
                    "min_amount": min_amount if min_amount > 0 else None,
                    "max_amount": max_amount if max_amount > 0 else None,
                    "job_level": job_level,
                    "job_function": job_function,
                    "date_posted": date_posted.strftime("%Y-%m-%d")
                    if date_posted
                    else None,
                    "is_remote": is_remote,
                    "description": description,
                    "company_industry": company_industry,
                    "company_url": company_url,
                    "company_logo": company_logo,
                    "company_url_direct": company_url_direct,
                    "company_addresses": company_addresses,
                    "company_num_employees": company_num_employees,
                    "company_revenue": company_revenue,
                    "company_description": company_description,
                }

                db.update_job(job_id, job_updates)

                # Update application if exists
                if application:
                    app_updates = {
                        "application_date": application_date.strftime("%Y-%m-%d")
                        if application_date
                        else None,
                        "resume_version": resume_version,
                        "resume_file_path": resume_file_path,
                        "cover_letter_path": cover_letter_path,
                        "notes": notes,
                    }
                    db.update_application(job_id, app_updates)

                st.toast("✓ Changes saved successfully!")
                st.session_state.editing_job_id = None
                st.rerun()

            except Exception as e:
                st.error(f"Error saving changes: {e}")

    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.editing_job_id = None
            st.rerun()
