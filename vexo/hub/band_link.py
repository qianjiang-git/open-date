"""BandLink: the single owner of this hub's band connection.

Modes follow the server's desired state: BEACON (renew the advertising window), IDLE (no
renewal), LIT (connected, pair colour, taps on), MET_FLASH (green blink). Commands apply
only if newer than the last accepted version and still inside their lease. A LIT or
MET_FLASH command whose lease is not renewed by the server clears the LED and disconnects.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from .adapters import BandAdapter

log = logging.getLogger("vexo.link")

RENEW_S = 90.0                 # renew at 90 s of the documented 120 s window (plan section 3)
RETRY_S = (2.0, 5.0)
TAP_DEBOUNCE_S = 1.0


class BandLink:
    def __init__(self, adapter: BandAdapter, renew_s: float = RENEW_S, sim_tap_after: float | None = None):
        self.adapter = adapter
        self.renew_s = renew_s
        self.sim_tap_after = sim_tap_after
        self.mode = "IDLE"
        self.command: dict | None = None          # last accepted desired command
        self.last_version = 0
        self.lease_until = 0.0                    # monotonic
        self.next_renewal = 0.0                   # monotonic; 0 = renew as soon as possible
        self.renew_failures = 0
        self.band_state = "idle"
        self.pending_acks: list = []
        self.pending_taps: list = []
        self._last_tap = 0.0
        self._queue: asyncio.Queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        adapter.on_drop(self._dropped)

    # ------------------------------------------------------------ from the poll loop

    def on_desired(self, desired: dict) -> None:
        """Called with every tick response. Renews the lease or queues a newer command."""
        now = time.monotonic()
        if self.command and desired["command_id"] == self.command["command_id"]:
            self.lease_until = now + desired["valid_for_ms"] / 1000
            return
        if desired["desired_version"] <= self.last_version:
            return                                 # older than what we already applied
        self.last_version = desired["desired_version"]
        self._queue.put_nowait({**desired, "_received": now})

    def health(self) -> dict:
        return {"state": self.band_state, "mic_active": False}

    def take_outbox(self) -> tuple[list, list]:
        return list(self.pending_acks), list(self.pending_taps)

    def confirm(self, ack_ids: list, tap_ids: list) -> None:
        self.pending_acks = [a for a in self.pending_acks if a["command_id"] not in ack_ids]
        self.pending_taps = [t for t in self.pending_taps if t["event_id"] not in tap_ids]

    # ------------------------------------------------------------ actor loop

    async def run(self) -> None:
        while True:
            try:
                cmd = await asyncio.wait_for(self._queue.get(), timeout=0.25)
            except asyncio.TimeoutError:
                cmd = None
            async with self._lock:
                if cmd is not None:
                    await self._apply(cmd)
                await self._check_lease()
                await self._renew_if_due()

    def _ack(self, cmd: dict, status: str, error: str | None = None) -> None:
        self.pending_acks.append({"command_id": cmd["command_id"], "version": cmd["desired_version"],
                                  "status": status, "error": error})
        log.info("command v%s %s -> %s%s", cmd["desired_version"], cmd["mode"], status,
                 f" ({error})" if error else "")

    async def _apply(self, cmd: dict) -> None:
        if time.monotonic() > cmd["_received"] + cmd["valid_for_ms"] / 1000:
            self._ack(cmd, "EXPIRED")
            return
        self.command = cmd
        self.lease_until = cmd["_received"] + cmd["valid_for_ms"] / 1000
        mode = cmd["mode"]
        try:
            if mode == "LIT":
                await self._ensure_connected()
                await self.adapter.set_led(cmd["color"], "solid", cmd.get("brightness") or 0.6)
                await self.adapter.enable_taps(lambda e, c=cmd: self._tap(c))
                self.mode, self.band_state = "LIT", "connected"
                if self.sim_tap_after is not None and hasattr(self.adapter, "tap"):
                    asyncio.get_running_loop().call_later(self.sim_tap_after, self.adapter.tap)
            elif mode == "MET_FLASH":
                await self._ensure_connected()
                await self.adapter.set_led(cmd["color"] or "#00ff00", "blink", cmd.get("brightness") or 0.8, 300)
                self.mode, self.band_state = "MET_FLASH", "connected"
            elif mode in ("BEACON", "IDLE"):
                await self._release()
                self.mode = mode
                self.band_state = "advertising" if mode == "BEACON" else "idle"
                if mode == "BEACON" and not self.adapter.advertises:
                    self.band_state = "ready"
            self._ack(cmd, "APPLIED")
        except Exception as exc:
            self._ack(cmd, "FAILED", f"{type(exc).__name__}: {exc}"[:280])
            await self._release()
            self.band_state = "error" if mode in ("LIT", "MET_FLASH") else self.band_state

    async def _ensure_connected(self) -> None:
        if not self.adapter.connected:
            await self.adapter.connect()

    async def _release(self) -> None:
        """Clear the LED and disconnect. A disconnect reopens the 120 s advertising window."""
        if self.adapter.connected:
            try:
                await self.adapter.led_off()
            finally:
                await self.adapter.disconnect()
            self.next_renewal = time.monotonic() + self.renew_s

    async def _check_lease(self) -> None:
        if self.mode in ("LIT", "MET_FLASH") and time.monotonic() > self.lease_until:
            log.warning("lease expired without renewal: clearing the light")
            await self._release()
            self.mode, self.band_state = "BEACON", "advertising" if self.adapter.advertises else "ready"
            if self.command:
                self._ack(self.command, "EXPIRED")

    async def _renew_if_due(self) -> None:
        if self.mode != "BEACON" or not self.adapter.advertises or time.monotonic() < self.next_renewal:
            return
        try:
            await self.adapter.connect()          # also verifies the band's identity
            battery = await self.adapter.battery()
            await self.adapter.disconnect()
            self.renew_failures = 0
            self.next_renewal = time.monotonic() + self.renew_s
            self.band_state = "advertising"
            log.info("advertising window renewed (battery %s%%); next renewal in %.0f s", battery, self.renew_s)
        except Exception as exc:
            self.renew_failures += 1
            delay = RETRY_S[min(self.renew_failures - 1, len(RETRY_S) - 1)]
            if self.renew_failures > len(RETRY_S):
                self.band_state = "needs_double_tap"
                delay = 10.0
                log.warning("cannot reach band %s: double-tap it to open a window (%s)", self.adapter.number, exc)
            self.next_renewal = time.monotonic() + delay

    # ------------------------------------------------------------ band events

    def _tap(self, cmd: dict) -> None:
        now = time.monotonic()
        if self.mode != "LIT" or self.command is not cmd or now - self._last_tap < TAP_DEBOUNCE_S:
            return
        self._last_tap = now
        self.pending_taps.append({"event_id": str(uuid.uuid4()), "match_id": cmd["match_id"],
                                  "lighting_session_id": cmd["lighting_session_id"]})
        log.info("tap recorded for match %s", (cmd["match_id"] or "")[:8])

    def _dropped(self) -> None:
        if self.mode in ("LIT", "MET_FLASH"):
            self.band_state = "error"              # server ends the match as device loss
        self.next_renewal = time.monotonic() + self.renew_s
