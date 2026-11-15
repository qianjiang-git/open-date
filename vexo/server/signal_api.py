"""Small join-by-name demo relay for browser clients and a laptop band bridge.

This feature is deliberately independent of dating profiles, proximity and matching.
Participants join with a demo name; the server assigns a random person ID and bearer
token. Online state is a heartbeat lease refreshed by joining/polling clients.
"""
from __future__ import annotations

import re
import secrets
import threading
import uuid
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

PRESENCE_TTL_S = 12
SIGNAL_TTL_S = 120
NAME_RE = re.compile(r"^[\w .'-]+$", re.UNICODE)


class JoinIn(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    token: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or not NAME_RE.fullmatch(value):
            raise ValueError("name may contain letters, numbers, spaces, apostrophe, dot and hyphen")
        return value


class SignalIn(BaseModel):
    to: str = Field(min_length=1, max_length=128)
    answer: Literal["accept", "reject"]


def register(app: FastAPI) -> None:
    # Render currently runs this demo as one service instance. This ephemeral state is
    # enough for a live demo; after a restart each tab/process rejoins automatically.
    members: dict[str, dict] = {}                 # person ID -> {token, name, last_seen}
    token_to_id: dict[str, str] = {}
    latest: dict[str, dict] = {}                   # recipient person ID -> newest answer
    counter = {"seq": 0}
    lock = threading.RLock()

    def clean(now: float) -> None:
        with lock:
            expired = [uid for uid, m in members.items() if now - m["last_seen"] > PRESENCE_TTL_S]
            for uid in expired:
                token_to_id.pop(members[uid]["token"], None)
                members.pop(uid, None)

    def identity(authorization: str | None, now: float) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "join first and send your bearer token")
        token = authorization[7:].strip()
        with lock:
            uid = token_to_id.get(token)
            member = members.get(uid) if uid else None
            if member is None:
                raise HTTPException(401, "unknown or expired client token; join again")
            member["last_seen"] = now
            return member

    @app.post("/api/signal/join")
    def join(body: JoinIn):
        now = app.state.db.now()
        clean(now)
        key = body.name.casefold()
        with lock:
            if body.token:
                uid = token_to_id.get(body.token)
                member = members.get(uid) if uid else None
                if member is None:
                    raise HTTPException(401, "unknown or expired client token; join without the old token")
                if member["name"].casefold() != key:
                    raise HTTPException(403, "that token belongs to a different client name")
                member["last_seen"] = now
                return {"id": member["id"], "name": member["name"], "token": body.token,
                        "online": True, "presence_ttl_seconds": PRESENCE_TTL_S}
            for member in members.values():
                if member["name"].casefold() == key:
                    raise HTTPException(409, "that name is already online; choose another name")
            uid = str(uuid.uuid4())
            token = "sig_" + secrets.token_urlsafe(32)
            member = {"id": uid, "name": body.name, "token": token, "last_seen": now}
            members[uid] = member
            token_to_id[token] = uid
            return {"id": uid, "name": body.name, "token": token,
                    "online": True, "presence_ttl_seconds": PRESENCE_TTL_S}

    @app.get("/api/signal/members")
    def list_members():
        now = app.state.db.now()
        clean(now)
        with lock:
            people = [{"id": m["id"], "name": m["name"], "online": True}
                      for m in sorted(members.values(), key=lambda x: x["name"].casefold())]
        return {"members": people, "server_time": now, "presence_ttl_seconds": PRESENCE_TTL_S}

    @app.post("/api/signal")
    def send_signal(body: SignalIn, authorization: str | None = Header(default=None)):
        now = app.state.db.now()
        clean(now)
        sender = identity(authorization, now)
        query = body.to.strip()
        with lock:
            target = next((m for m in members.values()
                           if m["id"] == query or m["name"].casefold() == query.casefold()), None)
            if target is None:
                raise HTTPException(404, "recipient is not online")
            if target["id"] == sender["id"]:
                raise HTTPException(409, "cannot signal yourself")
            counter["seq"] += 1
            event = {"seq": counter["seq"], "answer": body.answer, "from": sender["name"],
                     "from_id": sender["id"], "to": target["id"], "created_at": now,
                     "expires_at": now + SIGNAL_TTL_S}
            latest[target["id"]] = event
        return {"ok": True, "seq": event["seq"], "to": target["id"],
                "expires_in_seconds": SIGNAL_TTL_S}

    @app.get("/api/signal")
    def read_signal(authorization: str | None = Header(default=None)):
        now = app.state.db.now()
        clean(now)
        member = identity(authorization, now)
        with lock:
            signal = latest.get(member["id"])
            if signal is not None and signal["expires_at"] <= now:
                latest.pop(member["id"], None)
                signal = None
            else:
                signal = dict(signal) if signal else None
        if signal is not None:
            signal.pop("expires_at", None)
        return {"signal": signal, "server_time": now}
