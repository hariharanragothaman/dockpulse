"""Tests for dashboard helper functions (sparkline and usage bar)."""

from __future__ import annotations

from rich.text import Text

from dockpulse.dashboard import _sparkline, _usage_bar


class TestSparkline:
    """Verify sparkline rendering logic."""

    def test_sparkline_empty(self) -> None:
        result = _sparkline([])
        assert result == " " * 12

    def test_sparkline_uniform(self) -> None:
        result = _sparkline([50.0] * 10)
        assert len(result) == 10
        assert len(set(result)) == 1

    def test_sparkline_ascending(self) -> None:
        result = _sparkline([1.0, 2.0, 3.0, 4.0, 5.0])
        assert len(result) == 5
        assert result[0] != result[-1]
        assert result[-1] > result[0]


class TestUsageBar:
    """Verify coloured usage bar rendering."""

    def test_usage_bar_low(self) -> None:
        bar = _usage_bar(20.0)
        assert isinstance(bar, Text)
        plain = bar.plain
        assert "20.0%" in plain
        spans = bar._spans
        assert any(s.style == "green" for s in spans)

    def test_usage_bar_high(self) -> None:
        bar = _usage_bar(90.0)
        assert isinstance(bar, Text)
        plain = bar.plain
        assert "90.0%" in plain
        spans = bar._spans
        assert any(s.style == "red" for s in spans)
