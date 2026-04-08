"""retro-pilot configuration loader.

Reads retro-pilot.yml, substitutes ${ENV_VAR} references, validates
with Pydantic. Environment variables always override file values.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


def _substitute_env(text: str) -> str:
    """Replace ${VAR_NAME} with os.environ.get(VAR_NAME, '')."""
    return re.sub(
        r"\$\{([^}]+)\}",
        lambda m: os.environ.get(m.group(1), ""),
        text,
    )


class LLMConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_tokens: int = Field(default=4096, ge=256)
    max_turns: int = Field(default=10, ge=1)


class EvaluatorConfig(BaseModel):
    pass_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    max_revision_cycles: int = Field(default=3, ge=1)


class RetroPilotConfig(BaseModel):
    tenant_id: str = "default"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    evaluator: EvaluatorConfig = Field(default_factory=EvaluatorConfig)
    demo_mode: bool = False
    chroma_db_path: str = "./chroma_db"
    postmortems_path: str = "./postmortems"


def load_config(path: str | Path = "retro-pilot.yml") -> RetroPilotConfig:
    p = Path(path)
    if not p.exists():
        return RetroPilotConfig()
    raw = _substitute_env(p.read_text())
    data = yaml.safe_load(raw) or {}
    return RetroPilotConfig(**data)
