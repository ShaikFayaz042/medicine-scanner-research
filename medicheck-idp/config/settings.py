"""Runtime settings from environment variables (see .env.example).

Only stage 5 (classifier) settings are defined so far; other stages add their own section.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _flag(name: str, default: bool) -> bool:
    value = _env(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ClassifierSettings:
    rules_dir: Optional[Path] = None             # IDP_RULES_DIR; default: medicheck-idp/rules
    llm_provider: str = "none"                   # IDP_LLM_PROVIDER: none | bedrock | gemini | package.module:Class
    llm_model: Optional[str] = None              # IDP_LLM_MODEL: model or inference-profile ID
    llm_region: Optional[str] = None             # IDP_LLM_REGION (Bedrock); falls back to AWS_REGION
    llm_structured_output: bool = True           # IDP_LLM_STRUCTURED_OUTPUT: ask the provider to enforce the schema
    llm_timeout_seconds: int = 120               # IDP_LLM_TIMEOUT_SECONDS
    llm_cache_dir: Optional[Path] = None         # IDP_LLM_CACHE_DIR: reuse answers across runs
    gemini_api_key: Optional[str] = None         # GEMINI_API_KEY (gemini provider only)

    @classmethod
    def from_env(cls) -> "ClassifierSettings":
        rules_dir = _env("IDP_RULES_DIR")
        cache_dir = _env("IDP_LLM_CACHE_DIR")
        return cls(
            rules_dir=Path(rules_dir) if rules_dir else None,
            llm_provider=_env("IDP_LLM_PROVIDER", "none") or "none",
            llm_model=_env("IDP_LLM_MODEL"),
            llm_region=_env("IDP_LLM_REGION", _env("AWS_REGION")),
            llm_structured_output=_flag("IDP_LLM_STRUCTURED_OUTPUT", True),
            llm_timeout_seconds=int(_env("IDP_LLM_TIMEOUT_SECONDS", "120") or 120),
            llm_cache_dir=Path(cache_dir) if cache_dir else None,
            gemini_api_key=_env("GEMINI_API_KEY"),
        )

    def provider_options(self) -> Dict[str, Any]:
        """Keyword arguments for idp.models.llm.create_provider, per provider."""
        provider = self.llm_provider.lower()
        if provider == "bedrock":
            return {"region": self.llm_region, "structured_output": self.llm_structured_output,
                    "timeout_seconds": self.llm_timeout_seconds}
        if provider == "gemini":
            return {"api_key": self.gemini_api_key}
        return {}
