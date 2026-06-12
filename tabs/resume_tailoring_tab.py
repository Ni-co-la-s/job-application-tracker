"""AI Resume Tailoring tab."""

import json
import re
from pathlib import Path
from typing import Any

import streamlit as st
from streamlit_pdf_viewer import pdf_viewer

import constants
from modules.database import JobDatabase
from modules.latex_builder import LatexBuildError, build_pdf
from modules.resume_editing import apply_approved_edits, has_manual_required
from modules.resume_tailoring import ResumeTailoringError, generate_tailoring_edits
from modules.resume_templates import (
    extract_document_body,
    get_template_dir,
    list_latex_templates,
    read_template_tex,
)


def render_resume_tailoring_tab(db: JobDatabase, jobs: list[dict[str, Any]]) -> None:
    """Render the AI Resume Tailoring tab."""
    st.title("🧵 AI Resume Tailoring")
    st.caption(
        "Tailor a LaTeX resume template to a saved job, review each AI edit, "
        "compile a PDF preview, then save only after approval."
    )

    _init_state()

    if not Path(constants.RESUME_FILE).exists():
        st.error(f"❌ Required information bank not found: `{constants.RESUME_FILE}`")
        st.info("Create config/resume.txt before generating tailoring edits.")
        return

    templates = list_latex_templates()
    if not templates:
        st.warning(f"⚠️ No LaTeX templates found in `{constants.RESUME_TEX_DIR}`.")
        st.info(
            "Create a folder like `Resumes/tex/base/resume.tex` and place any "
            "supporting .cls/.sty/fonts/images beside it."
        )
        return

    if not jobs:
        st.warning("📭 No jobs found. Add or scrape jobs before tailoring a resume.")
        return

    col_setup, col_history = st.columns([2, 1])

    with col_setup:
        selected_job = _render_job_selector(jobs)
        selected_template = st.selectbox("📄 Select LaTeX template", templates)

        with st.expander("Selected job description", expanded=False):
            st.markdown(selected_job.get("description") or "No description available")

        generate_disabled = not selected_job or not selected_template
        if st.button(
            "✨ Generate tailoring edits",
            type="primary",
            disabled=generate_disabled,
            width="stretch",
        ):
            _generate_edits(db, selected_job, selected_template)

    with col_history:
        st.markdown("### Recent runs for this job")
        for run in db.get_resume_tailoring_runs_for_job(selected_job["id"]):
            output_name = (
                Path(run["output_path"]).name if run.get("output_path") else "—"
            )
            st.caption(
                f"#{run['id']} • {run['status']} • {run['base_template']} • {output_name}"
            )

    if st.session_state.tailoring_edits:
        st.divider()
        _render_edit_review()
        st.divider()
        _render_build_and_save(db)


def _init_state() -> None:
    defaults = {
        "tailoring_run_id": None,
        "tailoring_job_id": None,
        "tailoring_template": None,
        "tailoring_source_tex": None,
        "tailoring_edits": [],
        "tailoring_apply_results": [],
        "tailoring_pdf_bytes": None,
        "tailoring_output_name": "",
        "tailoring_raw_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_job_selector(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    job_options = {
        f"#{job['id']} • {job['title']} @ {job['company']} ({job['llm_score'] or 0}/10)": job
        for job in jobs
    }
    selected_label = st.selectbox("💼 Select target job", list(job_options.keys()))
    return job_options[selected_label]


def _generate_edits(
    db: JobDatabase, selected_job: dict[str, Any], selected_template: str
) -> None:
    try:
        source_tex = read_template_tex(selected_template)
        current_resume_body = extract_document_body(source_tex)

        with st.spinner("Generating search/replacement edits..."):
            edits = generate_tailoring_edits(selected_job, current_resume_body)

        run_id = db.create_resume_tailoring_run(
            selected_job["id"], selected_template, status="draft"
        )

        st.session_state.tailoring_run_id = run_id
        st.session_state.tailoring_job_id = selected_job["id"]
        st.session_state.tailoring_template = selected_template
        st.session_state.tailoring_source_tex = source_tex
        st.session_state.tailoring_edits = [
            {**edit.model_dump(), "accepted": True, "apply_status": "pending"}
            for edit in edits
        ]
        st.session_state.tailoring_apply_results = []
        st.session_state.tailoring_pdf_bytes = None
        st.session_state.tailoring_output_name = _default_output_name(
            selected_template, selected_job
        )
        st.session_state.tailoring_raw_error = None
        st.toast(f"Generated {len(edits)} edit(s).")
        st.rerun()
    except ResumeTailoringError as exc:
        st.error(str(exc))
        if exc.raw_output:
            st.session_state.tailoring_raw_error = exc.raw_output
            with st.expander("Raw model output", expanded=True):
                st.code(exc.raw_output)
    except FileNotFoundError as exc:
        st.error(f"Required file not found: {exc}")
    except Exception as exc:
        st.error(f"Unexpected tailoring error: {exc}")


