"""Authenticated 1-second poll. Acks and taps are kept until the server confirms them."""
from __future__ import annotations

import asyncio
import logging
import uuid

import httpx

from .band_link import BandLink
from .proximity import Proximity

log = logging.getLogger("vexo.client")


class ServerClient:
    def __init__(self, server_url: str, hub_token: str, link: BandLink, proximity: Proximity | None):
        self.url = server_url.rstrip("/") + "/api/hub/tick"
        self.headers = {"Authorization": f"Bearer {hub_token}"}
        self.link = link
        self.proximity = proximity
        self.session_id = str(uuid.uuid4())
        self.seq = 0
        self.last_response: dict | None = None

    async def run(self) -> None:
        backoff = 1.0
        async with httpx.AsyncClient(timeout=3.0) as http:
            while True:
                self.seq += 1
                acks, taps = self.link.take_outbox()
                body = {"session_id": self.session_id, "seq": self.seq, "band": self.link.health(),
                        "observations": self.proximity.observations() if self.proximity else [],
                        "acks": acks, "taps": taps}
                try:
                    r = await http.post(self.url, json=body, headers=self.headers)
                    r.raise_for_status()
                    data = r.json()
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("server unreachable (%s); retrying in %.0f s", type(exc).__name__, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 5.0)
                    continue
                backoff = 1.0
                self.last_response = data
                self.link.confirm(data["ack_ids"], data["tap_acks"])
                self.link.on_desired(data["desired"])
                await asyncio.sleep(data.get("next_poll_ms", 1000) / 1000)
