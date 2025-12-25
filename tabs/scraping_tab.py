"""Scraping Tab for running job scraping directly from the dashboard."""

import atexit
import logging
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

# Global process tracker for cleanup
_active_processes: list[subprocess.Popen[Any]] = []

logger = logging.getLogger(__name__)


def cleanup_processes() -> None:
    """Kill any active scraping processes on exit."""
    for process in _active_processes:
        if process and process.poll() is None:  # Still running
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()  # Force kill if terminate didn't work
                except Exception:
                    pass


# Register cleanup handler
atexit.register(cleanup_processes)


@st.fragment(run_every=2)
def live_log_viewer() -> None:
    """Auto-refreshing fragment for live log output - only this section refreshes."""
    if not st.session_state.get("scraping_log_file"):
        st.info("👆 Click 'Start Scraping' to begin. Live output will appear here.")
        return

    # Check if process is still running and update state if needed
    if st.session_state.scraping_process is not None:
        if st.session_state.scraping_process.poll() is not None:
            # Process just finished
            if st.session_state.scraping_process in _active_processes:
                _active_processes.remove(st.session_state.scraping_process)

            st.session_state.scraping_process = None
            st.success("✅ Scraping completed!")

    # Show status if running
    is_running = st.session_state.scraping_process is not None
    if is_running:
        elapsed = datetime.now() - st.session_state.scraping_start_time
        st.info(
            f"🔄 Scraping in progress... Elapsed: {elapsed.seconds // 60}m {elapsed.seconds % 60}s"
        )

    # Display log content
    if (
        st.session_state.scraping_log_file
        and Path(st.session_state.scraping_log_file).exists()
    ):
        try:
            with open(st.session_state.scraping_log_file, "r") as f:
                output = f.read()

            if output:
                # Show last 1000 lines to prevent UI slowdown with huge logs
                lines = output.split("\n")
                if len(lines) > 1000:
                    display_output = "\n".join(lines[-1000:])
                    st.caption(f"⚠️ Showing last 1000 lines (total: {len(lines)} lines)")
                else:
                    display_output = output

                st.code(display_output, language="log")
            else:
                st.info("Waiting for output...")
        except Exception as e:
            st.error(f"Error reading log: {e}")
    else:
        st.info("👆 Click 'Start Scraping' to begin. Live output will appear here.")