def _render_edit_review() -> None:
    st.markdown("## Review proposed edits")
    st.info("Accept only the edits you want included in the compiled PDF.")

    for index, edit in enumerate(st.session_state.tailoring_edits):
        with st.expander(
            f"Edit {index + 1}: {edit.get('reason', 'No reason')}", expanded=True
        ):
            accepted = st.checkbox(
                "Accept this edit",
                value=bool(edit.get("accepted", True)),
                key=f"tailoring_accept_{st.session_state.tailoring_run_id}_{index}",
            )
            st.session_state.tailoring_edits[index]["accepted"] = accepted

            col_search, col_replacement = st.columns(2)
            with col_search:
                st.markdown("**Search**")
                st.markdown(
                    f"<div style='background:#4a1515;color:#ffd8d8;padding:0.75rem;border-radius:0.4rem;white-space:pre-wrap'>{_html_escape(edit['search'])}</div>",
                    unsafe_allow_html=True,
                )
            with col_replacement:
                st.markdown("**Replacement**")
                st.markdown(
                    f"<div style='background:#123d22;color:#d8ffe5;padding:0.75rem;border-radius:0.4rem;white-space:pre-wrap'>{_html_escape(edit['replacement'])}</div>",
                    unsafe_allow_html=True,
                )
            st.caption(f"Reason: {edit.get('reason', '')}")


def _render_build_and_save(db: JobDatabase) -> None:
    st.markdown("## Build preview")

    timeout = st.number_input("Build timeout seconds", 30, 300, 120, step=30)

    if st.button("🔨 Build PDF preview", type="primary"):
        _build_preview(db, int(timeout))

    if st.session_state.tailoring_apply_results:
        with st.expander("Edit application results", expanded=True):
            for result in st.session_state.tailoring_apply_results:
                status = result.get("apply_status")
                message = result.get("apply_message")
                edit_index = result.get("edit_index")
                edit_label = edit_index + 1 if isinstance(edit_index, int) else "?"
                st.write(f"Edit {edit_label}: `{status}` — {message}")

    pdf_bytes = st.session_state.tailoring_pdf_bytes
    if pdf_bytes:
        st.success("PDF compiled successfully. Review it before saving.")
        pdf_viewer(input=pdf_bytes)

        output_name = st.text_input(
            "Output filename",
            value=st.session_state.tailoring_output_name,
            help="Saved under Resumes/final/ after approval.",
        )
        st.session_state.tailoring_output_name = output_name

        if st.button("✅ Approve & save", type="primary"):
            _save_pdf(db, pdf_bytes, output_name)


def _build_preview(db: JobDatabase, timeout: int) -> None:
    source_tex = st.session_state.tailoring_source_tex
    template_name = st.session_state.tailoring_template
    run_id = st.session_state.tailoring_run_id
    if not source_tex or not template_name or not run_id:
        st.error("No active tailoring run. Generate edits first.")
        return

    tailored_tex, results = apply_approved_edits(
        source_tex, st.session_state.tailoring_edits
    )
    st.session_state.tailoring_apply_results = results

    if has_manual_required(results):
        st.error(
            "Some accepted edits couldn't auto-apply. Reject or manually resolve them first."
        )
        db.update_resume_tailoring_run(
            run_id,
            status="manual_required",
            edits_json=json.dumps(results, indent=2),
        )
        return

    try:
        with st.spinner("Compiling LaTeX..."):
            pdf_bytes = build_pdf(
                tailored_tex,
                template_dir=get_template_dir(template_name),
                engine="auto",
                timeout=timeout,
            )
        st.session_state.tailoring_pdf_bytes = pdf_bytes
        db.update_resume_tailoring_run(
            run_id, status="previewed", edits_json=json.dumps(results, indent=2)
        )
        st.rerun()
    except LatexBuildError as exc:
        st.session_state.tailoring_pdf_bytes = None
        db.update_resume_tailoring_run(
            run_id, status="build_error", edits_json=json.dumps(results, indent=2)
        )
        st.error(f"LaTeX build failed:\n{exc}")
        if exc.full_log:
            with st.expander("Full LaTeX build log", expanded=True):
                st.code(exc.full_log, language="text")


def _save_pdf(db: JobDatabase, pdf_bytes: bytes, output_name: str) -> None:
    run_id = st.session_state.tailoring_run_id
    if not run_id:
        st.error("No tailoring run to save.")
        return

    filename = _sanitize_pdf_filename(output_name)
    output_path = Path(constants.RESUME_FINAL_DIR) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)

    db.update_resume_tailoring_run(
        run_id,
        output_path=str(output_path),
        status="saved",
        edits_json=json.dumps(st.session_state.tailoring_apply_results, indent=2),
    )
    st.success(f"Saved tailored resume to `{output_path}`")
    st.toast("Tailored resume saved.")


def _default_output_name(base_template: str, job: dict[str, Any]) -> str:
    company = _slug(job.get("company") or "company")
    base = _slug(base_template)
    return f"{base}__{company}_{job['id']}.pdf"


def _sanitize_pdf_filename(filename: str) -> str:
    stem = Path(filename).stem if filename else "tailored_resume"
    return f"{_slug(stem)}.pdf"


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("._-")
    return value or "resume"


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
