"""LLM-backed resume tailoring edit generation."""

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from constants import RESUME_FILE
from modules.langgraph_pipeline import clean_json_string, safe_str
from modules.llm_config import get_config_manager
from modules.prompts_loader import RESUME_TAILORING_PROMPT


class ResumeEdit(BaseModel):
    """One deterministic search/replacement edit proposed by the LLM."""

    search: str = Field(min_length=1)
    replacement: str = Field(min_length=1)
    reason: str = Field(default="")


class ResumeEditList(BaseModel):
    """Validated LLM response for resume tailoring."""

    edits: list[ResumeEdit]


class ResumeTailoringError(Exception):
    """Raised when tailoring edit generation fails."""

    def __init__(self, message: str, raw_output: str | None = None):
        super().__init__(message)
        self.raw_output = raw_output


def read_information_bank() -> str:
    """Read required plain-text resume information bank."""
    with open(RESUME_FILE, "r", encoding="utf-8") as f:
        return f.read()


def generate_tailoring_edits(
    job: dict[str, Any], current_resume_body: str
) -> list[ResumeEdit]:
    """Generate resume tailoring edits with a single plain LLM call."""
    if not RESUME_TAILORING_PROMPT:
        raise ResumeTailoringError(
            "resume_tailoring prompt is missing from config/prompts.json."
        )

    config_manager = get_config_manager()
    config = config_manager.get_config_for_stage("resume_tailoring")
    client = config_manager.get_client_for_stage("resume_tailoring")

    if (
        not config
        or not client
        or not config.api_key
        or not config.model
        or not config.base_url
    ):
        raise ResumeTailoringError(
            "Resume Tailoring LLM is not configured. Set RESUME_TAILORING_API_KEY, "
            "RESUME_TAILORING_MODEL, and RESUME_TAILORING_BASE_URL in your .env file."
        )

    information_bank = read_information_bank()
    prompt = RESUME_TAILORING_PROMPT.format(
        information_bank=information_bank,
        current_resume=current_resume_body,
        title=safe_str(job.get("title"), "Unknown"),
        company=safe_str(job.get("company"), "Unknown"),
        location=safe_str(job.get("location"), "Not specified"),
        description=safe_str(job.get("description"), "No description available"),
    )

    response = client.chat.completions.create(
        model=config.model,
        messages=[
            {
                "role": "system",
                "content": "You are a careful resume editor. Output only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=config.max_tokens,
    )

    raw_output = response.choices[0].message.content or ""
    cleaned = clean_json_string(raw_output)

    try:
        parsed = json.loads(cleaned)
        edit_list = ResumeEditList.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ResumeTailoringError(
            f"Could not parse resume tailoring JSON: {exc}", raw_output=raw_output
        ) from exc

    return edit_list.edits
