"""
LLM Configuration Manager with per-stage configuration
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from openai import OpenAI
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class StageConfig:
    """Configuration for a specific LLM stage"""

    stage_name: str
    api_key: str
    base_url: Optional[str] = None
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 2000

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            "stage_name": self.stage_name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StageConfig":
        """Create config from dictionary"""
        return cls(
            stage_name=data.get("stage_name", ""),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url"),
            model=data.get("model", "gpt-4o-mini"),
            temperature=data.get("temperature", 0.3),
            max_tokens=data.get("max_tokens", 2000),
        )


class LLMConfigManager:
    """Manages per-stage LLM configurations for the application"""

    def __init__(self):
        load_dotenv()
        self.stages = ["skills_extraction", "skills_matching", "job_scoring", "chat"]

        # Load configurations for all stages
        self.stage_configs: Dict[str, StageConfig] = {}
        for stage in self.stages:
            self.stage_configs[stage] = self._load_stage_config(stage)

    def _load_stage_config(self, stage_name: str) -> StageConfig:
        """Load configuration for a specific stage from environment variables"""
        # Convert stage name to uppercase with underscores for env var names
        env_prefix = stage_name.upper()

        # Read from .env file using pattern: {STAGE}_API_KEY, {STAGE}_BASE_URL, {STAGE}_MODEL
        api_key = os.getenv(f"{env_prefix}_API_KEY", "")
        base_url = os.getenv(f"{env_prefix}_BASE_URL") or None
        model = os.getenv(f"{env_prefix}_MODEL", "gpt-4o-mini")

        # Set appropriate temperature defaults
        temperature = 0.3  # Default for analytical tasks
        if stage_name == "chat":
            temperature = 0.7  # Higher for conversational tasks

        return StageConfig(
            stage_name=stage_name,
            api_key=api_key or "",
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=2000,
        )

    def get_client_for_stage(self, stage_name: str) -> Optional[OpenAI]:
        """
        Get OpenAI client for a specific stage

        Args:
            stage_name: One of the stage names (skills_extraction, skills_matching, job_scoring, chat)

        Returns:
            OpenAI client or None if configuration is missing
        """
        if stage_name not in self.stage_configs:
            logger.error(f"Unknown stage: {stage_name}")
            return None

        config = self.stage_configs[stage_name]

        # Check if we have the necessary configuration
        if not config.api_key:
            logger.error(f"No API key configured for stage: {stage_name}")
            return None

        try:
            client_kwargs = {"api_key": config.api_key}
            if config.base_url:
                client_kwargs["base_url"] = config.base_url

            return OpenAI(**client_kwargs)
        except Exception as e:
            logger.error(f"Error creating client for stage {stage_name}: {e}")
            return None

    def get_config_for_stage(self, stage_name: str) -> Optional[StageConfig]:
        """Get configuration for a specific stage"""
        return self.stage_configs.get(stage_name)

    def test_stage_connection(self, stage_name: str) -> tuple[bool, str]:
        """Test connection for a specific stage"""
        client = self.get_client_for_stage(stage_name)
        if not client:
            return (
                False,
                f"No client available for stage: {stage_name}. Check your .env file.",
            )

        config = self.get_config_for_stage(stage_name)
        if not config:
            return False, f"No configuration found for stage: {stage_name}"

        try:
            # Simple test call
            response = client.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": "Say 'test successful'"}],
                max_tokens=10,
                temperature=config.temperature,
            )
            if response.choices:
                return True, f"{stage_name} ({config.model}) connection successful"
            return False, f"No response from {stage_name}"
        except Exception as e:
            return False, f"{stage_name} connection failed: {str(e)}"

    def get_config_summary(self) -> Dict[str, Any]:
        """Get summary of all stage configurations"""
        summary = {}
        for stage_name, config in self.stage_configs.items():
            summary[stage_name] = {
                "has_api_key": bool(config.api_key),
                "model": config.model,
                "base_url": config.base_url or "default OpenAI",
                "temperature": config.temperature,
                "configured": bool(config.api_key),
            }

        return summary


# Singleton instance
_config_manager: Optional[LLMConfigManager] = None


def get_config_manager() -> LLMConfigManager:
    """Get singleton instance of LLMConfigManager"""
    global _config_manager
    if _config_manager is None:
        _config_manager = LLMConfigManager()
    return _config_manager
