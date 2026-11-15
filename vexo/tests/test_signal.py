from conftest import Demo


def join(d, name, token=None):
    return d.client.post("/api/signal/join", json={"name": name, "token": token})


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_join_list_and_answer_reaches_only_the_addressee():
    d = Demo()
    kgen = join(d, "kgen").json()
    guest = join(d, "Sam").json()
    names = [m["name"] for m in d.client.get("/api/signal/members").json()["members"]]
    assert sorted(names) == ["Sam", "kgen"]
    assert d.client.post("/api/signal", headers=auth(guest["token"]), json={"to": "KGEN", "answer": "accept"}).status_code == 200
    got = d.client.get("/api/signal", headers=auth(kgen["token"])).json()["signal"]
    assert got["answer"] == "accept" and got["from"] == "Sam"
    assert d.client.get("/api/signal", headers=auth(guest["token"])).json()["signal"] is None


def test_name_rules_and_auth():
    d = Demo()
    t = join(d, "kgen").json()["token"]
    assert join(d, "kgen").status_code == 409                    # online name cannot be taken
    assert join(d, "kgen", t).status_code == 200                 # owner can resume
    assert join(d, "<b>").status_code == 422
    assert d.client.post("/api/signal", json={"to": "kgen", "answer": "accept"}).status_code == 401
    assert d.client.post("/api/signal", headers=auth(t), json={"to": "kgen", "answer": "accept"}).status_code == 409
    assert d.client.post("/api/signal", headers=auth(t), json={"to": "nobody", "answer": "accept"}).status_code == 404
    assert d.client.post("/api/signal", headers=auth(t), json={"to": "x", "answer": "maybe"}).status_code == 422
    assert d.client.get("/respond").status_code == 200
