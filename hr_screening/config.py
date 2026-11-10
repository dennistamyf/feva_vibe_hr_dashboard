"""Project paths and private provider configuration.

The provider key is read from the process environment or an ignored local
``.env`` file. It is never printed, logged, written to output, or sent to the
model. Only the non-secret model handle is displayed in the UI and scoring
sheet header.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .errors import MissingProviderConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "HR_dummy_data"
OUTPUT_ROOT = DATA_ROOT / "output"
ENV_FILE = PROJECT_ROOT / ".env"

_KEY_NAME = "OPENROUTER_API_KEY"
_MODEL_NAME = "OPENROUTER_MODEL"


@dataclass(frozen=True)
class Settings:
    """Validated provider settings. The API key is excluded from repr."""

    api_key: str = field(repr=False)
    model: str

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_key.strip():
            raise MissingProviderConfig(
                "Provider not configured. Missing setting: OPENROUTER_API_KEY. "
                "No model request was made."
            )
        if not self.model or not self.model.strip():
            raise MissingProviderConfig(
                "Provider not configured. Missing setting: OPENROUTER_MODEL. "
                "No model request was made."
            )


@dataclass(frozen=True)
class ProviderStatus:
    configured: bool
    model_handle: str | None
    safe_message: str


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines without evaluating shell syntax."""

    values: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _merged_env(
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> dict[str, str]:
    """Return process env overlaid on the optional local .env file.

    Existing process values win over file values, which keeps an
    instructor-managed environment authoritative.
    """

    merged: dict[str, str] = {}
    file_path = ENV_FILE if env_file is None else Path(env_file)
    if file_path.exists():
        merged.update(_parse_env_file(file_path))
    source = os.environ if env is None else env
    merged.update({str(k): str(v) for k, v in source.items()})
    return merged


def load_settings(
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> Settings:
    """Load and validate provider settings.

    Raises:
        MissingProviderConfig: when either required setting is empty.
    """

    merged = _merged_env(env=env, env_file=env_file)
    api_key = merged.get(_KEY_NAME, "").strip()
    model = merged.get(_MODEL_NAME, "").strip()

    missing = []
    if not api_key:
        missing.append(_KEY_NAME)
    if not model:
        missing.append(_MODEL_NAME)
    if missing:
        names = ", ".join(missing)
        raise MissingProviderConfig(
            f"Provider not configured. Missing setting(s): {names}. "
            "See .env.example and ask the instructor to configure them privately. "
            "No model request was made."
        )

    return Settings(api_key=api_key, model=model)


def provider_status(
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> ProviderStatus:
    """Return a safe UI status without ever exposing the key."""

    try:
        settings = load_settings(env=env, env_file=env_file)
    except MissingProviderConfig as exc:
        return ProviderStatus(
            configured=False,
            model_handle=None,
            safe_message=str(exc),
        )
    return ProviderStatus(
        configured=True,
        model_handle=settings.model,
        safe_message="Provider configuration is present. The key is never displayed.",
    )
