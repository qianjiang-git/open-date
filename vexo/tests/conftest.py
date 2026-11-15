"""Test harness: fake clock, in-memory SQLite, API client, simulated hubs and sightings."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config as config_mod          # noqa: E402
from server.app import create_app                # noqa: E402
from server.db import Database, FakeClock        # noqa: E402
from server.enroll import PEOPLE, enroll, operator_token   # noqa: E402

BANDS = {"alice": 11, "bob": 22, "cara": 33, "dan": 44}


class Demo:
    def __init__(self, people=("alice", "bob"), open_now=True, **cfg_overrides):
        self.clock = FakeClock()
        self.cfg = config_mod._merge(config_mod.Config(), {"db_path": ":memory:", **cfg_overrides})
        self.db = Database(":memory:", self.clock)
        self.app = create_app(self.cfg, self.db, start_worker=False)
        self.client = TestClient(self.app)
        self.p = {}
        for key in people:
            spec = {k: v for k, v in PEOPLE[key].items()}
            self.p[key] = enroll(self.db, band_number=BANDS[key], open_now=open_now, **spec)
        self.op = {"Authorization": f"Bearer {operator_token(self.db)}"}
        self.hubs = {k: {"session": str(uuid.uuid4()), "seq": 0, "state": "advertising",
                         "acks": [], "taps": [], "applied": None, "online": True} for k in people}

    # -- auth headers
    def u(self, who):
        return {"Authorization": f"Bearer {self.p[who]['user_token']}"}

    def h(self, who):
        return {"Authorization": f"Bearer {self.p[who]['hub_token']}"}

    # -- hub simulation: obeys desired state like the real hub, acks every new command
    def tick(self, who, observations=(), auto_apply=True, fail=False):
        hub = self.hubs[who]
        hub["seq"] += 1
        body = {"session_id": hub["session"], "seq": hub["seq"],
                "band": {"state": hub["state"], "mic_active": False, "battery": 80},
                "observations": list(observations), "acks": hub["acks"], "taps": hub["taps"]}
        r = self.client.post("/api/hub/tick", json=body, headers=self.h(who))
        assert r.status_code == 200, r.text
        data = r.json()
        hub["acks"], hub["taps"] = [], [t for t in hub["taps"] if t["event_id"] not in data["tap_acks"]]
        d = data["desired"]
        hub["desired"] = d
        if auto_apply and d["command_id"] != hub["applied"]:
            hub["applied"] = d["command_id"]
            status = "FAILED" if (fail and d["mode"] == "LIT") else "APPLIED"
            hub["acks"].append({"command_id": d["command_id"], "version": d["desired_version"], "status": status})
            if status == "APPLIED":
                hub["state"] = "connected" if d["mode"] in ("LIT", "MET_FLASH") else "advertising"
        return data

    def tap(self, who):
        d = self.hubs[who]["desired"]
        self.hubs[who]["taps"].append({"event_id": str(uuid.uuid4()), "match_id": d["match_id"],
                                       "lighting_session_id": d["lighting_session_id"]})

    def sight(self, observer, target, rssi, source="simulated"):
        r = self.client.post("/api/demo/sightings", headers=self.op, json={
            "observer_band": BANDS[observer], "target_band": BANDS[target], "rssi_dbm": rssi, "source": source})
        assert r.status_code == 200, r.text
        return r.json()

    def step(self, seconds=1.0, sightings=(), ticks=True):
        """Advance time; every online hub ticks twice (send, then deliver acks); worker runs."""
        self.clock.advance(seconds)
        for obs, tgt, rssi in sightings:
            self.sight(obs, tgt, rssi)
        if ticks:
            for who, hub in self.hubs.items():
                if hub["online"]:
                    self.tick(who)
                    self.tick(who)
        self.app.state.engine.run_once()

    def approach(self, a, b, rssi, seconds):
        for _ in range(int(seconds)):
            self.step(1, sightings=[(a, b, rssi), (b, a, rssi)])

    def match(self, who):
        return self.client.get("/api/me/match", headers=self.u(who)).json()["match"]

    def inbox(self, who):
        return self.client.get("/api/me/notifications", headers=self.u(who)).json()["items"]

    def respond(self, who, accept=True):
        m = self.match(who)
        return self.client.post(f"/api/matches/{m['id']}/respond", json={"accept": accept}, headers=self.u(who))

    def state(self):
        return self.client.get("/api/demo/state", headers=self.op).json()


@pytest.fixture
def demo():
    return Demo()
