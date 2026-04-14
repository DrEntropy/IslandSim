"""Operational configuration (models, retries, defaults).

Loaded from ``config.yaml`` at the project root. Falls back to sensible
defaults when the file is missing.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ModelConfig(BaseModel):
    country: str = "openrouter:anthropic/claude-haiku-4.5"
    facilitator: str = "openrouter:anthropic/claude-sonnet-4-6"


class OperationalConfig(BaseModel):
    models: ModelConfig = ModelConfig()
    retries: int = 2
    default_turns: int = 4
    langfuse: bool = True


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_settings() -> OperationalConfig:
    """Load operational config from ``config.yaml``, or use defaults."""
    path = _PROJECT_ROOT / "config.yaml"
    if not path.exists():
        return OperationalConfig()
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return OperationalConfig()
    return OperationalConfig.model_validate(data)
