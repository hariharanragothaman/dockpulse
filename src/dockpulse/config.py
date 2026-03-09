"""Configuration and utility functions for DockPulse."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_DURATION_PATTERN = re.compile(
    r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$",
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3_600,
    "d": 86_400,
}


def parse_duration(value: str) -> int:
    """Parse a human-readable duration string into seconds.

    Supports compound durations like ``1d12h``, ``2h30m``, or simple forms
    like ``1h``, ``30m``, ``90s``.

    Raises:
        ValueError: If the string does not match a recognised duration format.
    """
    value = value.strip()

    # Fast path: single-unit shorthand (e.g. "1h", "30m")
    if len(value) >= 2 and value[-1].lower() in _UNIT_SECONDS and value[:-1].isdigit():
        return int(value[:-1]) * _UNIT_SECONDS[value[-1].lower()]

    match = _DURATION_PATTERN.match(value)
    if not match or not any(match.groups()):
        raise ValueError(
            f"Invalid duration '{value}'. Use formats like '1h', '30m', '1d12h', '90s'."
        )

    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


@dataclass(slots=True)
class Config:
    """Runtime configuration for DockPulse."""

    sample_interval_seconds: float = 1.0
    default_profile_duration: str = "1h"
    headroom_percent: float = 20.0
    percentiles: tuple[int, ...] = (50, 95, 99)
    output_format: str = "rich"
    db_path: str = "~/.dockpulse/profiles.db"

    @property
    def resolved_db_path(self) -> Path:
        """Return the database path with ``~`` expanded."""
        return Path(self.db_path).expanduser()

    @property
    def default_duration_seconds(self) -> int:
        return parse_duration(self.default_profile_duration)


def load_config(config_path: str | None = None) -> Config:
    """Load configuration from a YAML file, falling back to defaults.

    Looks for config in this order:
    1. Explicit path if provided
    2. .dockpulse.yml in current directory
    3. ~/.dockpulse/config.yml
    4. Default Config()
    """
    paths_to_try: list[Path] = []
    if config_path:
        paths_to_try.append(Path(config_path).expanduser())
    paths_to_try.append(Path.cwd() / ".dockpulse.yml")
    paths_to_try.append(Path.home() / ".dockpulse" / "config.yml")

    for path in paths_to_try:
        if path.exists() and path.is_file():
            try:
                yaml = YAML()
                with open(path) as f:
                    data: dict[str, Any] | None = yaml.load(f)
                if not data:
                    return Config()
                return Config(
                    sample_interval_seconds=float(data.get("sample_interval_seconds", 1.0)),
                    default_profile_duration=str(data.get("default_profile_duration", "1h")),
                    headroom_percent=float(data.get("headroom_percent", 20.0)),
                    percentiles=tuple(int(p) for p in data.get("percentiles", [50, 95, 99])),
                    output_format=str(data.get("output_format", "rich")),
                    db_path=str(data.get("db_path", "~/.dockpulse/profiles.db")),
                )
            except (OSError, ValueError, TypeError):
                pass
    return Config()


def format_duration(seconds: int) -> str:
    """Convert seconds to human-readable duration string.

    Examples: 3600 -> "1h", 5400 -> "1h30m", 86400 -> "1d"
    """
    parts: list[str] = []
    if seconds >= 86_400:
        d = seconds // 86_400
        parts.append(f"{d}d")
        seconds %= 86_400
    if seconds >= 3_600:
        h = seconds // 3_600
        parts.append(f"{h}h")
        seconds %= 3_600
    if seconds >= 60:
        m = seconds // 60
        parts.append(f"{m}m")
        seconds %= 60
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    return "".join(parts)


def format_bytes(mb: float) -> str:
    """Format megabytes into human-readable form.

    Examples: 0.5 -> "512 KB", 256.0 -> "256 MB", 2048.0 -> "2.0 GB"
    """
    if mb < 1:
        kb = mb * 1024
        return f"{kb:.0f} KB" if kb == int(kb) else f"{kb:.1f} KB"
    elif mb < 1024:
        return f"{mb:.0f} MB" if mb == int(mb) else f"{mb:.1f} MB"
    else:
        gb = mb / 1024
        return f"{gb:.1f} GB"
