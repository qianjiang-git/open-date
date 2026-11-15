"""Server configuration: one JSON file, every value with a safe default.

Load order: the file named by $VEXO_CONFIG, else config/demo.local.json, else defaults.
Nothing here is a secret: provider keys come from the environment (.env is git-ignored).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEMO_MODES = ("real", "single_laptop", "simulated")

# Sighting sources each demo mode accepts as proximity evidence. Anything else is ignored
# for matching and lighting, so a simulated sighting can never pass as a radio result.
ALLOWED_SOURCES = {
    "real": {"real_beacon"},
    "single_laptop": {"real_beacon", "mirrored_demo"},
    "simulated": {"simulated"},
}

# Lighting palette. Blue is the band's own status colour (advertising window, microphone);
# green means "met". Neither is ever a pair colour.
PALETTE = ["#00c7be", "#ff2d55", "#ff9500", "#af52de", "#ffcc00", "#ffffff"]
PALETTE_NAMES = {"#00c7be": "teal", "#ff2d55": "pink", "#ff9500": "orange",
                 "#af52de": "purple", "#ffcc00": "yellow", "#ffffff": "white"}
MET_COLOR = "#00ff00"


@dataclass
class Rssi:
    near_enter: float = -78.0     # FAR -> NEAR when at least this
    near_exit: float = -84.0      # NEAR -> FAR when below this
    close_enter: float = -58.0    # NEAR -> CLOSE when at least this
    close_exit: float = -66.0     # CLOSE -> NEAR when below this
    enter_dwell_s: float = 3.0
    exit_dwell_s: float = 5.0
    stale_s: float = 8.0          # no fresh sample -> UNKNOWN
    min_samples: int = 3
    fresh_close_s: float = 5.0    # lighting gate: close confirmed within this many seconds
    max_sample_age_ms: int = 5000  # older observations are rejected as impossible/stale


@dataclass
class Deadlines:
    scoring_s: float = 20.0
    suggestion_s: float = 120.0
    approach_s: float = 180.0
    lighting_s: float = 10.0
    lighting_attempts: int = 2
    lit_s: float = 60.0
    met_flash_s: float = 3.0
    hub_lost_s: float = 5.0
    command_lease_ms: int = 5000
    cooldown_long_s: float = 600.0    # decline, cancel, met
    cooldown_short_s: float = 60.0    # expiry, device failure
    score_cache_s: float = 86400.0


@dataclass
class Scorer:
    provider: str = "deterministic"   # "deterministic" | "claude"
    threshold: int = 60               # deterministic scale
    claude_model: str = "claude-opus-5-5"
    claude_threshold: int = 70        # Claude scale, independent of the deterministic one
    claude_effort: str = "low"
    timeout_s: float = 15.0           # total budget, one retry inside it
    fallback_to_deterministic: bool = False   # if true, the fallback is labelled on the match
    prompt_version: str = "v1"


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8080
    demo_mode: str = "simulated"
    db_path: str = str(ROOT / "server" / "vexo.db")
    roster: list = field(default_factory=list)     # authorised band numbers for this demo
    worker_interval_s: float = 0.5
    rssi: Rssi = field(default_factory=Rssi)
    deadlines: Deadlines = field(default_factory=Deadlines)
    scorer: Scorer = field(default_factory=Scorer)

    @property
    def allowed_sources(self) -> set:
        return ALLOWED_SOURCES[self.demo_mode]


def _merge(obj, values: dict):
    for key, value in values.items():
        if not hasattr(obj, key):
            raise ValueError(f"unknown config key: {key}")
        current = getattr(obj, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(obj, key, value)
    return obj


def load(path: str | None = None, **overrides) -> Config:
    cfg = Config()
    path = path or os.environ.get("VEXO_CONFIG")
    if path is None and (ROOT / "config" / "demo.local.json").exists():
        path = str(ROOT / "config" / "demo.local.json")
    if path:
        data = json.loads(Path(path).read_text())
        data.pop("hubs", None)          # hub sections are read by hub.py, not the server
        data.pop("_comment", None)
        _merge(cfg, data)
    _merge(cfg, overrides)
    if cfg.demo_mode not in DEMO_MODES:
        raise ValueError(f"demo_mode must be one of {DEMO_MODES}, got {cfg.demo_mode!r}")
    return cfg
