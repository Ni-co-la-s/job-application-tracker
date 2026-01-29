"""Add Job Panel for manually adding jobs to the database."""

import datetime
import logging
import re

import streamlit as st

from modules.database import JobDatabase
from modules.langgraph_pipeline import process_single_job

logger = logging.getLogger(__name__)


def validate_url(url: str) -> bool:
    """Basic URL validation.

    Args:
        url: URL string to validate

    Returns:
        True if URL is reasonably formatted, False otherwise
    """
    if not url or not url.strip():
        return False

    # Basic URL pattern check
    url_pattern = re.compile(
        r"^(https?://)?"  # http:// or https://
        r"([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+"  # domain
        r"[a-zA-Z]{2,}"  # top level domain
        r"(/.*)?$",  # path
        re.IGNORECASE,
    )

    return bool(url_pattern.match(url.strip()))


def render_add_job_panel(db: JobDatabase) -> None:
    """Render the add job panel for manually creating jobs.

    Args:
        db: Database instance.
    """
    st.header("➕ Add Job Manually")

    # Create tabs for different sections
    tab1, tab2, tab3 = st.tabs(
        ["Job Details", "Company Information", "Salary Information"]
    )

    # Initialize form data in session state if not exists
    if "add_job_form_data" not in st.session_state:
        st.session_state.add_job_form_data = {}

    # TAB 1: Job Details
    with tab1:
        st.subheader("Job Details")
        st.markdown("Fields marked with * are required")

        # Basic job info
        col1, col2 = st.columns(2)
        with col1:
            job_url = st.text_input(
                "Job URL*",
                value=st.session_state.add_job_form_data.get("job_url", ""),
                placeholder="https://example.com/job/123",
                key="add_job_url",
            )
            title = st.text_input(
                "Title*",
                value=st.session_state.add_job_form_data.get("title", ""),
                placeholder="Senior Software Engineer",
                key="add_title",
            )
            company = st.text_input(
                "Company*",
                value=st.session_state.add_job_form_data.get("company", ""),
                placeholder="Example Corp",
                key="add_company",
            )
            location = st.text_input(
                "Location*",
                value=st.session_state.add_job_form_data.get("location", ""),
                placeholder="San Francisco, CA or Remote",
                key="add_location",
            )

            # Date input - default to today
            date_posted = st.date_input(
                "Date Posted*", value=datetime.date.today(), key="add_date_posted"
            )

            description = st.text_area(
                "Description*",
                value=st.session_state.add_job_form_data.get("description", ""),
                height=300,
                placeholder="Enter the full job description...",
                key="add_description",
            )

        with col2:
            site_options = [
                "indeed",
                "linkedin",
                "glassdoor",
                "zip_recruiter",
                "google",
                "other",
            ]
            site = st.selectbox(
                "Site",
                options=site_options,
                index=site_options.index(
                    st.session_state.add_job_form_data.get("site", "other")
                )
                if st.session_state.add_job_form_data.get("site") in site_options
                else site_options.index("other"),
                key="add_site",
            )
            job_url_direct = st.text_input(
                "Job URL Direct",
                value=st.session_state.add_job_form_data.get("job_url_direct", ""),
                placeholder="Direct application URL (optional)",
                key="add_job_url_direct",
            )
            job_type = st.text_input(
                "Job Type",
                value=st.session_state.add_job_form_data.get("job_type", ""),
                placeholder="e.g., Full-time, Contract",
                key="add_job_type",
            )
            job_level = st.text_input(
                "Job Level",
                value=st.session_state.add_job_form_data.get("job_level", ""),
                placeholder="e.g., Senior, Mid-level",
                key="add_job_level",
            )
            job_function = st.text_input(
                "Job Function",
                value=st.session_state.add_job_form_data.get("job_function", ""),
                placeholder="e.g., Engineering, Product",
                key="add_job_function",
            )
            is_remote = st.checkbox(
                "Is Remote",
                value=st.session_state.add_job_form_data.get("is_remote", False),
                key="add_is_remote",
            )

    # TAB 2: Company Information
    with tab2:
        st.subheader("Company Information")
        st.markdown("All fields in this tab are optional")

        col1, col2 = st.columns(2)
        with col1:
            company_industry = st.text_input(
                "Company Industry",
                value=st.session_state.add_job_form_data.get("company_industry", ""),
                placeholder="e.g., Technology, Healthcare",
                key="add_company_industry",
            )
            company_url = st.text_input(
                "Company URL",
                value=st.session_state.add_job_form_data.get("company_url", ""),
                placeholder="https://example.com",
                key="add_company_url",
            )
            company_logo = st.text_input(
                "Company Logo URL",
                value=st.session_state.add_job_form_data.get("company_logo", ""),
                placeholder="https://example.com/logo.png",
                key="add_company_logo",
            )
            company_url_direct = st.text_input(
                "Company URL Direct",
                value=st.session_state.add_job_form_data.get("company_url_direct", ""),
                placeholder="Direct company URL (optional)",
                key="add_company_url_direct",
            )

        with col2:
            company_addresses = st.text_input(
                "Company Addresses",
                value=st.session_state.add_job_form_data.get("company_addresses", ""),
                placeholder="123 Main St, San Francisco, CA",
                key="add_company_addresses",
            )
            company_num_employees = st.text_input(
                "Company Number of Employees",
                value=st.session_state.add_job_form_data.get(
                    "company_num_employees", ""
                ),
                placeholder="e.g., 1000-5000",
                key="add_company_num_employees",
            )
            company_revenue = st.text_input(
                "Company Revenue",
                value=st.session_state.add_job_form_data.get("company_revenue", ""),
                placeholder="e.g., $1B",
                key="add_company_revenue",
            )

        company_description = st.text_area(
            "Company Description",
            value=st.session_state.add_job_form_data.get("company_description", ""),
            height=200,
            placeholder="Enter company description...",
            key="add_company_description",
        )

    # TAB 3: Salary Information
    with tab3:
        st.subheader("Salary Information")
        st.markdown("All fields in this tab are optional")

        col1, col2 = st.columns(2)
        with col1:
            min_amount = st.number_input(
                "Minimum Amount",
                value=float(st.session_state.add_job_form_data.get("min_amount", 0)),
                step=1000.0,
                min_value=0.0,
                key="add_min_amount",
            )
            currency = st.text_input(
                "Currency",
                value=st.session_state.add_job_form_data.get("currency", ""),
                placeholder="e.g., USD, EUR",
                key="add_currency",
            )
            salary_source = st.text_input(
                "Salary Source",
                value=st.session_state.add_job_form_data.get("salary_source", ""),
                placeholder="e.g., Glassdoor, self-reported",
                key="add_salary_source",
            )

        with col2:
            max_amount = st.number_input(
                "Maximum Amount",
                value=float(st.session_state.add_job_form_data.get("max_amount", 0)),
                step=1000.0,
                min_value=0.0,
                key="add_max_amount",
            )
            interval = st.text_input(
                "Interval",
                value=st.session_state.add_job_form_data.get("interval", ""),
                placeholder="e.g., YEARLY, MONTHLY, HOURLY",
                key="add_interval",
            )

    # Action buttons
    st.divider()

    # Check for duplicate url
    cursor = db.conn.cursor()
    cursor.execute("SELECT id, title, company FROM jobs WHERE job_url = ?", (job_url,))
    existing_job = cursor.fetchone()

    if existing_job:
        job_id, existing_title, existing_company = existing_job
        st.error("❌ Job with this URL already exists:")
        st.info(f"**{existing_title}** at **{existing_company}** (ID: {job_id})")
        st.info(
            "💡 You can find this job in the Job Browser by searching for the company name or using filters."
        )

        if st.button("↩️ Back to Browser", use_container_width=True):
            st.session_state.adding_job = False
            st.session_state.add_job_form_data = {}
            st.rerun()
        st.stop()

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "💾 Add Job & Run Pipeline", type="primary", use_container_width=True
        ):
            # Validate required fields
            required_fields = {
                "Job URL": job_url,
                "Title": title,
                "Company": company,
                "Location": location,
                "Description": description,
            }

            missing_fields = [
                field
                for field, value in required_fields.items()
                if not value or not str(value).strip()
            ]

            if missing_fields:
                st.error(
                    f"❌ Please fill in all required fields: {', '.join(missing_fields)}"
                )
                st.stop()

            # Validate URL format
            if not validate_url(job_url):
                st.error(
                    "❌ Please enter a valid job URL (e.g., https://example.com/job/123)"
                )
                st.stop()

            # Prepare job data
            job_data = {
                "job_url": job_url.strip(),
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "date_posted": date_posted.strftime("%Y-%m-%d"),
                "description": description.strip(),
                "site": site.strip() if site.strip() else "manual",
                "job_url_direct": job_url_direct.strip()
                if job_url_direct.strip()
                else None,
                "job_type": job_type.strip() if job_type.strip() else None,
                "job_level": job_level.strip() if job_level.strip() else None,
                "job_function": job_function.strip() if job_function.strip() else None,
                "is_remote": 1 if is_remote else 0,
                "company_industry": company_industry.strip()
                if company_industry.strip()
                else None,
                "company_url": company_url.strip() if company_url.strip() else None,
                "company_logo": company_logo.strip() if company_logo.strip() else None,
                "company_url_direct": company_url_direct.strip()
                if company_url_direct.strip()
                else None,
                "company_addresses": company_addresses.strip()
                if company_addresses.strip()
                else None,
                "company_num_employees": company_num_employees.strip()
                if company_num_employees.strip()
                else None,
                "company_revenue": company_revenue.strip()
                if company_revenue.strip()
                else None,
                "company_description": company_description.strip()
                if company_description.strip()
                else None,
                "min_amount": min_amount if min_amount > 0 else None,
                "max_amount": max_amount if max_amount > 0 else None,
                "currency": currency.strip() if currency.strip() else None,
                "interval": interval.strip() if interval.strip() else None,
                "salary_source": salary_source.strip()
                if salary_source.strip()
                else None,
                "archived": 0,
                "date_scraped": datetime.datetime.now().isoformat(),
            }

            # Show loading indicator
            with st.spinner("⏳ Processing job through evaluation pipeline..."):
                try:
                    # Run the pipeline
                    pipeline_result = process_single_job(job_data)
                except Exception as e:
                    logger.error(f"Error processing job: {e}")
                    pipeline_result = {"status": "error", "error": str(e)}

            # Handle results
            if pipeline_result.get("status") == "error":
                st.error(
                    f"❌ Pipeline processing failed: {pipeline_result.get('error', 'Unknown error')}"
                )
                st.info(
                    "💡 You can edit the form above and try again, or click Cancel below to return to the Job Browser."
                )

            elif pipeline_result.get("status") == "duplicate":
                st.warning(
                    "⚠️ This job appears very similar to an existing job in the database (based on content analysis)."
                )
                st.info(
                    "💡 The job was not saved to avoid duplicates. You can edit the description above and try again, or click Cancel below to return to the Job Browser."
                )

            else:
                # Success handling
                llm_score = pipeline_result.get("llm_score", 0)
                heuristic_score = pipeline_result.get("heuristic_score", 0.0)
                extracted_skills = pipeline_result.get("extracted_skills", [])
                match_result = pipeline_result.get("match_result")

                matched_count = len(match_result.matched) if match_result else 0
                partial_count = len(match_result.partial) if match_result else 0
                missing_count = len(match_result.missing) if match_result else 0

                if llm_score is not None:
                    st.success(f"✅ Job added successfully! Score: {llm_score}/10")
                else:
                    st.warning(
                        f"⚠️ Job not added due to not enough skills matched (heuristic: {heuristic_score:.3f} < 0.35)"
                    )

                # Show summary
                with st.expander("📊 Pipeline Results", expanded=True):
                    col_result1, col_result2, col_result3 = st.columns(3)
                    with col_result1:
                        score_display = (
                            f"{llm_score}/10" if llm_score is not None else "Not Scored"
                        )
                        st.metric("LLM Score", score_display)
                        st.metric("Heuristic Score", f"{heuristic_score:.3f}")
                    with col_result2:
                        st.metric("Skills Extracted", len(extracted_skills))
                        st.metric("Skills Matched", matched_count)
                    with col_result3:
                        st.metric("Skills Partial", partial_count)
                        st.metric("Skills Missing", missing_count)

                    if pipeline_result.get("llm_reasoning"):
                        st.write("**LLM Reasoning:**")
                        st.write(pipeline_result["llm_reasoning"])

                # Action buttons after success
                col_add_another, col_done = st.columns(2)
                with col_add_another:
                    if st.button(
                        "➕ Add Another Job",
                        use_container_width=True,
                        key="add_another",
                    ):
                        st.rerun()

                with col_done:
                    if st.button("✓ Done", use_container_width=True, key="done"):
                        st.session_state.adding_job = False
                        st.rerun()

                # Don't show cancel button after success
                st.stop()

    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.adding_job = False
            st.session_state.add_job_form_data = {}
            st.rerun()
