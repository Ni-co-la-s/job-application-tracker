"""AI Resume Tailoring tab."""

import json
import re
import time
from pathlib import Path
from typing import Any

import streamlit as st
from streamlit_pdf_viewer import pdf_viewer

import constants
from modules.database import JobDatabase
from modules.latex_builder import LatexBuildError, build_pdf
from modules.resume_editing import (
    STATUS_APPLIED_EXACT,
    STATUS_APPLIED_NORMALIZED_WHITESPACE,
    STATUS_MANUAL_REQUIRED,
    STATUS_REJECTED,
    match_edit_once,
)
from modules.resume_redaction import build_redaction_map, redact, restore
from modules.resume_tailoring import ResumeTailoringError, generate_tailoring_edits
from modules.resume_templates import (
    extract_document_body,
    get_template_dir,
    list_latex_templates,
    read_template_tex,
)

APPLICABLE_STATUSES = {STATUS_APPLIED_EXACT, STATUS_APPLIED_NORMALIZED_WHITESPACE}


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
        preview = _prepare_redacted_preview(selected_template)

        with st.expander("Selected job description", expanded=False):
            st.markdown(selected_job.get("description") or "No description available")

        with st.expander("Resume sent to model", expanded=False):
            st.code(preview["redacted_body"], language="latex")
            redaction_note = (
                f"{preview['redaction_count']} string(s) redacted"
                if preview["redaction_count"]
                else "no redactions configured"
            )
            st.caption(
                f"{redaction_note}. Only this LaTeX body is redacted; "
                "config/resume.txt is sent to the model as-is."
            )

        generate_disabled = not selected_job or not selected_template
        if st.button(
            "✨ Generate tailoring edits",
            type="primary",
            disabled=generate_disabled,
            width="stretch",
        ):
            _generate_edits(selected_job, selected_template, preview)

    with col_history:
        st.markdown("### Recent runs for this job")
        for run in db.get_resume_tailoring_runs_for_job(selected_job["id"]):
            output_name = (
                Path(run["output_path"]).name if run.get("output_path") else "—"
            )
            st.caption(
                f"#{run['id']} • {run['base_template']} • {output_name} • {run['created_at']}"
            )

    if st.session_state.tailoring_edits:
        st.divider()
        _render_edit_review()
        st.divider()
        _render_tailored_resume_editor()
        st.divider()
        _render_build_and_save(db)


