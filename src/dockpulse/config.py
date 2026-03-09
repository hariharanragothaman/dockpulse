"""Configuration and utility functions for DockPulse."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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
