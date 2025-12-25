"""Prompt loader for loading prompts from JSON file."""

import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path to import constants
sys.path.insert(0, str(Path(__file__).parent.parent))
from constants import PROMPTS_FILE

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


# Load prompts once when module is imported
_PROMPTS = load_prompts()


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