def _init_state() -> None:
    defaults = {
        "tailoring_generation_id": None,
        "tailoring_job_id": None,
        "tailoring_template": None,
        "tailoring_source_tex": None,
        "tailoring_redacted_body": "",
        "tailoring_redaction_count": 0,
        "tailoring_redaction_map": {},
        "tailoring_edits": [],
        "tailoring_apply_results": [],
        "tailoring_pdf_bytes": None,
        "tailoring_output_name": "",
        "tailoring_raw_error": None,
        "tailoring_saved_edits_json": "[]",
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


def _prepare_redacted_preview(selected_template: str) -> dict[str, Any]:
    source_tex = read_template_tex(selected_template)
    current_resume_body = extract_document_body(source_tex)
    redaction_map = build_redaction_map(_load_redaction_strings(selected_template))
    return {
        "source_tex": source_tex,
        "body": current_resume_body,
        "redacted_body": redact(current_resume_body, redaction_map),
        "redaction_map": redaction_map,
        "redaction_count": len(redaction_map),
    }


def _generate_edits(
    selected_job: dict[str, Any], selected_template: str, preview: dict[str, Any]
) -> None:
    try:
        with st.spinner("Generating search/replacement edits..."):
            edits = generate_tailoring_edits(selected_job, preview["redacted_body"])

        generation_id = f"{selected_job['id']}_{selected_template}_{time.time_ns()}"
        reviewed_edits = _review_generated_edits(
            preview["source_tex"], edits, preview["redaction_map"]
        )

        st.session_state.tailoring_generation_id = generation_id
        st.session_state.tailoring_job_id = selected_job["id"]
        st.session_state.tailoring_template = selected_template
        st.session_state.tailoring_source_tex = preview["source_tex"]
        st.session_state.tailoring_redacted_body = preview["redacted_body"]
        st.session_state.tailoring_redaction_count = preview["redaction_count"]
        st.session_state.tailoring_redaction_map = preview["redaction_map"]
        st.session_state.tailoring_edits = reviewed_edits
        st.session_state.tailoring_apply_results = []
        st.session_state.tailoring_pdf_bytes = None
        st.session_state.tailoring_output_name = _default_output_name(
            selected_template, selected_job
        )
        st.session_state.tailoring_raw_error = None
        st.session_state.tailoring_saved_edits_json = "[]"
        st.session_state[_tailored_text_key(generation_id)] = preview["source_tex"]
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


def _review_generated_edits(
    source_tex: str, edits: list[Any], mapping: dict[str, str]
) -> list[dict]:
    reviewed: list[dict] = []
    for index, edit in enumerate(edits):
        raw = edit.model_dump()
        token_error = _token_integrity_error(
            raw.get("search", ""), mapping
        ) or _token_integrity_error(raw.get("replacement", ""), mapping)
        restored_search = restore(raw.get("search", ""), mapping)
        restored_replacement = restore(raw.get("replacement", ""), mapping)
        reviewed_edit = {
            **raw,
            "edit_index": index,
            "accepted": True,
            "restored_search": restored_search,
            "restored_replacement": restored_replacement,
            "apply_status": STATUS_MANUAL_REQUIRED,
            "apply_message": token_error or "Pending match.",
            "matched_start": None,
            "matched_end": None,
            "matched_start_line": None,
            "matched_end_line": None,
        }
        if not token_error:
            match = match_edit_once(source_tex, restored_search)
            reviewed_edit.update(
                {
                    "apply_status": match.status,
                    "apply_message": match.message,
                    "matched_start": match.start,
                    "matched_end": match.end,
                    "matched_start_line": match.start_line,
                    "matched_end_line": match.end_line,
                }
            )
        reviewed.append(reviewed_edit)
    _flag_overlapping_matches(reviewed)
    return reviewed


def _flag_overlapping_matches(edits: list[dict]) -> None:
    overlapped_indexes: set[int] = set()
    applicable = [
        edit
        for edit in edits
        if edit.get("apply_status") in APPLICABLE_STATUSES
        and edit.get("matched_start") is not None
        and edit.get("matched_end") is not None
    ]
    for left_pos, left in enumerate(applicable):
        for right in applicable[left_pos + 1 :]:
            if (
                left["matched_start"] < right["matched_end"]
                and right["matched_start"] < left["matched_end"]
            ):
                overlapped_indexes.add(left["edit_index"])
                overlapped_indexes.add(right["edit_index"])
    for edit in edits:
        if edit["edit_index"] in overlapped_indexes:
            edit["apply_status"] = STATUS_MANUAL_REQUIRED
            edit["apply_message"] = (
                "Matched span overlaps another proposed edit; resolve manually in the editable resume."
            )


def _render_edit_review() -> None:
    st.markdown("## Review proposed edits")
    st.info(
        "Accept applicable edits, then click **Apply accepted edits**. Manual-required edits "
        "are visible here and should be fixed directly in the editable resume below."
    )

    for index, edit in enumerate(st.session_state.tailoring_edits):
        with st.expander(
            f"Edit {index + 1}: {edit.get('reason', 'No reason')}", expanded=True
        ):
            accepted = st.checkbox(
                "Accept this edit",
                value=bool(edit.get("accepted", True)),
                key=f"tailoring_accept_{st.session_state.tailoring_generation_id}_{index}",
            )
            st.session_state.tailoring_edits[index]["accepted"] = accepted

            status = edit.get("apply_status", STATUS_MANUAL_REQUIRED)
            status_text = f"Status: `{status}` — {edit.get('apply_message', '')}"
            if status in APPLICABLE_STATUSES:
                st.success(status_text)
                st.caption(
                    f"Matched lines {edit.get('matched_start_line')}–{edit.get('matched_end_line')} "
                    "in the full resume.tex file."
                )
            else:
                st.warning(
                    f"{status_text}. Couldn't auto-apply — fix manually in the editable resume below."
                )

            col_search, col_replacement = st.columns(2)
            with col_search:
                st.markdown("**Search**")
                st.markdown(
                    _colored_block(
                        edit.get("restored_search") or edit.get("search", ""),
                        "#4a1515",
                        "#ffd8d8",
                    ),
                    unsafe_allow_html=True,
                )
            with col_replacement:
                st.markdown("**Replacement**")
                st.markdown(
                    _colored_block(
                        edit.get("restored_replacement") or edit.get("replacement", ""),
                        "#123d22",
                        "#d8ffe5",
                    ),
                    unsafe_allow_html=True,
                )
            st.caption(f"Reason: {edit.get('reason', '')}")

    if st.button("Apply accepted edits", type="primary"):
        _apply_accepted_edits_to_editor()


def _render_tailored_resume_editor() -> None:
    st.markdown("## Tailored resume")
    generation_id = st.session_state.tailoring_generation_id
    text_key = _tailored_text_key(generation_id)
    if text_key not in st.session_state:
        st.session_state[text_key] = st.session_state.tailoring_source_tex or ""

    with st.expander("Tailored resume (editable)", expanded=True):
        st.text_area(
            "Full tailored resume.tex",
            key=text_key,
            height=520,
            help="Manual edits here are compiled by Build PDF preview. They are not overwritten unless you click Apply accepted edits again.",
        )


def _render_build_and_save(db: JobDatabase) -> None:
    st.markdown("## Build preview")

    timeout = st.number_input("Build timeout seconds", 30, 300, 120, step=30)

    if st.button("🔨 Build PDF preview", type="primary"):
        _build_preview(int(timeout))

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


def _apply_accepted_edits_to_editor() -> None:
    source_tex = st.session_state.tailoring_source_tex
    if not source_tex:
        st.error("No active tailoring run. Generate edits first.")
        return

    updated_parts: list[str] = []
    cursor = 0
    results: list[dict] = []

    accepted_applicable = [
        (index, edit)
        for index, edit in enumerate(st.session_state.tailoring_edits)
        if edit.get("accepted") and edit.get("apply_status") in APPLICABLE_STATUSES
    ]
    accepted_applicable.sort(key=lambda item: item[1].get("matched_start") or 0)

    for index, edit in enumerate(st.session_state.tailoring_edits):
        if not edit.get("accepted"):
            results.append(
                {
                    **edit,
                    "edit_index": index,
                    "apply_status": STATUS_REJECTED,
                    "apply_message": "Rejected.",
                }
            )
            continue

        if edit.get("apply_status") not in APPLICABLE_STATUSES:
            results.append({**edit, "edit_index": index})
            continue

        results.append(
            {
                **edit,
                "edit_index": index,
                "apply_message": "Applied from review-time full-file match span.",
            }
        )

    for _index, edit in accepted_applicable:
        start = edit.get("matched_start")
        end = edit.get("matched_end")
        if start is None or end is None:
            continue
        updated_parts.append(source_tex[cursor:start])
        updated_parts.append(edit.get("restored_replacement", ""))
        cursor = end
    updated_parts.append(source_tex[cursor:])
    updated_tex = "".join(updated_parts)

    st.session_state[_tailored_text_key(st.session_state.tailoring_generation_id)] = (
        updated_tex
    )
    st.session_state.tailoring_apply_results = results
    st.session_state.tailoring_saved_edits_json = json.dumps(results, indent=2)
    st.session_state.tailoring_pdf_bytes = None
    st.toast("Accepted applicable edits applied to editable resume.")
    st.rerun()


def _build_preview(timeout: int) -> None:
    template_name = st.session_state.tailoring_template
    generation_id = st.session_state.tailoring_generation_id
    if not template_name or not generation_id:
        st.error("No active tailoring run. Generate edits first.")
        return

    tailored_tex = st.session_state.get(_tailored_text_key(generation_id), "")
    if not tailored_tex.strip():
        st.error("Tailored resume text is empty.")
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
        st.rerun()
    except LatexBuildError as exc:
        st.session_state.tailoring_pdf_bytes = None
        st.error(f"LaTeX build failed:\n{exc}")
        if exc.full_log:
            with st.expander("Full LaTeX build log", expanded=True):
                st.code(exc.full_log, language="text")


def _save_pdf(db: JobDatabase, pdf_bytes: bytes, output_name: str) -> None:
    if not st.session_state.tailoring_job_id or not st.session_state.tailoring_template:
        st.error("No tailoring run to save.")
        return

    filename = _sanitize_pdf_filename(output_name)
    output_path = Path(constants.RESUME_FINAL_DIR) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)

    db.save_resume_tailoring_run(
        job_id=st.session_state.tailoring_job_id,
        base_template=st.session_state.tailoring_template,
        output_path=str(output_path),
        edits_json=st.session_state.tailoring_saved_edits_json,
    )
    st.success(f"Saved tailored resume to `{output_path}`")
    st.toast("Tailored resume saved.")


def _load_redaction_strings(template_name: str) -> list[str]:
    path = get_template_dir(template_name) / "pii_redactions.txt"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _token_integrity_error(text: str, mapping: dict[str, str]) -> str | None:
    valid_tokens = set(mapping.values())
    for token in re.findall(r"\[\[REDACT_\d+\]\]", text):
        if token not in valid_tokens:
            return f"Unknown redaction token from model output: {token}"

    without_valid_tokens = text
    for token in valid_tokens:
        without_valid_tokens = without_valid_tokens.replace(token, "")
    if "[[REDACT" in without_valid_tokens or "REDACT_" in without_valid_tokens:
        return "Malformed or partial redaction token in model output."
    return None


def _tailored_text_key(generation_id: str | None) -> str:
    return f"tailoring_tailored_tex_{generation_id or 'none'}"


def _colored_block(value: str, background: str, color: str) -> str:
    return (
        f"<div style='background:{background};color:{color};padding:0.75rem;"
        f"border-radius:0.4rem;white-space:pre-wrap'>{_html_escape(value)}</div>"
    )


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
