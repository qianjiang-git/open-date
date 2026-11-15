"""Per-band RSSI filter: 5-second rolling median, then EMA (alpha 0.3), once a second.

The hub only smooths and timestamps. Zones are decided by the server from these
timestamped values, so the hub never claims "close" on its own.
"""
from __future__ import annotations

import statistics
import time
from collections import deque


class BandFilter:
    def __init__(self, window_s: float = 5.0, alpha: float = 0.3, min_samples: int = 3, stale_s: float = 8.0):
        self.window_s, self.alpha, self.min_samples, self.stale_s = window_s, alpha, min_samples, stale_s
        self.samples: deque = deque(maxlen=200)      # (monotonic time, rssi)
        self.ema: float | None = None
        self.sequence = 0

    def add(self, rssi: float, at: float | None = None) -> None:
        at = time.monotonic() if at is None else at
        if self.samples and at - self.samples[-1][0] > self.stale_s:
            self.ema = None                          # stale gap: clear the filter
        self.samples.append((at, float(rssi)))

    def observation(self, band_number: int, now: float | None = None) -> dict | None:
        """The current smoothed observation, or None with fewer than min_samples fresh samples."""
        now = time.monotonic() if now is None else now
        recent = [r for t, r in self.samples if now - t <= self.window_s]
        if len(recent) < self.min_samples:
            if self.samples and now - self.samples[-1][0] > self.stale_s:
                self.ema = None
            return None
        median = statistics.median(recent)
        self.ema = median if self.ema is None else self.alpha * median + (1 - self.alpha) * self.ema
        self.sequence += 1
        newest = self.samples[-1][0]
        return {"target_band_number": band_number, "source": "real_beacon", "sequence": self.sequence,
                "rssi_dbm": round(self.ema, 1), "samples": len(recent), "window_seconds": self.window_s,
                "sample_age_ms": max(0, int((now - newest) * 1000))}


class Proximity:
    def __init__(self, own_number: int, roster: set):
        self.own = own_number
        self.roster = set(roster)
        self.filters: dict[int, BandFilter] = {}

    def add(self, band_number: int, rssi: float, at: float | None = None) -> None:
        if band_number == self.own or band_number not in self.roster:
            return
        self.filters.setdefault(band_number, BandFilter()).add(rssi, at)

    def observations(self, now: float | None = None) -> list:
        out = []
        for number, f in self.filters.items():
            obs = f.observation(number, now)
            if obs:
                out.append(obs)
        return out
