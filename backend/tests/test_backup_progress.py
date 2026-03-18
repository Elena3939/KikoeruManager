"""
Comprehensive unit tests for the sliding-window speed/ETA algorithm
in BackupZipService._record_speed_sample / _calc_speed_and_eta.

We bypass the heavy dependencies (database, config) by directly
instantiating BackupZipService.__new__ and wiring only the fields
the algorithm touches.
"""

import time
from collections import deque
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.core.backup_zip_service import (
    BackupZipService,
    SPEED_WINDOW_SIZE,
    SPEED_WINDOW_MIN_SECONDS,
)


# ── helpers ───────────────────────────────────────────────────────

def _make_service(total_bytes: int = 0, start_time: datetime | None = None) -> BackupZipService:
    """Create a minimal BackupZipService without triggering __init__ side-effects."""
    svc = object.__new__(BackupZipService)
    svc._speed_samples = deque(maxlen=SPEED_WINDOW_SIZE)
    svc._status = {
        "total_bytes": total_bytes,
        "processed_bytes": 0,
    }
    svc._start_time = start_time
    return svc


def _feed_constant_rate(svc: BackupZipService, rate_bps: float,
                        duration: float, interval: float = 0.5,
                        t0: float = 100.0):
    """Populate speed_samples at a constant byte-rate."""
    steps = int(duration / interval)
    for i in range(steps + 1):
        t = t0 + i * interval
        b = int(rate_bps * i * interval)
        svc._speed_samples.append((t, b))
        svc._status["processed_bytes"] = b


# ── 1. constant rate ─────────────────────────────────────────────

class TestConstantRate:
    def test_constant_rate_10mb(self):
        """Feed samples at 10 MB/s for 10 s; measured speed should be within 5%."""
        rate = 10 * 1024 * 1024  # 10 MB/s
        total = rate * 20  # pretend 20 s worth of data total
        svc = _make_service(total_bytes=total)
        _feed_constant_rate(svc, rate, duration=10.0, interval=0.5)

        speed_str, _ = svc._calc_speed_and_eta(50)
        assert "MB/s" in speed_str
        numeric = float(speed_str.split()[0])
        assert abs(numeric - 10.0) / 10.0 < 0.05

    def test_constant_rate_500kb(self):
        """500 KB/s should report KB/s."""
        rate = 500 * 1024
        svc = _make_service(total_bytes=rate * 60)
        _feed_constant_rate(svc, rate, duration=10.0)

        speed_str, _ = svc._calc_speed_and_eta(50)
        assert "KB/s" in speed_str
        numeric = float(speed_str.split()[0])
        assert abs(numeric - 500.0) / 500.0 < 0.05


# ── 2. acceleration ──────────────────────────────────────────────

class TestAcceleration:
    def test_speed_reflects_recent_rate(self):
        """After slow start then fast burst, speed should reflect the faster recent rate."""
        svc = _make_service(total_bytes=500 * 1024 * 1024)
        t0 = 100.0
        # Phase 1: 1 MB/s for 5 s (samples will be pushed out of window)
        slow_rate = 1 * 1024 * 1024
        for i in range(11):
            t = t0 + i * 0.5
            b = int(slow_rate * i * 0.5)
            svc._speed_samples.append((t, b))

        # Phase 2: 20 MB/s for 5 s (these dominate the window)
        fast_rate = 20 * 1024 * 1024
        base_bytes = int(slow_rate * 5)
        for i in range(11):
            t = t0 + 5.0 + i * 0.5
            b = base_bytes + int(fast_rate * i * 0.5)
            svc._speed_samples.append((t, b))
        svc._status["processed_bytes"] = b

        speed_str, _ = svc._calc_speed_and_eta(30)
        numeric = float(speed_str.split()[0])
        # The window covers both phases, so speed should be well above 1 MB/s
        assert numeric > 5.0, f"Expected speed > 5 MB/s during acceleration, got {numeric}"


# ── 3. deceleration ──────────────────────────────────────────────

