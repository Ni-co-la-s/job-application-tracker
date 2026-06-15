"""Main dashboard for Job Application Tracker."""

import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import constants
from modules.database import JobDatabase
from modules.prompts_loader import reload_prompts
from tabs.ai_tools_tab import render_ai_tools
from tabs.analytics_tab import render_analytics_tab
from tabs.job_browser_tab import get_resume_version_pdf, render_job_browser
from tabs.resume_tailoring_tab import render_resume_tailoring_tab
from tabs.scraping_tab import render_scraping_tab
from tabs.user_files_tab import render_user_files_tab

# Setup logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Job Application Tracker", layout="wide")


def init_session_state() -> None:
    """Initialize all session state variables."""
    if "selected_jobs" not in st.session_state:
        st.session_state.selected_jobs = set()
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = False
    if "page_size" not in st.session_state:
        st.session_state.page_size = 20
    if "current_page" not in st.session_state:
        st.session_state.current_page = 1
    if "title_text_filter" not in st.session_state:
        st.session_state.title_text_filter = ""
    if "description_text_filter" not in st.session_state:
        st.session_state.description_text_filter = ""


def startup_check() -> bool:
    """Validate required configuration files and directories.

    Returns:
        True if all checks pass, False otherwise.
    """
    # Check config directory
    config_dir = Path("config")
    if not config_dir.exists():
        st.error("❌ Config directory not found.")
        st.info("Please create a 'config' directory with the required files.")
        return False

    # Create missing local files from tracked examples.
    example_backed_files = [
        (".env", ".env.example", "environment variables"),
        ("config/prompts.json", "config/prompts.json.example", "prompts configuration"),
        ("config/resume.txt", "config/resume.txt.example", "resume text file"),
        (
            "config/candidate_skills.txt",
            "config/candidate_skills.txt.example",
            "candidate skills text file",
        ),
        ("config/searches.txt", "config/searches.txt.example", "searches text file"),
        (
            "config/interview_stages.json",
            "config/interview_stages.json.example",
            "interview stages configuration",
        ),
        ("config/presets.json", "config/presets.json.example", "chat presets"),
        ("config/queries.json", "config/queries.json.example", "analytics queries"),
    ]

    missing_files = []
    created_files = []
    for filepath, example_path, description in example_backed_files:
        target = Path(filepath)
        example = Path(example_path)
        if target.exists():
            continue
        if example.exists():
            shutil.copyfile(example, target)
            created_files.append(filepath)
        else:
            missing_files.append((filepath, description, example_path))

    if created_files:
        st.info(
            "Created missing local files from .example templates: "
            + ", ".join(created_files)
        )
        if ".env" in created_files:
            st.warning(
                "Please fill .env with real API keys, models, and base URLs in the file or in User Config → LLM Settings before using LLM features."
            )

    if missing_files:
        st.error("❌ Missing required configuration templates:")
        for filepath, description, example_path in missing_files:
            st.error(f"   - {filepath} ({description}); expected template: {example_path}")
        st.info("Please restore the missing .example files from the repository.")
        return False

    reload_prompts()

    # Create required directories
    Path(constants.RESUME_FINAL_DIR).mkdir(parents=True, exist_ok=True)
    Path(constants.RESUME_TEX_DIR).mkdir(parents=True, exist_ok=True)

    return True


