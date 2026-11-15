"""One-time LinkedIn OIDC profile import for the Google-authenticated iPhone beta."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.id_token import verify_oauth2_token
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/beta/linkedin")


def settings():
    values = [os.getenv(k, "") for k in ("GOOGLE_IOS_CLIENT_ID", "LINKEDIN_CLIENT_ID",
                                          "LINKEDIN_CLIENT_SECRET", "LINKEDIN_REDIRECT_URI")]
    if not all(values) or urlsplit(values[3]).scheme != "https":
        raise HTTPException(503, "LinkedIn import is not configured for this beta.")
    return values


def account(request: Request):
    audience = settings()[0]
    kind, _, token = request.headers.get("authorization", "").partition(" ")
    if kind.lower() != "bearer" or not token:
        raise HTTPException(401, "Google sign-in required.")
    try:
        return verify_oauth2_token(token, GoogleRequest(), audience)["sub"]
    except (GoogleAuthError, ValueError, KeyError):
        raise HTTPException(401, "Please sign in with Google again.") from None


def signature(secret, subject, challenge, salt, expiry):
    msg = json.dumps([subject, challenge, salt, expiry], separators=(",", ":")).encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class Start(BaseModel):
    challenge: str = Field(pattern=r"^[0-9a-f]{64}$")


class Finish(BaseModel):
    verifier: str = Field(min_length=32, max_length=160)
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(pattern=r"^[0-9]{1,12}\.[0-9a-f]{32}\.[0-9a-f]{64}$")


@router.post("/start")
def start(body: Start, subject: str = Depends(account)):
    _, client, secret, redirect = settings()
    expiry, salt = str(int(time.time()) + 600), secrets.token_hex(16)
    state = ".".join([expiry, salt, signature(secret, subject, body.challenge, salt, expiry)])
    params = dict(response_type="code", client_id=client, redirect_uri=redirect,
                  state=state, scope="openid profile")
    return {"url": "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(params),
            "state": state}


@router.get("/callback")
def callback(state: str, code: str = "", error: str = ""):
    query = {"state": state}
    if error or not code:
        query["error"] = "cancelled"
    else:
        query["code"] = code
    return RedirectResponse("opendatebeta://linkedin?" + urlencode(query), status_code=302,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/finish")
def finish(body: Finish, subject: str = Depends(account)):
    _, client, secret, redirect = settings()
    parts = body.state.split(".")
    challenge = hashlib.sha256(body.verifier.encode()).hexdigest()
    if len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) < time.time() or not hmac.compare_digest(
        signature(secret, subject, challenge, parts[1], parts[0]), parts[2]
    ):
        raise HTTPException(400, "LinkedIn authorization expired. Please reconnect.")
    try:
        token = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "authorization_code", "code": body.code, "client_id": client,
            "client_secret": secret, "redirect_uri": redirect}, timeout=12)
        token.raise_for_status()
        bearer = token.json()["access_token"]
        info = requests.get("https://api.linkedin.com/v2/userinfo",
                            headers={"Authorization": "Bearer " + bearer}, timeout=12)
        info.raise_for_status()
        claims = info.json()
        if not claims.get("sub"):
            raise ValueError("missing subject")
    except (requests.RequestException, KeyError, ValueError):
        raise HTTPException(502, "LinkedIn could not return the profile. Please reconnect.") from None
    return {"name": claims.get("given_name") or claims.get("name"), "picture": claims.get("picture")}