def render_scraping_tab() -> None:
    """Render the job scraping interface."""
    try:
        st.title("🔍 Job Scraping")

        # Import constants from parent directory
        try:
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

            import constants

            SEARCHES_FILE = constants.SEARCHES_FILE
            RESUME_FILE = constants.RESUME_FILE
        except (ImportError, AttributeError) as e:
            st.error(f"❌ Configuration error: {e}")
            st.info(
                "Please ensure constants.py has SEARCHES_FILE and RESUME_FILE defined"
            )
            st.code(traceback.format_exc())
            return

        # Initialize session state
        if "scraping_process" not in st.session_state:
            st.session_state.scraping_process = None
        if "scraping_log_file" not in st.session_state:
            st.session_state.scraping_log_file = None
        if "scraping_start_time" not in st.session_state:
            st.session_state.scraping_start_time = None

        # ==================== CONFIGURATION SECTION ====================
        st.header("⚙️ Configuration")

        # Two columns: left for searches editor, right for parameters
        col_left, col_right = st.columns([1, 1])

        # ==================== LEFT: SEARCHES FILE EDITOR ====================
        with col_left:
            st.subheader("📝 Search Terms")

            searches_file_path = Path(SEARCHES_FILE)
            if searches_file_path.exists():
                with open(searches_file_path, "r", encoding="utf-8") as f:
                    current_searches = f.read()
            else:
                current_searches = "# Format: search_term|location|country\n# Example:\n# data scientist|Berlin|Germany\n"

            searches_text = st.text_area(
                "Edit search terms",
                value=current_searches,
                height=300,
                help="Format: search_term|location|country (one per line)\nLines starting with # are ignored",
                key="searches_editor",
            )

            col_save, col_preview = st.columns(2)
            with col_save:
                if st.button("💾 Save Searches", use_container_width=True):
                    try:
                        with open(searches_file_path, "w", encoding="utf-8") as f:
                            f.write(searches_text)
                        st.toast(f"✓ Saved to {SEARCHES_FILE}")
                    except Exception as e:
                        st.error(f"Error saving: {e}")

            with col_preview:
                if st.button("👁️ Preview", use_container_width=True):
                    st.session_state.show_preview = True

            if st.session_state.get("show_preview", False):
                st.divider()
                st.caption("**Parsed Searches:**")
                lines = searches_text.strip().split("\n")
                valid_searches = []
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split("|")
                        if len(parts) >= 1:
                            search_term = parts[0].strip()
                            location = parts[1].strip() if len(parts) > 1 else "N/A"
                            country = parts[2].strip() if len(parts) > 2 else "Germany"
                            valid_searches.append(
                                f"• {search_term} in {location}, {country}"
                            )

                if valid_searches:
                    for search in valid_searches:
                        st.caption(search)
                    st.info(f"Total: {len(valid_searches)} searches")
                else:
                    st.warning("No valid searches found")

        # ==================== RIGHT: SCRAPING PARAMETERS ====================
        with col_right:
            st.subheader("🎛️ Scraping Parameters")

            st.text_input(
                "Resume File",
                value=RESUME_FILE,
                disabled=True,
                help="Resume file is configured in constants.py",
            )

            sites = st.multiselect(
                "Job Sites",
                options=["indeed", "linkedin", "glassdoor", "zip_recruiter", "google"],
                default=["indeed", "linkedin"],
                help="Select which job sites to scrape",
            )

            results_per_site = st.slider(
                "Results per Site (per search)",
                min_value=1,
                max_value=200,
                value=50,
                step=1,
            )
            hours_old = st.number_input(
                "Maximum Job Age (hours)", min_value=1, max_value=720, value=24, step=1
            )
            job_type = st.selectbox(
                "Job Type (optional)",
                options=["Any", "fulltime", "parttime", "internship", "contract"],
                index=0,
            )
            is_remote = st.checkbox("Remote Only", value=False)
            min_score = st.slider(
                "Minimum Score to Save", min_value=0, max_value=10, value=0
            )
            heuristic_threshold = st.slider(
                "Heuristic Threshold",
                min_value=0.0,
                max_value=1.0,
                value=0.35,
                step=0.05,
                help="Heuristic score threshold for filtering jobs (0.0-1.0)",
            )
            batch_size = st.number_input(
                "Batch Size (LLM Concurrency)",
                min_value=1,
                max_value=100,
                value=10,
                step=1,
            )

            with st.expander("🔧 Advanced Options"):
                proxies_enabled = st.checkbox("Use Proxies", value=False)
                proxies_text = ""
                if proxies_enabled:
                    proxies_text = st.text_area(
                        "Proxies (one per line)", placeholder="user:pass@host:port"
                    )

        st.divider()

        # ==================== RUN SCRAPING ====================
        st.header("▶️ Run Scraping")

        # Check if scraping is running
        is_running = st.session_state.scraping_process is not None

        if is_running:
            # Check if process is still alive
            if st.session_state.scraping_process.poll() is not None:
                # Process finished - remove from tracker
                if st.session_state.scraping_process in _active_processes:
                    _active_processes.remove(st.session_state.scraping_process)

                is_running = False
                st.session_state.scraping_process = None

        # Build command
        cmd = [
            sys.executable,
            "jobspy_scraper.py",
            "--resume",
            RESUME_FILE,
            "--searches-file",
            SEARCHES_FILE,
            "--sites",
            *sites,
            "--results-per-site",
            str(results_per_site),
            "--hours-old",
            str(hours_old),
            "--min-score",
            str(min_score),
            "--heuristic-threshold",
            str(heuristic_threshold),
            "--batch-size",
            str(batch_size),
        ]

        if job_type != "Any":
            cmd.extend(["--job-type", job_type])

        if is_remote:
            cmd.append("--is-remote")

        if proxies_enabled and proxies_text:
            proxies_list = [p.strip() for p in proxies_text.split("\n") if p.strip()]
            if proxies_list:
                cmd.extend(["--proxies", *proxies_list])

        with st.expander("📋 Command Preview"):
            st.code(" ".join(cmd), language="bash")

        # Control buttons
        col_start, col_stop = st.columns(2)

        with col_start:
            if st.button(
                "🚀 Start Scraping",
                disabled=is_running or not sites,
                use_container_width=True,
                type="primary",
            ):
                if not Path(RESUME_FILE).exists():
                    st.error(f"❌ Resume file not found: {RESUME_FILE}")
                elif not sites:
                    st.error("❌ Please select at least one job site")
                else:
                    # Create temporary log file
                    log_file = tempfile.NamedTemporaryFile(
                        mode="w+", delete=False, suffix=".log"
                    )
                    st.session_state.scraping_log_file = log_file.name
                    log_file.close()

                    # Start process with output redirected to file
                    with open(st.session_state.scraping_log_file, "w") as f:
                        process = subprocess.Popen(
                            cmd,
                            stdout=f,
                            stderr=subprocess.STDOUT,
                            text=True,
                            bufsize=1,
                        )

                    st.session_state.scraping_process = process
                    st.session_state.scraping_start_time = datetime.now()

                    # Track process globally for cleanup
                    _active_processes.append(process)

                    st.rerun()

        with col_stop:
            if st.button(
                "⏹️ Stop Scraping",
                disabled=not is_running,
                use_container_width=True,
                type="secondary",
            ):
                if st.session_state.scraping_process:
                    st.session_state.scraping_process.terminate()

                    # Remove from global tracker
                    if st.session_state.scraping_process in _active_processes:
                        _active_processes.remove(st.session_state.scraping_process)

                    st.session_state.scraping_process = None
                    st.toast("⚠️ Scraping stopped")
                    st.rerun()

        # ==================== OUTPUT LOG (AUTO-REFRESHING FRAGMENT) ====================
        st.header("📄 Live Output")

        output_container = st.container(height=500)

        with output_container:
            # This fragment auto-refreshes every 2 seconds without blocking the rest of the UI
            live_log_viewer()

        # Download log button
        if (
            st.session_state.scraping_log_file
            and Path(st.session_state.scraping_log_file).exists()
        ):
            try:
                with open(st.session_state.scraping_log_file, "r") as f:
                    log_content = f.read()

                if log_content:
                    st.download_button(
                        "💾 Download Full Log",
                        data=log_content,
                        file_name=f"scraping_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )
            except Exception:
                pass

    except Exception as e:
        st.error("❌ Fatal error in scraping tab:")
        st.code(str(e))
        st.code(traceback.format_exc())
