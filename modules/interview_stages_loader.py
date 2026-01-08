"""Interview stages loader for loading customizable interview stages from JSON file."""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path to import constants
sys.path.insert(0, str(Path(__file__).parent.parent))
from constants import INTERVIEW_STAGES_FILE

logger = logging.getLogger(__name__)


def load_interview_stages() -> Dict[str, Any]:
    """Load interview stages from JSON file.

    Returns:
        Dictionary containing stages list or empty dict if file not found/invalid.
    """
    try:
        with open(INTERVIEW_STAGES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

            # Validate structure
            if not isinstance(data, dict) or "stages" not in data:
                logger.error(f"{INTERVIEW_STAGES_FILE} missing 'stages' key")
                return {}

            if not isinstance(data["stages"], list):
                logger.error(f"{INTERVIEW_STAGES_FILE} 'stages' must be a list")
                return {}

            # Validate each stage has required fields
            for i, stage in enumerate(data["stages"]):
                if not isinstance(stage, dict):
                    logger.error(
                        f"{INTERVIEW_STAGES_FILE} stage {i} must be a dictionary"
                    )
                    return {}

                if "id" not in stage or "label" not in stage:
                    logger.error(
                        f"{INTERVIEW_STAGES_FILE} stage {i} missing 'id' or 'label'"
                    )
                    return {}

            return data

    except FileNotFoundError:
        logger.error(f"{INTERVIEW_STAGES_FILE} not found")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error loading {INTERVIEW_STAGES_FILE}: {e}")
        return {}


# Load stages once when module is imported
_INTERVIEW_STAGES_DATA = load_interview_stages()
_INTERVIEW_STAGES = _INTERVIEW_STAGES_DATA.get("stages", [])


def get_interview_stages() -> List[Dict[str, Any]]:
    """Get all interview stages.

    Returns:
        List of stage dictionaries sorted by order field.
    """
    # Sort by order if present, otherwise maintain original order
    return sorted(_INTERVIEW_STAGES, key=lambda x: x.get("order", 999))


def get_stage_options() -> List[str]:
    """Get list of stage IDs for use in selectbox.

    Returns:
        List of stage IDs (including empty string for "Select stage...").
    """
    return [""] + [stage["id"] for stage in get_interview_stages()]


def format_stage_option(stage_id: str) -> str:
    """Format a stage ID for display in selectbox.

    Args:
        stage_id: Stage ID to format.

    Returns:
        Formatted string for selectbox display.
    """
    if not stage_id:
        return "Select stage..."

    # Find the stage by ID
    for stage in _INTERVIEW_STAGES:
        if stage.get("id") == stage_id:
            return stage.get("label", stage_id)

    return stage_id


# Export for backward compatibility
INTERVIEW_STAGES = get_interview_stages()