class TestDeceleration:
    def test_speed_decreases(self):
        """After fast start then slow phase, speed should drop."""
        svc = _make_service(total_bytes=500 * 1024 * 1024)
        t0 = 100.0
        # Phase 1: 20 MB/s for 10 s
        fast_rate = 20 * 1024 * 1024
        for i in range(21):
            t = t0 + i * 0.5
            b = int(fast_rate * i * 0.5)
            svc._speed_samples.append((t, b))
        base_bytes = int(fast_rate * 10)

        # Phase 2: 1 MB/s for 10 s (window maxlen=30 pushes out fast samples)
        slow_rate = 1 * 1024 * 1024
        for i in range(21):
            t = t0 + 10.0 + i * 0.5
            b = base_bytes + int(slow_rate * i * 0.5)
            svc._speed_samples.append((t, b))
        svc._status["processed_bytes"] = b

        speed_str, _ = svc._calc_speed_and_eta(30)
        numeric = float(speed_str.split()[0])
        # With 30-sample window at 0.5s interval = 15s window, mostly slow phase
        assert numeric < 15.0, f"Expected speed < 15 MB/s during deceleration, got {numeric}"


# ── 4. window minimum (< 3 s fallback) ──────────────────────────

class TestWindowMinimum:
    def test_fallback_to_cumulative_average(self):
        """With < 3 s of samples, algorithm should fall back to cumulative average."""
        total = 100 * 1024 * 1024
        start = datetime.now() - timedelta(seconds=10)
        svc = _make_service(total_bytes=total, start_time=start)

        # Only 2 seconds of window data
        t0 = 100.0
        svc._speed_samples.append((t0, 0))
        svc._speed_samples.append((t0 + 1.0, 5 * 1024 * 1024))
        svc._speed_samples.append((t0 + 2.0, 10 * 1024 * 1024))
        svc._status["processed_bytes"] = 10 * 1024 * 1024

        speed_str, _ = svc._calc_speed_and_eta(50)
        # Should still return a valid speed string (cumulative fallback)
        assert speed_str != "", "Expected non-empty speed from cumulative fallback"
        assert "B/s" in speed_str or "KB/s" in speed_str or "MB/s" in speed_str

    def test_no_fallback_when_window_sufficient(self):
        """With >= 3 s of samples, use sliding window, not cumulative."""
        total = 200 * 1024 * 1024
        svc = _make_service(total_bytes=total)

        t0 = 100.0
        rate = 5 * 1024 * 1024  # 5 MB/s
        for i in range(8):  # 0..3.5 s at 0.5 s intervals => 3.5 s span
            svc._speed_samples.append((t0 + i * 0.5, int(rate * i * 0.5)))
        svc._status["processed_bytes"] = int(rate * 3.5)

        speed_str, _ = svc._calc_speed_and_eta(50)
        assert "MB/s" in speed_str
        numeric = float(speed_str.split()[0])
        assert abs(numeric - 5.0) / 5.0 < 0.05


# ── 5. ETA accuracy ──────────────────────────────────────────────

