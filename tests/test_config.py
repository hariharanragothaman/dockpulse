"""Tests for configuration and utility functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from dockpulse.config import Config, format_bytes, format_duration, parse_duration


class TestParseDuration:
    """Verify human-readable duration parsing."""

    def test_parse_duration_hours(self) -> None:
        assert parse_duration("1h") == 3600

    def test_parse_duration_minutes(self) -> None:
        assert parse_duration("30m") == 1800

    def test_parse_duration_compound(self) -> None:
        assert parse_duration("1h30m") == 5400

    def test_parse_duration_days(self) -> None:
        assert parse_duration("1d") == 86400

    def test_parse_duration_seconds(self) -> None:
        assert parse_duration("90s") == 90

    def test_parse_duration_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")


class TestFormatDuration:
    """Verify seconds-to-human conversion."""

    def test_format_duration_hours(self) -> None:
        assert format_duration(3600) == "1h"

    def test_format_duration_compound(self) -> None:
        assert format_duration(5400) == "1h30m"

    def test_format_duration_days(self) -> None:
        assert format_duration(86400) == "1d"


class TestFormatBytes:
    """Verify megabyte formatting."""

    def test_format_bytes_kb(self) -> None:
        result = format_bytes(0.5)
        assert "512" in result
        assert "KB" in result

    def test_format_bytes_mb(self) -> None:
        result = format_bytes(256.0)
        assert "256" in result
        assert "MB" in result

    def test_format_bytes_gb(self) -> None:
        result = format_bytes(2048.0)
        assert "2.0" in result
        assert "GB" in result


class TestConfig:
    """Verify Config dataclass defaults and properties."""

    def test_config_defaults(self) -> None:
        cfg = Config()
        assert cfg.sample_interval_seconds == 1.0
        assert cfg.default_profile_duration == "1h"
        assert cfg.headroom_percent == 20.0
        assert cfg.percentiles == (50, 95, 99)
        assert cfg.output_format == "rich"
        assert cfg.db_path == "~/.dockpulse/profiles.db"

    def test_resolved_db_path(self) -> None:
        cfg = Config()
        resolved = cfg.resolved_db_path
        assert isinstance(resolved, Path)
        assert "~" not in str(resolved)
        assert str(resolved).endswith(".dockpulse/profiles.db")
