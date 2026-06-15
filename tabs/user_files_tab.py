"""User configuration tab for editable profile files, LLM settings, and prompt tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

import constants
from modules.llm_config import get_config_manager, reload_config_manager
from modules.prompt_testing import (
    run_extraction_and_matching_preview,
    run_job_scoring_preview,
    run_resume_tailoring_preview,
)
from modules.prompts_loader import load_prompts, reload_prompts
from modules.resume_editing import (
    STATUS_APPLIED_EXACT,
    STATUS_APPLIED_NORMALIZED_WHITESPACE,
)
from modules.resume_templates import list_latex_templates


ENV_FILE = Path(".env")
LLM_STAGES = {
    "skills_extraction": {
        "label": "Skills Extraction",
        "description": "Extracts skills, tools, software, standards, and hard requirements from a job description.",
    },
    "skills_matching": {
        "label": "Skills Matching",
        "description": "Compares extracted job skills against your candidate_skills.txt profile and groups them as matched, partial, or missing.",
    },
    "job_scoring": {
        "label": "Job Scoring",
        "description": "Scores a job against your resume.txt and writes the score/reasoning used in the job database.",
    },
    "chat": {
        "label": "Chat",
        "description": "Powers the conversational AI Tools tab and preset-based job chat.",
    },
    "resume_tailoring": {
        "label": "Resume Tailoring",
        "description": "Generates search/replacement edits for tailoring LaTeX resumes to selected jobs.",
    },
}


def _read_text_file(path: str | Path, fallback_path: str | Path | None = None) -> str:
    file_path = Path(path)
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    if fallback_path and Path(fallback_path).exists():
        return Path(fallback_path).read_text(encoding="utf-8")
    return ""


def _write_text_file(path: str | Path, content: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True) if file_path.parent != Path(
        "."
    ) else None
    file_path.write_text(content, encoding="utf-8")


def _parse_env_lines(content: str) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    order: list[str] = []
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
        order.append(key)
    return values, order


def _serialize_env(existing_content: str, updates: dict[str, str]) -> str:
    """Update known env keys while preserving unrelated lines and comments."""
    lines = existing_content.splitlines()
    written: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            output.append(line)

    missing = [key for key in updates if key not in written]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# ============= Added from User Config UI =============")
        for key in missing:
            output.append(f"{key}={updates[key]}")

    return "\n".join(output).rstrip() + "\n"


def _render_text_file_editor(
    *,
    title: str,
    path: str,
    fallback_path: str,
    description: str,
    key: str,
    height: int,
) -> None:
    st.subheader(title)
    st.info(description)
    content = _read_text_file(path, fallback_path)
    edited = st.text_area(
        f"Edit {path}",
        value=content,
        height=height,
        key=key,
    )
    if st.button(f"💾 Save {Path(path).name}", key=f"save_{key}"):
        _write_text_file(path, edited)
        st.success(
            f"Saved {path}. The next pipeline or prompt-test run will use the new content."
        )


def _render_prompt_editor() -> None:
    st.subheader("Pipeline Prompts")
    st.info(
        "These prompts control the existing LangGraph pipeline stages. Each JSON key is shown as its own multiline editor so you can edit real line breaks instead of escaped \\n sequences. Saving reloads the in-process prompt cache."
    )

    prompts = load_prompts()
    if not isinstance(prompts, dict):
        st.error(
            "prompts.json must contain a JSON object mapping prompt names to prompt text."
        )
        return

    edited_prompts: dict[str, str] = {}
    for prompt_key, prompt_value in prompts.items():
        with st.expander(prompt_key, expanded=False):
            edited_prompts[prompt_key] = st.text_area(
                prompt_key,
                value=str(prompt_value),
                height=260 if "SCORING" in prompt_key else 220,
                key=f"prompt_{prompt_key}",
                label_visibility="collapsed",
            )

    col_save, col_reload = st.columns([1, 3])
    with col_save:
        if st.button("💾 Save prompts", type="primary", key="save_prompts"):
            Path(constants.PROMPTS_FILE).write_text(
                json.dumps(edited_prompts, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
            reload_prompts()
            st.success(
                "Saved prompts.json and reloaded prompt cache. New prompt-test and pipeline runs will use these prompts."
            )
    with col_reload:
        if st.button("🔄 Reload prompts from disk", key="reload_prompts"):
            reload_prompts()
            st.success("Reloaded prompts from disk.")
            st.rerun()


def _render_env_editor() -> None:
    st.subheader("LLM Stage Configuration (.env)")
    st.info(
        "Configure each OpenAI-compatible model separately. API keys are displayed as password fields. Saving preserves unrelated .env lines and reloads the app's LLM configuration without requiring a server restart."
    )

    env_content = _read_text_file(ENV_FILE)
    env_values, _ = _parse_env_lines(env_content)
    updates: dict[str, str] = {}

    config_manager = get_config_manager()
    config_summary = config_manager.get_config_summary()

    for stage_name, meta in LLM_STAGES.items():
        prefix = stage_name.upper()
        summary = config_summary.get(stage_name, {})
        with st.expander(
            f"{meta['label']} ({stage_name})", expanded=stage_name == "chat"
        ):
            st.caption(meta["description"])
            col_model, col_base = st.columns(2)
            with col_model:
                updates[f"{prefix}_MODEL"] = st.text_input(
                    "Model",
                    value=env_values.get(f"{prefix}_MODEL", summary.get("model", "")),
                    key=f"env_{prefix}_MODEL",
                ).strip()
            with col_base:
                updates[f"{prefix}_BASE_URL"] = st.text_input(
                    "Base URL",
                    value=env_values.get(f"{prefix}_BASE_URL", ""),
                    key=f"env_{prefix}_BASE_URL",
                    placeholder="https://api.openai.com/v1 or local OpenAI-compatible endpoint",
                ).strip()

            updates[f"{prefix}_API_KEY"] = st.text_input(
                "API Key",
                value=env_values.get(f"{prefix}_API_KEY", ""),
                type="password",
                key=f"env_{prefix}_API_KEY",
            ).strip()

            status_col, test_col = st.columns([2, 1])
            with status_col:
                if summary.get("configured"):
                    st.success(f"Configured: {summary.get('model', 'Unknown model')}")
                else:
                    st.warning("Not configured yet")
            with test_col:
                if st.button("🔌 Test connection", key=f"test_{stage_name}"):
                    # Ensure tests use values currently saved in .env.
                    reload_config_manager()
                    success, message = get_config_manager().test_stage_connection(
                        stage_name
                    )
                    if success:
                        st.success(message)
                    else:
                        st.error(message)

    if st.button("💾 Save .env settings", type="primary", key="save_env"):
        new_content = _serialize_env(env_content, updates)
        ENV_FILE.write_text(new_content, encoding="utf-8")
        reload_config_manager()
        st.success(
            "Saved .env and reloaded LLM configuration. Connection tests and new LLM calls will use the saved values."
        )
        st.rerun()


def _render_result_block(title: str, result: dict[str, Any] | None) -> None:
    st.markdown(f"#### {title}")
    if result is None:
        st.warning("No result produced.")
        return
    if result.get("error"):
        st.error(result["error"])

    messages = result.get("messages", [])
    for message in messages:
        label = "System prompt" if message.get("role") == "system" else "User prompt"
        with st.expander(label, expanded=False):
            st.code(message.get("content", ""), language="text")

    if "raw_output" in result:
        with st.expander("Raw model output", expanded=True):
            st.code(result["raw_output"], language="text")
    if "parse_error" in result:
        st.warning(f"Parse warning: {result['parse_error']}")
    if "parsed" in result:
        st.markdown("**Parsed result**")
        st.json(result["parsed"])


def _render_colored_block(value: str, background: str, color: str) -> None:
    escaped = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    st.markdown(
        f"<div style='background:{background};color:{color};padding:0.75rem;"
        f"border-radius:0.4rem;white-space:pre-wrap'>{escaped}</div>",
        unsafe_allow_html=True,
    )


def _render_resume_tailoring_test_result(result: dict[str, Any] | None) -> None:
    st.markdown("#### Resume tailoring")
    if result is None:
        st.warning("No result produced.")
        return

    if result.get("error"):
        st.error(result["error"])

    messages = result.get("messages", [])
    for message in messages:
        label = "System prompt" if message.get("role") == "system" else "User prompt"
        with st.expander(label, expanded=False):
            st.code(message.get("content", ""), language="text")

    metadata = [f"Stage: `{result.get('stage', 'resume_tailoring')}`"]
    if result.get("model"):
        metadata.append(f"Model: `{result['model']}`")
    if result.get("template"):
        metadata.append(f"Template: `{result['template']}`")
    st.caption(" • ".join(metadata))

    if "redacted_body" in result:
        with st.expander("Resume sent to model", expanded=False):
            st.code(result["redacted_body"], language="latex")
            count = result.get("redaction_count", 0)
            st.caption(
                f"{count} string(s) redacted. config/resume.txt is sent to the model as-is by the tailoring prompt."
            )

    if "raw_output" in result:
        with st.expander("Raw model output", expanded=True):
            st.code(result["raw_output"], language="text")

    if "parse_error" in result:
        st.warning(f"Parse warning: {result['parse_error']}")

    edits = result.get("parsed", {}).get("edits", [])
    if not edits:
        if not result.get("error"):
            st.info("The model returned no edits.")
        return

    st.markdown("**Proposed edits**")
    applicable_statuses = {STATUS_APPLIED_EXACT, STATUS_APPLIED_NORMALIZED_WHITESPACE}
    for index, edit in enumerate(edits):
        reason = edit.get("reason") or "No reason"
        with st.expander(f"Edit {index + 1}: {reason}", expanded=True):
            status = edit.get("apply_status", "unknown")
            message = edit.get("apply_message", "")
            if status in applicable_statuses:
                st.success(f"Status: `{status}` — {message}")
                if edit.get("matched_start_line") and edit.get("matched_end_line"):
                    st.caption(
                        f"Matched lines {edit['matched_start_line']}–{edit['matched_end_line']} in the full resume.tex file."
                    )
            else:
                st.warning(f"Status: `{status}` — {message}")

            col_search, col_replacement = st.columns(2)
            with col_search:
                st.markdown("**Search**")
                _render_colored_block(
                    edit.get("restored_search") or edit.get("search", ""),
                    "#4a1515",
                    "#ffd8d8",
                )
            with col_replacement:
                st.markdown("**Replacement**")
                _render_colored_block(
                    edit.get("restored_replacement") or edit.get("replacement", ""),
                    "#123d22",
                    "#d8ffe5",
                )
            st.caption(f"Reason: {reason}")


def _render_prompt_testing(jobs: list[dict[str, Any]]) -> None:
    st.subheader("Prompt Testing")
    st.info(
        "Run existing pipeline prompts against one job without saving results to the database. This helps debug prompts by showing rendered inputs, raw outputs, and parsed results."
    )

    if not jobs:
        st.warning("No jobs available with the current sidebar filters.")
        return

    job_options = {
        f"{j.get('title') or 'Untitled'} @ {j.get('company') or 'Unknown'} (ID: {j.get('id')}, Score: {j.get('llm_score') or 0}/10)": j
        for j in jobs
    }
    selected_label = st.selectbox(
        "Select a job from the current filtered list",
        options=list(job_options.keys()),
        key="prompt_test_job_select",
    )
    selected_job = job_options[selected_label]

    with st.expander("Selected job description", expanded=False):
        st.markdown(selected_job.get("description") or "No description available")

    test_options = ["Skills extraction + matching", "Job scoring", "Resume tailoring"]
    test_type = st.radio(
        "Prompt test",
        test_options,
        horizontal=True,
        key="prompt_test_type",
    )

    selected_template = None
    if test_type == "Resume tailoring":
        templates = list_latex_templates()
        if templates:
            selected_template = st.selectbox(
                "📄 Select LaTeX template",
                templates,
                key="prompt_test_resume_template",
            )
        else:
            st.warning(f"No LaTeX templates found in `{constants.RESUME_TEX_DIR}`.")

    if st.button("▶️ Run prompt test", type="primary", key="run_prompt_test"):
        with st.spinner("Running prompt test..."):
            if test_type == "Skills extraction + matching":
                st.session_state.prompt_test_result = {
                    "type": test_type,
                    "result": run_extraction_and_matching_preview(selected_job),
                }
            elif test_type == "Job scoring":
                st.session_state.prompt_test_result = {
                    "type": test_type,
                    "result": run_job_scoring_preview(selected_job),
                }
            elif selected_template:
                st.session_state.prompt_test_result = {
                    "type": test_type,
                    "result": run_resume_tailoring_preview(
                        selected_job, selected_template
                    ),
                }
            else:
                st.error("Select a LaTeX template before running resume tailoring.")

    saved = st.session_state.get("prompt_test_result")
    if not saved:
        return

    st.divider()
    st.markdown(f"### Last result: {saved['type']}")
    result = saved["result"]
    if saved["type"] == "Skills extraction + matching":
        _render_result_block("Skills extraction", result.get("extraction"))
        _render_result_block("Skills matching", result.get("matching"))
    elif saved["type"] == "Job scoring":
        _render_result_block("Job scoring", result)
    else:
        _render_resume_tailoring_test_result(result)


def render_user_files_tab(db: Any, jobs: list[dict[str, Any]]) -> None:
    """Render the user configuration tab."""
    st.title("⚙️ User Config")

    config_tab, prompts_tab, env_tab, testing_tab = st.tabs(
        ["Profile Files", "Pipeline Prompts", "LLM Settings", "Prompt Testing"]
    )

    with config_tab:
        _render_text_file_editor(
            title="Resume Text for LLMs",
            path=constants.RESUME_FILE,
            fallback_path="config/resume.txt.example",
            description=(
                "This plain-text resume is passed to the job scoring LLM. In case you are using a cloud model, anonymize what you do not want the model to see."
                " It is not the same as the PDF resumes in Resumes/final/, "
                "which are only used to track which resume version you submitted for applications. Changes are used the next time scoring or prompt testing runs."
            ),
            key="resume_text_editor",
            height=420,
        )
        st.divider()
        _render_text_file_editor(
            title="Candidate Skills",
            path=constants.CANDIDATE_SKILLS_FILE,
            fallback_path="config/candidate_skills.txt.example",
            description=(
                "One skill per line. Blank lines and lines starting with # are ignored. These skills are compared against skills extracted from job descriptions to do a first filtering."
            ),
            key="candidate_skills_editor",
            height=320,
        )

    with prompts_tab:
        _render_prompt_editor()

    with env_tab:
        _render_env_editor()

    with testing_tab:
        _render_prompt_testing(jobs)
