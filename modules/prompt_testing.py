"""Helpers for testing pipeline prompts independently of the LangGraph graph."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from constants import CANDIDATE_SKILLS_FILE, RESUME_FILE
from modules.langgraph_pipeline import (
    SkillsExtraction,
    SkillsMatch,
    build_skills_extraction_prompt,
    build_skills_matching_prompt,
    calculate_heuristic_score,
    clean_json_string,
    parse_skills_match_content,
    safe_str,
)
from modules.llm_config import get_config_manager
from modules.prompts_loader import get_prompt
from modules.resume_editing import match_edit_once
from modules.resume_redaction import build_redaction_map, redact, restore
from modules.resume_tailoring import (
    ResumeEditList,
    ResumeTailoringError,
    read_information_bank,
)
from modules.resume_templates import (
    extract_document_body,
    get_template_dir,
    read_template_tex,
)


def read_candidate_skills() -> list[str]:
    """Read candidate skills."""
    try:
        with open(CANDIDATE_SKILLS_FILE, "r", encoding="utf-8") as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except FileNotFoundError:
        return []


def read_resume() -> str:
    """Read the resume.txt file."""
    with open(RESUME_FILE, "r", encoding="utf-8") as f:
        return f.read()


def _call_chat(
    stage_name: str, messages: list[dict[str, str]], **kwargs: Any
) -> dict[str, Any]:
    config_manager = get_config_manager()
    config = config_manager.get_config_for_stage(stage_name)
    client = config_manager.get_client_for_stage(stage_name)

    if not config or not client:
        return {
            "error": f"LLM client is not configured for stage: {stage_name}",
            "stage": stage_name,
            "messages": messages,
        }

    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            **kwargs,
        )
        return {
            "stage": stage_name,
            "model": config.model,
            "messages": messages,
            "raw_output": response.choices[0].message.content or "",
        }
    except Exception as e:
        return {
            "error": str(e),
            "stage": stage_name,
            "model": config.model,
            "messages": messages,
        }


def run_skills_extraction_preview(job: dict[str, Any]) -> dict[str, Any]:
    """Render and run the skills extraction prompt for one job."""
    description = safe_str(job.get("description", ""))
    prompt = build_skills_extraction_prompt(description)
    messages = [
        {"role": "system", "content": "You are a useful assistant. Output valid JSON."},
        {"role": "user", "content": prompt},
    ]

    result = _call_chat(
        "skills_extraction",
        messages,
        temperature=0.1,
        max_tokens=10000,
        response_format={"type": "json_object"},
    )
    if result.get("error"):
        return result

    cleaned = clean_json_string(result["raw_output"])
    try:
        parsed = SkillsExtraction.model_validate_json(cleaned)
        result["parsed"] = {"skills": parsed.skills}
    except ValidationError as e:
        result["parse_error"] = str(e)
        result["parsed"] = {"skills": []}
    return result


def run_skills_matching_preview(job_skills: list[str]) -> dict[str, Any]:
    """Render and run the skills matching prompt for extracted job skills."""
    candidate_skills = read_candidate_skills()
    prompt = build_skills_matching_prompt(candidate_skills, job_skills)
    messages = [
        {"role": "system", "content": "You are a useful assistant. Output valid JSON."},
        {"role": "user", "content": prompt},
    ]

    result = _call_chat(
        "skills_matching",
        messages,
        temperature=0.1,
        max_tokens=10000,
        response_format={"type": "json_object"},
    )
    result["candidate_skills"] = candidate_skills
    result["job_skills"] = job_skills
    if result.get("error"):
        return result

    try:
        parsed = parse_skills_match_content(result["raw_output"])
    except (ValidationError, ValueError, json.JSONDecodeError) as e:
        result["parse_error"] = str(e)
        parsed = SkillsMatch(matched=[], partial=[], missing=[])

    result["parsed"] = {
        "matched": parsed.matched,
        "partial": parsed.partial,
        "missing": parsed.missing,
        "heuristic_score": calculate_heuristic_score(parsed),
    }
    return result


def run_extraction_and_matching_preview(job: dict[str, Any]) -> dict[str, Any]:
    """Run extraction then matching for one selected job."""
    extraction = run_skills_extraction_preview(job)
    skills = extraction.get("parsed", {}).get("skills", [])
    matching = run_skills_matching_preview(skills) if skills else None
    return {"extraction": extraction, "matching": matching}


def run_job_scoring_preview(job: dict[str, Any]) -> dict[str, Any]:
    """Render and run the job scoring prompt for one selected job."""
    try:
        resume = read_resume()
    except FileNotFoundError:
        return {"error": f"Resume file not found: {RESUME_FILE}"}

    user_prompt = get_prompt("JOB_SCORING_PROMPT", "").format(
        resume=resume,
        title=safe_str(job.get("title", ""), "Unknown"),
        company=safe_str(job.get("company", ""), "Unknown"),
        location=safe_str(job.get("location", ""), "Not specified"),
        description=safe_str(job.get("description", ""), "No description available"),
    )
    system_prompt = get_prompt("JOB_SCORING_SYSTEM_PROMPT", "")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    result = _call_chat(
        "job_scoring",
        messages,
        temperature=0.3,
        max_tokens=10000,
    )
    if result.get("error"):
        return result

    content = result["raw_output"]
    score = 0
    reasoning = "Unable to parse response"
    score_match = re.search(r"SCORE:\s*(\d+)", content, re.IGNORECASE)
    if score_match:
        score = max(1, min(10, int(score_match.group(1))))
    reasoning_match = re.search(
        r"REASONING:\s*(.+)", content, re.IGNORECASE | re.DOTALL
    )
    if reasoning_match:
        reasoning = reasoning_match.group(1).strip()
    result["parsed"] = {"score": score, "reasoning": reasoning}
    return result


def run_resume_tailoring_preview(
    job: dict[str, Any], template_name: str
) -> dict[str, Any]:
    """Generate and review resume tailoring edits for prompt testing only."""
    result: dict[str, Any] = {
        "stage": "resume_tailoring",
        "template": template_name,
    }

    config_manager = get_config_manager()
    config = config_manager.get_config_for_stage("resume_tailoring")
    client = config_manager.get_client_for_stage("resume_tailoring")
    if config:
        result["model"] = config.model

    try:
        if not config or not client or not config.api_key or not config.model:
            raise ResumeTailoringError(
                "Resume Tailoring LLM is not configured. Set RESUME_TAILORING_API_KEY, "
                "RESUME_TAILORING_MODEL, and RESUME_TAILORING_BASE_URL in your .env file."
            )

        source_tex = read_template_tex(template_name)
        current_resume_body = extract_document_body(source_tex)
        redaction_map = _load_template_redactions(template_name)
        redacted_body = redact(current_resume_body, redaction_map)
        user_prompt = get_prompt("RESUME_TAILORING_PROMPT", "").format(
            information_bank=read_information_bank(),
            current_resume=redacted_body,
            title=safe_str(job.get("title"), "Unknown"),
            company=safe_str(job.get("company"), "Unknown"),
            location=safe_str(job.get("location"), "Not specified"),
            description=safe_str(job.get("description"), "No description available"),
        )
        messages = [
            {
                "role": "system",
                "content": "You are a careful resume editor. Output only valid JSON.",
            },
            {"role": "user", "content": user_prompt},
        ]

        result.update(
            {
                "redacted_body": redacted_body,
                "redaction_count": len(redaction_map),
                "messages": messages,
            }
        )

        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=0.2,
            max_tokens=config.max_tokens,
        )
        raw_output = response.choices[0].message.content or ""
        result["raw_output"] = raw_output

        try:
            parsed = json.loads(clean_json_string(raw_output))
            edit_list = ResumeEditList.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            result["parse_error"] = str(exc)
            raise ResumeTailoringError(
                f"Could not parse resume tailoring JSON: {exc}",
                raw_output=raw_output,
            ) from exc

        result["parsed"] = {
            "edits": _review_tailoring_preview_edits(
                source_tex, edit_list.edits, redaction_map
            )
        }
    except ResumeTailoringError as exc:
        result["error"] = str(exc)
        if exc.raw_output:
            result["raw_output"] = exc.raw_output
    except FileNotFoundError as exc:
        result["error"] = f"Required file not found: {exc}"
    except Exception as exc:
        result["error"] = f"Unexpected resume tailoring prompt-test error: {exc}"

    return result


def _load_template_redactions(template_name: str) -> dict[str, str]:
    path = get_template_dir(template_name) / "pii_redactions.txt"
    if not path.exists():
        return {}
    return build_redaction_map(path.read_text(encoding="utf-8").splitlines())


def _review_tailoring_preview_edits(
    source_tex: str, edits: list[Any], redaction_map: dict[str, str]
) -> list[dict[str, Any]]:
    reviewed: list[dict[str, Any]] = []
    for index, edit in enumerate(edits):
        edit_data = edit.model_dump()
        restored_search = restore(edit_data.get("search", ""), redaction_map)
        restored_replacement = restore(edit_data.get("replacement", ""), redaction_map)
        match = match_edit_once(source_tex, restored_search)
        reviewed.append(
            {
                **edit_data,
                "edit_index": index,
                "restored_search": restored_search,
                "restored_replacement": restored_replacement,
                "apply_status": match.status,
                "apply_message": match.message,
                "matched_start_line": match.start_line,
                "matched_end_line": match.end_line,
            }
        )
    return reviewed