def main() -> None:
    """Main dashboard function."""
    # Initialize session state
    init_session_state()

    # Run startup checks
    if not startup_check():
        st.stop()

    # Initialize database
    db = JobDatabase(constants.JOBS_DB)

    # Sidebar filters
    st.sidebar.title("🔍 Filters")

    # Score filter with min and max
    col1, col2 = st.sidebar.columns(2)
    with col1:
        min_score = st.number_input("Min Score", 0, 10, 0)
    with col2:
        max_score = st.number_input("Max Score", 0, 10, 10)

    # Website filter
    website_filter = st.sidebar.multiselect(
        "Job Sites",
        options=["indeed", "linkedin", "glassdoor", "zip_recruiter", "other"],
        default=[],  # Empty = all sites
    )

    company_filter = st.sidebar.text_input("Company")
    location_filter = st.sidebar.text_input("Location")

    # Text filters in sidebar
    title_text_filter = st.sidebar.text_input(
        "Filter by text in title", key="title_text_filter"
    )
    description_text_filter = st.sidebar.text_input(
        "Filter by text in description", key="description_text_filter"
    )

    # Application status filter
    applied_filter = st.sidebar.radio(
        "Application Status", ["All", "Applied", "Not Applied"]
    )

    archive_filter = st.sidebar.radio("Archive Status", ["Active", "Archived", "All"])

    # Sort options
    sort_by = st.sidebar.selectbox(
        "Sort By",
        [
            "Date (Newest First)",
            "Date (Oldest First)",
            "Score (Highest First)",
            "Score (Lowest First)",
        ],
    )

    date_range = st.sidebar.selectbox(
        "Date Range",
        ["All Time", "Last 7 Days", "Last 30 Days", "Last 90 Days", "Custom"],
    )

    # Custom date range
    if date_range == "Custom":
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input("From")
        with col2:
            end_date = st.date_input("To")

    # Build filters
    filters = {"min_score": min_score, "max_score": max_score}

    if archive_filter == "Active":
        filters["show_archived"] = "active"
    elif archive_filter == "Archived":
        filters["show_archived"] = "archived"
    else:
        filters["show_archived"] = "all"

    if website_filter:  # Only filter if user selected specific sites
        filters["sites"] = website_filter

    if company_filter:
        filters["company"] = company_filter
    if location_filter:
        filters["location"] = location_filter
    if title_text_filter:
        filters["title_text"] = title_text_filter
    if description_text_filter:
        filters["description_text"] = description_text_filter
    if applied_filter == "Applied":
        filters["applied"] = True
    elif applied_filter == "Not Applied":
        filters["not_applied"] = True

    if date_range != "All Time" and date_range != "Custom":
        days = {"Last 7 Days": 7, "Last 30 Days": 30, "Last 90 Days": 90}[date_range]
        filters["date_from"] = (datetime.now() - timedelta(days=days)).isoformat()
    elif date_range == "Custom":
        filters["date_from"] = start_date.isoformat()
        filters["date_to"] = end_date.isoformat()

    # Page size selector
    page_size = st.sidebar.selectbox(
        "Jobs per page", [10, 20, 50, 100, 200], index=1, key="page_size_selector"
    )
    if page_size != st.session_state.page_size:
        st.session_state.page_size = page_size
        st.session_state.current_page = 1

    # Map UI sorting options to database sorting parameters
    sort_mapping = {
        "Date (Newest First)": "date_desc",
        "Date (Oldest First)": "date_asc",
        "Score (Highest First)": "score_desc",
        "Score (Lowest First)": "score_asc",
    }
    db_sort_by = sort_mapping.get(sort_by)

    # Get jobs with pagination and sorting
    try:
        offset = (st.session_state.current_page - 1) * st.session_state.page_size
        jobs, total_count = db.get_all_jobs(
            filters, limit=st.session_state.page_size, offset=offset, sort_by=db_sort_by
        )
    except Exception as e:
        st.sidebar.error(f"⚠️ Error loading jobs: {e}")
        import traceback

        st.sidebar.code(traceback.format_exc())
        jobs, total_count = [], 0

    # Main content - Tabbed interface
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "📋 Job Browser",
            "🤖 AI Tools",
            "🧵 Resume Tailoring",
            "🔍 Scraping",
            "📊 Analytics",
            "⚙️ User Config",
        ]
    )

    with tab1:
        try:
            render_job_browser(db, jobs, total_count)
        except Exception as e:
            st.error(f"❌ Error in Job Browser tab: {e}")
            import traceback

            st.code(traceback.format_exc())

    with tab2:
        try:
            render_ai_tools(db, jobs)
        except Exception as e:
            logger.error(f"Error in AI Tools tab: {e}")
            st.error(f"❌ Error in AI Tools tab: {e}")
            import traceback

            st.code(traceback.format_exc())

    with tab3:
        try:
            render_resume_tailoring_tab(db, jobs)
        except Exception as e:
            logger.error(f"Error in Resume Tailoring tab: {e}")
            st.error(f"❌ Error in Resume Tailoring tab: {e}")
            import traceback

            st.code(traceback.format_exc())

    with tab4:
        try:
            render_scraping_tab()
        except Exception as e:
            st.error(f"❌ Error in Scraping tab: {e}")
            import traceback

            st.code(traceback.format_exc())

    with tab5:
        render_analytics_tab(db)

    with tab6:
        try:
            render_user_files_tab(db, jobs)
        except Exception as e:
            st.error(f"❌ Error in User Config tab: {e}")
            import traceback

            st.code(traceback.format_exc())

    try:
        # Export section in sidebar
        st.sidebar.markdown("---")
        st.sidebar.subheader("📥 Export")

        if jobs:
            # Export filtered jobs
            if st.sidebar.button("Export Filtered Jobs to CSV"):
                df = pd.DataFrame(jobs)
                csv = df.to_csv(index=False)
                st.sidebar.download_button(
                    "Download CSV",
                    csv,
                    f"jobs_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    "text/csv",
                )

            # Export selected jobs
            if st.session_state.selected_jobs:
                selected_jobs_list = [
                    j for j in jobs if j["id"] in st.session_state.selected_jobs
                ]
                if st.sidebar.button("Export Selected Jobs to CSV"):
                    df = pd.DataFrame(selected_jobs_list)
                    csv = df.to_csv(index=False)
                    st.sidebar.download_button(
                        "Download Selected CSV",
                        csv,
                        f"jobs_selected_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        "text/csv",
                    )

        # Database stats in sidebar
        st.sidebar.markdown("---")
        st.sidebar.subheader("📊 Database Stats")
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs")
        total_in_db = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE archived = 1")
        total_archived = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM applications")
        total_applied = cursor.fetchone()[0]

        # Get average score and high matches from all jobs
        cursor.execute(
            "SELECT AVG(llm_score), COUNT(*) FROM jobs WHERE llm_score IS NOT NULL"
        )
        avg_score_result = cursor.fetchone()
        avg_score = avg_score_result[0] or 0
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE llm_score >= 8")
        high_matches = cursor.fetchone()[0]

        # Stats by site
        cursor.execute(
            "SELECT site, COUNT(*) FROM jobs GROUP BY site ORDER BY COUNT(*) DESC"
        )
        site_stats = cursor.fetchall()

        st.sidebar.metric("Total Jobs", total_in_db)
        st.sidebar.metric("Archived", total_archived)
        st.sidebar.metric("Applied", total_applied)
        st.sidebar.metric("Avg Score", f"{avg_score:.1f}")
        st.sidebar.metric("High Matches (8+)", high_matches)

        if site_stats:
            with st.sidebar.expander("Jobs by Site"):
                for site, count in site_stats:
                    site_emoji = {
                        "indeed": "📄",
                        "linkedin": "💼",
                        "glassdoor": "🏢",
                        "zip_recruiter": "📨",
                        "other": "📝",
                    }.get(site.lower() if site else "", "🌐")
                    st.write(f"{site_emoji} {site or 'Unknown'}: {count}")

        # Resume folder info
        st.sidebar.markdown("---")
        st.sidebar.subheader("📁 Resume Folder")
        resume_versions = get_resume_version_pdf()
        if resume_versions:
            st.sidebar.success(f"✓ {len(resume_versions)} PDF resume(s) found")
            with st.sidebar.expander("View Resumes"):
                for resume in resume_versions:
                    st.write(f"• {resume}")
        else:
            st.sidebar.warning(
                f"⚠️ No PDF resumes in '{constants.RESUME_FINAL_DIR}' folder"
            )
            st.sidebar.caption(
                f"Add PDF resume files to '{constants.RESUME_FINAL_DIR}' folder to track versions"
            )

    except Exception as e:
        st.sidebar.error(f"⚠️ Sidebar error: {e}")
        import traceback

        st.sidebar.code(traceback.format_exc())


if __name__ == "__main__":
    main()
