import hashlib
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import linkedin_import as api


def test_import_bound_to_google_account_and_originating_phone(monkeypatch):
    for key, value in {"GOOGLE_IOS_CLIENT_ID": "beta-client", "LINKEDIN_CLIENT_ID": "linkedin",
                       "LINKEDIN_CLIENT_SECRET": "test", "LINKEDIN_REDIRECT_URI": "https://beta.example/callback"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(api, "verify_oauth2_token", lambda token, req, audience: {"sub": token})
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    path = "/api/beta/linkedin"
    auth = {"Authorization": "Bearer user-one"}
    verifier = "a" * 64
    challenge = hashlib.sha256(verifier.encode()).hexdigest()
    assert client.post(path + "/start", json={"challenge": challenge}).status_code == 401
    start = client.post(path + "/start", headers=auth, json={"challenge": challenge}).json()
    state = start["state"]
    callback = client.get(path + "/callback", params={"state": state, "code": "one-time-code"}, follow_redirects=False)
    assert callback.headers["location"].startswith("opendatebeta://linkedin?")
    body = {"state": state, "code": "one-time-code", "verifier": verifier}
    assert client.post(path + "/finish", headers={"Authorization": "Bearer user-two"}, json=body).status_code == 400
    assert client.post(path + "/finish", headers=auth, json={**body, "verifier": "b"*64}).status_code == 400
    monkeypatch.setattr(api.requests, "post", lambda *a, **k: Mock(json=lambda: {"access_token": "private"}))
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: Mock(json=lambda: {"sub": "linkedin-user", "given_name": "Ari", "picture": "https://media.licdn.com/test", "email": "private"}))
    assert client.post(path + "/finish", headers=auth, json=body).json() == {
        "name": "Ari", "picture": "https://media.licdn.com/test"}