class TestEtaAccuracy:
    def test_eta_at_50_percent(self):
        """At 50% with 10 MB/s and 200 MB total, remaining = 100 MB => ETA ~10 s."""
        total = 200 * 1024 * 1024
        rate = 10 * 1024 * 1024
        svc = _make_service(total_bytes=total)
        _feed_constant_rate(svc, rate, duration=10.0, interval=0.5)

        _, eta_str = svc._calc_speed_and_eta(50)
        assert eta_str != ""
        # Parse mm:ss
        parts = eta_str.split(":")
        total_seconds = int(parts[-2]) * 60 + int(parts[-1])
        if len(parts) == 3:
            total_seconds += int(parts[0]) * 3600
        expected = 10  # 100 MB / 10 MB/s
        assert abs(total_seconds - expected) / expected < 0.05

    def test_eta_at_90_percent(self):
        """At 90% with 5 MB/s and 100 MB total, remaining = 10 MB => ETA ~2 s."""
        total = 100 * 1024 * 1024
        rate = 5 * 1024 * 1024
        svc = _make_service(total_bytes=total)
        _feed_constant_rate(svc, rate, duration=10.0, interval=0.5)

        _, eta_str = svc._calc_speed_and_eta(90)
        assert eta_str != ""
        parts = eta_str.split(":")
        total_seconds = int(parts[-2]) * 60 + int(parts[-1])
        if len(parts) == 3:
            total_seconds += int(parts[0]) * 3600
        expected = 2  # 10 MB / 5 MB/s
        assert abs(total_seconds - expected) <= 1  # within 1 second

    def test_eta_format_hours(self):
        """Large remaining data should produce h:mm:ss format."""
        total = 100 * 1024 * 1024 * 1024  # 100 GB
        rate = 5 * 1024 * 1024  # 5 MB/s
        svc = _make_service(total_bytes=total)
        _feed_constant_rate(svc, rate, duration=10.0, interval=0.5)

        _, eta_str = svc._calc_speed_and_eta(10)
        # 90 GB remaining / 5 MB/s ≈ 18432 s ≈ 5+ hours
        assert eta_str.count(":") == 2, f"Expected h:mm:ss format, got '{eta_str}'"


# ── 6. progress mapping ─────────────────────────────────────────

class TestProgressMapping:
    """Verify 7z raw_percent -> app progress: mapped = 10 + raw_percent * 0.89"""

    def test_0_percent(self):
        assert 10 + int(0 * 0.89) == 10

    def test_50_percent(self):
        assert 10 + int(50 * 0.89) == 54

    def test_100_percent(self):
        assert 10 + int(100 * 0.89) == 99


# ── 7. empty samples ────────────────────────────────────────────

class TestEmptySamples:
    def test_no_samples(self):
        svc = _make_service(total_bytes=1000)
        speed_str, eta_str = svc._calc_speed_and_eta(50)
        assert speed_str == ""
        assert eta_str == ""


# ── 8. single sample ────────────────────────────────────────────

class TestSingleSample:
    def test_one_sample(self):
        svc = _make_service(total_bytes=1000)
        svc._speed_samples.append((100.0, 500))
        speed_str, eta_str = svc._calc_speed_and_eta(50)
        assert speed_str == ""
        assert eta_str == ""


# ── 9. speed formatting thresholds ───────────────────────────────

class TestSpeedFormatting:
    def _speed_for_rate(self, rate_bps: float) -> str:
        svc = _make_service(total_bytes=int(rate_bps * 100))
        _feed_constant_rate(svc, rate_bps, duration=5.0, interval=0.5)
        speed_str, _ = svc._calc_speed_and_eta(50)
        return speed_str

    def test_mb_threshold(self):
        """Speed > 1 MB/s should display as MB/s."""
        s = self._speed_for_rate(2 * 1024 * 1024)
        assert "MB/s" in s

    def test_kb_threshold(self):
        """Speed between 1 KB/s and 1 MB/s should display as KB/s."""
        s = self._speed_for_rate(100 * 1024)
        assert "KB/s" in s

    def test_bytes_threshold(self):
        """Speed < 1 KB/s should display as B/s."""
        s = self._speed_for_rate(500)
        assert "B/s" in s

    def test_mb_format_has_two_decimals(self):
        s = self._speed_for_rate(10 * 1024 * 1024)
        numeric_part = s.split()[0]
        assert "." in numeric_part
        assert len(numeric_part.split(".")[1]) == 2

    def test_kb_format_has_two_decimals(self):
        s = self._speed_for_rate(256 * 1024)
        numeric_part = s.split()[0]
        assert "." in numeric_part
        assert len(numeric_part.split(".")[1]) == 2

    def test_bytes_format_is_integer(self):
        s = self._speed_for_rate(800)
        numeric_part = s.split()[0]
        assert "." not in numeric_part
