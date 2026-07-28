"""Prompt loader for loading prompts from JSON file."""

import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path to import constants
sys.path.insert(0, str(Path(__file__).parent.parent))
from constants import PROMPTS_FILE

PROMPTS_EXAMPLE_FILE = f"{PROMPTS_FILE}.example"

logger = logging.getLogger(__name__)


def load_prompts() -> dict[str, Any]:
    """Load all prompts from JSON file.

    Returns:
        Dictionary of prompts or empty dict if file not found/invalid.
    """
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"{PROMPTS_FILE} not found, returning empty prompts")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error loading {PROMPTS_FILE}: {e}")
        return {}


def ensure_prompt_defaults() -> list[str]:
    """Merge missing prompt keys from the tracked example into user prompts.

    Existing user prompt values are never overwritten. The returned list contains
    keys that were added to ``PROMPTS_FILE``.
    """
    prompts_path = Path(PROMPTS_FILE)
    example_path = Path(PROMPTS_EXAMPLE_FILE)
    if not prompts_path.exists() or not example_path.exists():
        return []

    try:
        user_prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
        default_prompts = json.loads(example_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error(f"Could not merge prompt defaults due to invalid JSON: {exc}")
        return []

    if not isinstance(user_prompts, dict) or not isinstance(default_prompts, dict):
        logger.error(
            "Could not merge prompt defaults: prompt files must contain JSON objects"
        )
        return []

    added_keys = [key for key in default_prompts if key not in user_prompts]
    if not added_keys:
        return []

    for key in added_keys:
        user_prompts[key] = default_prompts[key]
    prompts_path.write_text(
        json.dumps(user_prompts, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return added_keys


# Load prompts once when module is imported. They can be refreshed from the
# Streamlit configuration UI after prompts.json is saved.
_PROMPTS = load_prompts()


def reload_prompts() -> dict[str, Any]:
    """Reload prompt cache from disk and return the fresh prompt mapping."""
    global _PROMPTS
    _PROMPTS = load_prompts()
    return _PROMPTS


def get_prompt(name: str, default: str = "") -> str:
    """Get a prompt by name.

    Args:
        name: Prompt name.
        default: Default value if prompt not found.

    Returns:
        Prompt text or default value.
    """
    return _PROMPTS.get(name, default)


# Export all prompts as module attributes for backward compatibility
SKILLS_EXTRACTION_PROMPT = get_prompt("SKILLS_EXTRACTION_PROMPT", "")
SKILLS_MATCHING_PROMPT = get_prompt("SKILLS_MATCHING_PROMPT", "")
JOB_SCORING_PROMPT = get_prompt("JOB_SCORING_PROMPT", "")
JOB_SCORING_SYSTEM_PROMPT = get_prompt("JOB_SCORING_SYSTEM_PROMPT", "")
RESUME_TAILORING_PROMPT = get_prompt("RESUME_TAILORING_PROMPT", "")
