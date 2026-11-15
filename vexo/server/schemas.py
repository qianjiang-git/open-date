"""Request bodies. Identity always comes from the bearer token, never from a body field."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

TAG = r"^[a-z0-9][a-z0-9-]{0,30}$"


class ProfileEdit(BaseModel):
    expected_version: int
    summary: Optional[str] = Field(None, max_length=300)
    interests: Optional[list[str]] = Field(None, max_length=8)
    values: Optional[list[str]] = Field(None, max_length=6)
    goal: Optional[str] = Field(None, pattern=r"^(long-term|casual|friendship-first)$")

    @field_validator("interests", "values")
    @classmethod
    def _tags(cls, v):
        import re
        if v is not None:
            for t in v:
                if not re.match(TAG, t):
                    raise ValueError(f"tags are lowercase words with hyphens, got {t!r}")
        return v


class PreferencesEdit(BaseModel):
    expected_version: int
    genders: Optional[list[str]] = None
    age_min: Optional[int] = Field(None, ge=18, le=120)
    age_max: Optional[int] = Field(None, ge=18, le=120)
    accepted_goals: Optional[list[Literal["long-term", "casual", "friendship-first"]]] = None


class DatingStatus(BaseModel):
    status: Literal["open", "paused"]
    expected_version: int


class Respond(BaseModel):
    accept: bool


class VoiceNote(BaseModel):
    transcript: str = Field(min_length=3, max_length=4000)
    source: Literal["typed", "mic"] = "typed"


class Observation(BaseModel):
    target_band_number: int = Field(ge=1, le=999)
    source: Literal["real_beacon"] = "real_beacon"     # hubs may only report radio evidence
    sequence: int = Field(ge=0)
    rssi_dbm: float = Field(ge=-127, le=20)
    samples: int = Field(ge=0, le=1000)
    window_seconds: float = Field(gt=0, le=30)
    sample_age_ms: int


class Ack(BaseModel):
    command_id: str
    version: int
    status: Literal["APPLIED", "FAILED", "EXPIRED", "SUPERSEDED"]
    error: Optional[str] = Field(None, max_length=300)


class Tap(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)
    match_id: str
    lighting_session_id: str


class BandHealth(BaseModel):
    state: Literal["advertising", "ready", "connected", "needs_double_tap", "error", "voice", "idle", "offline"]
    mic_active: bool = False
    battery: Optional[int] = Field(None, ge=0, le=100)


class Tick(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    seq: int = Field(ge=1)
    band: BandHealth
    observations: list[Observation] = Field(default_factory=list, max_length=50)
    acks: list[Ack] = Field(default_factory=list, max_length=20)
    taps: list[Tap] = Field(default_factory=list, max_length=20)


class DemoSighting(BaseModel):
    observer_band: int = Field(ge=1, le=999)
    target_band: int = Field(ge=1, le=999)
    rssi_dbm: float = Field(ge=-127, le=20)
    source: Literal["simulated", "mirrored_demo"] = "simulated"
    samples: int = 5
