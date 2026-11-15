"""Scorers (deterministic formula, Claude adapter failure modes) and profile proposals."""
import pytest

from conftest import Demo
from server import matcher
from server.config import Scorer

A = {"summary": "", "interests": ["climbing", "guitar", "hiking"], "values": ["honesty", "curiosity"],
     "goal": "long-term", "accepted_goals": ["long-term"]}


def test_deterministic_formula():
    b = dict(A)
    assert matcher.deterministic(A, b)["score"] == 100
    c = {**A, "interests": ["climbing", "tennis", "yoga"], "values": ["honesty", "family"]}
    # interests 1/5, values 1/3, goal 1 -> 100*(0.08 + 0.1167 + 0.25) = 45
    assert matcher.deterministic(A, c)["score"] == 45
    d = {**A, "goal": "casual", "accepted_goals": ["casual", "long-term"]}
    assert matcher.goal_compatibility(A, d) == 0.0           # A does not accept casual
    e = {**A, "accepted_goals": ["long-term", "casual"]}
    assert matcher.goal_compatibility(e, d) == 0.5


def test_empty_tags_score_zero_not_crash():
    z = {**A, "interests": [], "values": [], "goal": "x", "accepted_goals": []}
    assert matcher.deterministic(z, z)["score"] == 25        # identical goal only


def test_claude_without_key_is_unavailable_not_incompatible(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(matcher.ScoringUnavailable):
        matcher.score(A, A, Scorer(provider="claude"))


def test_claude_fallback_is_labelled(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    v = matcher.score(A, A, Scorer(provider="claude", fallback_to_deterministic=True))
    assert "fallback" in v["scorer"] and v["threshold"] == 60


def test_unavailable_scorer_ends_match_with_reason(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = Demo(scorer={"provider": "claude"})
    d.step(1)
    d.approach("alice", "bob", -70, 6)
    m = d.state()["matches"][0]
    assert m["state"] == "ENDED" and m["end_reason"] == "scoring_unavailable"
    assert d.inbox("alice") == []


def test_claude_evidence_must_exist_in_both_profiles(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    class FakeResponse:
        stop_reason = "end_turn"
        parsed_output = matcher.ClaudeVerdict(score=90, shared=["climbing", "skydiving"],
                                              explanation="x", icebreaker="hi")

    class FakeMessages:
        def parse(self, **kw):
            assert "<profile_a>" in kw["messages"][0]["content"]
            assert "Alice" not in kw["messages"][0]["content"]
            return FakeResponse()

    class FakeClient:
        def __init__(self, **kw):
            self.messages = FakeMessages()

        def with_options(self, **kw):
            return self

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    b = {**A, "interests": ["climbing", "tennis", "yoga"]}
    with pytest.raises(matcher.ScoringUnavailable, match="skydiving"):
        matcher.claude(A, b, Scorer(provider="claude"))


def test_claude_refusal_is_unavailable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    class Refused:
        stop_reason = "refusal"
        parsed_output = None

    class FakeClient:
        def __init__(self, **kw):
            self.messages = self

        def with_options(self, **kw):
            return self

        def parse(self, **kw):
            return Refused()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(matcher.ScoringUnavailable, match="refused"):
        matcher.claude(A, A, Scorer(provider="claude"))


def test_note_creates_proposal_not_profile_change(demo):
    d = demo
    me = d.client.get("/api/me", headers=d.u("alice")).json()
    r = d.client.post("/api/me/voice-notes", headers=d.u("alice"),
                      json={"transcript": "I started salsa dancing and I volunteer at a community garden."})
    assert r.status_code == 200
    changes = r.json()["changes"]
    assert "dancing" in changes["interests"] and "gardening" in changes["interests"]
    assert d.client.get("/api/me", headers=d.u("alice")).json()["profile"] == me["profile"]
    pid = r.json()["proposal_id"]
    assert d.client.post(f"/api/me/profile-proposals/{pid}/accept", headers=d.u("alice")).status_code == 200
    after = d.client.get("/api/me", headers=d.u("alice")).json()["profile"]
    assert after["version"] == me["profile"]["version"] + 1 and "dancing" in after["interests"]


def test_stale_proposal_is_rejected(demo):
    d = demo
    pid = d.client.post("/api/me/voice-notes", headers=d.u("alice"),
                        json={"transcript": "I love film nights."}).json()["proposal_id"]
    me = d.client.get("/api/me", headers=d.u("alice")).json()
    d.client.patch("/api/me/profile", headers=d.u("alice"),
                   json={"expected_version": me["profile"]["version"], "summary": "Edited by hand."})
    r = d.client.post(f"/api/me/profile-proposals/{pid}/accept", headers=d.u("alice"))
    assert r.status_code in (404, 409)
    assert d.client.get("/api/me", headers=d.u("alice")).json()["profile"]["summary"] == "Edited by hand."


def test_voice_never_changes_status_or_preferences(demo):
    d = demo
    before = d.client.get("/api/me", headers=d.u("alice")).json()
    pid = d.client.post("/api/me/voice-notes", headers=d.u("alice"),
                        json={"transcript": "I'm not dating anymore, only want casual, I am 19."}).json()["proposal_id"]
    d.client.post(f"/api/me/profile-proposals/{pid}/accept", headers=d.u("alice"))
    after = d.client.get("/api/me", headers=d.u("alice")).json()
    assert after["dating_status"] == before["dating_status"]
    assert after["preferences"] == before["preferences"] and after["age"] == before["age"]
