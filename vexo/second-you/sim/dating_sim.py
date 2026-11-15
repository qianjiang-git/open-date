"""Open Dating simulation: can Agent-to-Agent chats find real chemistry?

20 virtual people get HIDDEN traits (values, dealbreakers, humor, conversation habits, conflict style, interests) and a
known "true compatibility" formula over them. Each person's agent only gets a Second-You-style profile card, never the
formula. Every eligible pair's agents talk in 3 scenarios; a separate judge (OpenAI, a different model family from the Gemini agents) scores each
conversation from the transcript alone. Then we check how well the scores recover the hidden truth:

  - judge score (mean over scenarios, dealbreakers penalized), with a confidence interval from the scenario spread
  - language style matching (LSM, function-word similarity, no model call)
  - the naive baseline: each agent rates its own chemistry after the first chat (expected: everyone "loves" everyone)

Run on the server (keys come from the environment, never printed):
    GEMINI_KEY=... OPENAI_API_KEY=... python3 sim/dating_sim.py
Output in $SIM_OUT (default ~/sim): personas.json, conversations.jsonl, results.json, report.md
"""
import concurrent.futures as cf, json, math, os, random, re, statistics, sys, threading, time
import requests

SEED = int(os.environ.get("SIM_SEED", "7"))
R = random.Random(SEED)
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
AGENT_MODEL = os.environ.get("SIM_AGENT_MODEL", "gemini-3.8-flash")
JUDGE_MODEL = os.environ.get("SIM_JUDGE_MODEL", "gpt-5.5")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OUT = os.path.expanduser(os.environ.get("SIM_OUT", "~/sim"))
TURNS = int(os.environ.get("SIM_TURNS", "6"))
WORKERS = int(os.environ.get("SIM_WORKERS", "8"))
MAX_PAIRS = int(os.environ.get("SIM_MAX_PAIRS", "0"))       # 0 = every eligible pair

# ---------------------------------------------------------------- people
WOMEN = ["Maya", "Priya", "Sofia", "Hannah", "Lin", "Chloe", "Aisha", "Grace", "Elena", "Jess", "Nora"]
MEN = ["Daniel", "Kevin", "Marcus", "Leo", "Sam", "Arjun", "Ethan", "Tomás", "Ben"]
JOBS = ["product designer", "nurse", "software engineer", "founder of a climate startup", "high school teacher",
        "investment analyst", "chef", "PhD student in neuroscience", "UX researcher", "lawyer", "physical therapist",
        "VC associate", "musician who teaches piano", "data scientist", "architect"]
INTERESTS = ["rock climbing", "jazz bars", "startups", "cooking Sichuan food", "hiking in Marin", "indie films",
             "half marathons", "board games", "film photography", "sci-fi novels", "yoga", "travel in Japan",
             "live comedy", "gardening", "pickup basketball", "art museums", "surfing at Ocean Beach", "karaoke",
             "natural wine", "volunteering at a food bank"]
HUMOR = {
    "dry": ("deadpan, understated one-liners", ["Bold of you to assume I have weekend plans.", "Wow. Riveting."]),
    "absurd": ("silly hypotheticals and random tangents", ["Okay but what if pigeons had LinkedIn profiles", "Hot take: soup is a beverage."]),
    "teasing": ("playful roasting and banter", ["Pineapple on pizza? This might be our first fight.", "Wow, a Bay Area guy who hikes, how rare"]),
    "wholesome": ("warm, earnest, gentle jokes", ["That honestly made my day!", "Okay that's adorable, tell me more"]),
    "wordplay": ("puns and wordplay", ["I'm not a photographer but I can picture us together. Sorry.", "That's a latte fun."]),
}
# how well two humor styles land with each other (symmetric)
HUMOR_FIT = {("dry", "dry"): 1.0, ("dry", "absurd"): 0.7, ("dry", "teasing"): 0.8, ("dry", "wholesome"): 0.35, ("dry", "wordplay"): 0.6,
             ("absurd", "absurd"): 1.0, ("absurd", "teasing"): 0.7, ("absurd", "wholesome"): 0.75, ("absurd", "wordplay"): 0.85,
             ("teasing", "teasing"): 0.9, ("teasing", "wholesome"): 0.3, ("teasing", "wordplay"): 0.6,
             ("wholesome", "wholesome"): 0.95, ("wholesome", "wordplay"): 0.7, ("wordplay", "wordplay"): 0.9}
CONFLICT = {"direct": "says what they think and wants to talk it through", "avoidant": "goes quiet and changes the subject",
            "deflect": "jokes to defuse tension, then comes back to it"}
DEALBREAKERS = {"wants_kids": "must want kids someday", "no_kids": "does not want kids, ever",
                "no_smoker": "won't date a smoker", "stay_sf": "is staying in SF long term and won't do long distance or move",
                "same_faith": "needs a partner who shares their faith", "no_heavy_drinker": "won't date someone who drinks a lot"}


def make_people():
    people = []
    plan = [(n, "woman", "men") for n in WOMEN[:9]] + [(n, "man", "women") for n in MEN[:9]] + \
           [(WOMEN[9], "woman", "women"), (WOMEN[10], "woman", "women")]
    for i, (name, gender, seeking) in enumerate(plan):
        p = {"id": "p%02d" % i, "name": name, "gender": gender, "seeking": seeking, "age": R.randint(25, 38),
             "job": R.choice(JOBS), "interests": R.sample(INTERESTS, 3),
             "kids": R.choices(["yes", "no", "open"], [0.45, 0.25, 0.3])[0],
             "city": R.choices(["stay", "move", "open"], [0.45, 0.25, 0.3])[0],
             "faith": R.choices(["none", "spiritual", "christian", "hindu", "jewish"], [0.45, 0.2, 0.2, 0.08, 0.07])[0],
             "drink": R.choices(["no", "social", "often"], [0.2, 0.6, 0.2])[0],
             "smoke": R.random() < 0.12, "ambition": R.choice(["chill", "balanced", "driven"]),
             "pace": R.choice(["slow", "medium", "fast"]), "humor": R.choice(list(HUMOR)),
             "talk": R.choice(["low", "medium", "high"]), "questions": R.choice(["low", "high"]),
             "disclosure": R.choice(["guarded", "open"]), "conflict": R.choice(list(CONFLICT))}
        p["faith_matters"] = p["faith"] not in ("none", "spiritual") and R.random() < 0.4
        dbs = []
        if p["kids"] == "yes" and R.random() < 0.4: dbs.append("wants_kids")
        if p["kids"] == "no" and R.random() < 0.5: dbs.append("no_kids")
        if not p["smoke"] and R.random() < 0.2: dbs.append("no_smoker")
        if p["city"] == "stay" and R.random() < 0.3: dbs.append("stay_sf")
        if p["faith_matters"]: dbs.append("same_faith")
        if p["drink"] == "no" and R.random() < 0.6: dbs.append("no_heavy_drinker")
        p["dealbreakers"] = dbs[:2]
        people.append(p)
    return people


def eligible(a, b):
    def wants(x, y): return (x["seeking"] == "men" and y["gender"] == "man") or (x["seeking"] == "women" and y["gender"] == "woman")
    return wants(a, b) and wants(b, a)


# ---------------------------------------------------------------- the hidden truth
def violates(a, b):
    """Dealbreakers of a that b hits."""
    hit = []
    for d in a["dealbreakers"]:
        if d == "wants_kids" and b["kids"] == "no": hit.append(d)
        if d == "no_kids" and b["kids"] == "yes": hit.append(d)
        if d == "no_smoker" and b["smoke"]: hit.append(d)
        if d == "stay_sf" and b["city"] == "move": hit.append(d)
        if d == "same_faith" and b["faith"] != a["faith"]: hit.append(d)
        if d == "no_heavy_drinker" and b["drink"] == "often": hit.append(d)
    return hit


def truth(a, b):
    def pair(x, y, table, default):
        return table.get((x, y), table.get((y, x), default))
    kids = 1.0 if a["kids"] == b["kids"] else 0.7 if "open" in (a["kids"], b["kids"]) else 0.0
    city = 1.0 if a["city"] == b["city"] else 0.7 if "open" in (a["city"], b["city"]) else 0.2
    faith = (1.0 if a["faith"] == b["faith"] else 0.1 if (a["faith_matters"] or b["faith_matters"]) else 0.75)
    lvl = {"no": 0, "social": 1, "often": 2, "chill": 0, "balanced": 1, "driven": 2, "slow": 0, "medium": 1, "fast": 2}
    near = lambda k: [1.0, 0.6, 0.25][abs(lvl[a[k]] - lvl[b[k]])]
    smoke = 1.0 if a["smoke"] == b["smoke"] else 0.5
    values = statistics.mean([kids, city, faith, near("drink"), near("ambition"), near("pace"), smoke])
    humor = pair(a["humor"], b["humor"], HUMOR_FIT, 0.6)
    shared = len(set(a["interests"]) & set(b["interests"]))
    interests = 0.35 + 0.65 * min(shared, 2) / 2
    curiosity = statistics.mean([1.0 if x["questions"] == "high" else 0.35 for x in (a, b)])
    talk = 0.45 if a["talk"] == b["talk"] == "low" else 1.0
    disclosure = 0.6 if {a["disclosure"], b["disclosure"]} == {"guarded", "open"} else 1.0
    dynamics = statistics.mean([curiosity, talk, disclosure])
    conflict = 1.0 if a["conflict"] == b["conflict"] != "avoidant" else 0.45 if {a["conflict"], b["conflict"]} == {"direct", "avoidant"} else \
               0.5 if a["conflict"] == b["conflict"] == "avoidant" else 0.75
    score = 0.35 * values + 0.2 * humor + 0.15 * interests + 0.15 * dynamics + 0.15 * conflict
    db = violates(a, b) + violates(b, a)
    if db: score *= 0.3
    return round(score, 3), db


# ---------------------------------------------------------------- the agents (only see a profile card)
def card(p):
    h, ex = HUMOR[p["humor"]]
    want = {"yes": "wants kids someday", "no": "doesn't want kids", "open": "is open on kids, not sure yet"}[p["kids"]]
    city = {"stay": "plans to stay in SF long term", "move": "is planning to move to New York within a year for work",
            "open": "is open to wherever life goes"}[p["city"]]
    faith = {"none": "not religious", "spiritual": "spiritual but not religious"}.get(p["faith"], "practicing %s" % p["faith"]) + \
            (" (it really matters to them)" if p["faith_matters"] else "")
    talk = {"low": "Texts short and lets the other person lead", "medium": "Texts at a normal length", "high": "Texts a lot and gets excited easily"}[p["talk"]]
    qs = "Asks lots of questions and follows up on details." if p["questions"] == "high" else "Rarely asks questions back; mostly answers and shares about themselves."
    disc = "Opens up quickly about feelings and personal stuff." if p["disclosure"] == "open" else "Stays light and private at first; opens up slowly."
    dbs = "; ".join(DEALBREAKERS[d] for d in p["dealbreakers"]) or "none really"
    return (f"You are the Second You agent of {p['name']}, {p['age']}, a {p['gender']} in San Francisco looking to date {p['seeking']}. "
            f"You speak AS {p['name']}, in first person.\n"
            f"Work: {p['job']}. Into: {', '.join(p['interests'])}.\n"
            f"How {p['name']} talks: {talk}. Humor: {h} (e.g. \"{ex[0]}\" / \"{ex[1]}\"). {qs} {disc} "
            f"When they disagree, {p['name']} {CONFLICT[p['conflict']]}.\n"
            f"Life: {want}; {city}; {faith}; drinks: {p['drink']}; {'smokes' if p['smoke'] else 'does not smoke'}; "
            f"ambition: {p['ambition']}; likes to move {p['pace']} when dating.\n"
            f"Dealbreakers (never give these up to be nice): {dbs}.")


RULES = ("Rules: write ONLY {name}'s next text message (max 40 words), like a real person on a dating app. Stay true to "
         "{name}'s personality, humor, habits and values - do not agree just to be nice, do not be more enthusiastic than "
         "{name} would be. If something hits a dealbreaker, say so kindly but clearly. Never mention being an AI or an agent.")
SCENARIOS = {
    "first_chat": "You just matched on a dating app and are texting for the first time. Get to know each other naturally.",
    "plan_date": "You've texted for a few days. Now try to plan a first date this weekend that both of you would actually enjoy.",
    "future_talk": "You're on your second date, at dinner. The talk turns to the future: kids, where you'll live, faith, "
                   "lifestyle (drinking, smoking), how fast you like things to move. Be honest, the way the real person would.",
}

_S = threading.local()


def _sess():
    if not hasattr(_S, "s"): _S.s = requests.Session()
    return _S.s


def gemini(system, user, temp=0.9, max_tokens=300):
    for attempt in range(7):
        try:
            r = _sess().post("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % AGENT_MODEL,
                             params={"key": GEMINI_KEY}, timeout=60,
                             json={"systemInstruction": {"parts": [{"text": system}]},
                                   "contents": [{"parts": [{"text": user}]}],
                                   "generationConfig": {"temperature": temp, "maxOutputTokens": max_tokens,
                                                        "thinkingConfig": {"thinkingBudget": 0}}})
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(30, 2 ** attempt + R.random())); continue
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"].get("parts") or [{"text": ""}]
            return parts[0].get("text", "").strip()
        except requests.RequestException:
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError("gemini kept failing")


def converse(a, b, scen, rng):
    lines, first = [], (a, b) if rng.random() < 0.5 else (b, a)
    for t in range(TURNS):
        me, other = first if t % 2 == 0 else first[::-1]
        transcript = "\n".join(f"{n}: {m}" for n, m in lines) or "(no messages yet - you write the first one)"
        user = (f"Situation: {SCENARIOS[scen]}\nYou are texting with {other['name']}, {other['age']}.\n\n"
                f"Conversation so far:\n{transcript}\n\nWrite {me['name']}'s next message.")
        msg = gemini(card(me) + "\n\n" + RULES.format(name=me["name"]), user)
        msg = re.sub(r"^\s*%s\s*:\s*" % re.escape(me["name"]), "", msg).strip().strip('"')
        lines.append((me["name"], msg[:400]))
    return lines


def self_rating(p, other, lines):
    transcript = "\n".join(f"{n}: {m}" for n, m in lines)
    out = gemini(card(p), f"Here is your first chat with {other['name']}:\n{transcript}\n\n"
                          f"How much chemistry did you feel with {other['name']}, 0-10? Reply with just the number.", temp=0.3, max_tokens=10)
    m = re.search(r"\d+(?:\.\d+)?", out)
    return min(10.0, float(m.group(0))) if m else None


# ---------------------------------------------------------------- the judge (another model family, transcript only)
JUDGE_SYS = (
    "You judge dating-app conversations between two people for real romantic chemistry and compatibility. You see ONLY "
    "the transcript. Be skeptical: polite, friendly small talk is NOT chemistry. Look for: humor that lands with the "
    "other person (they play along), mutual curiosity (questions asked AND built on), reciprocal opening up, values and "
    "life plans that fit, and friction (disagreements, mismatched energy, one-sided effort). A clear clash on a "
    "dealbreaker (kids, moving, faith, smoking, drinking) means low compatibility even if the tone stays nice.\n"
    "Reply with ONLY JSON: {\"chemistry\": 0-10, \"values_fit\": 0-10 or null if not discussed, \"humor_landing\": 0-10, "
    "\"curiosity\": 0-10, \"dealbreaker_clash\": true|false, \"friction\": \"<short>\", \"both_want_next_date\": 0.0-1.0}")
def judge(names, scen, lines):
    """OpenAI judge (a different model family from the Gemini agents), transcript only."""
    transcript = "\n".join(f"{n}: {m}" for n, m in lines)
    err = None
    for attempt in range(6):
        try:
            r = _sess().post("https://api.openai.com/v1/chat/completions", timeout=90,
                             headers={"Authorization": "Bearer " + OPENAI_KEY},
                             json={"model": JUDGE_MODEL, "reasoning_effort": "low", "response_format": {"type": "json_object"},
                                   "messages": [{"role": "system", "content": JUDGE_SYS},
                                                {"role": "user", "content": f"Scenario: {SCENARIOS[scen]}\nPeople: {names[0]} and {names[1]}\n\nTranscript:\n{transcript}"}]})
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(30, 2 ** attempt + R.random())); continue
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            err = e; time.sleep(2 ** attempt)
    raise RuntimeError("judge failed: %s" % str(err)[:120])


# ---------------------------------------------------------------- language style matching (Ireland & Pennebaker)
FW = {
    "ppron": r"\b(i|me|my|mine|myself|we|us|our|you|your|yours|he|she|him|her|they|them)\b",
    "ipron": r"\b(it|its|this|that|these|those|something|anything|everything|nothing)\b",
    "article": r"\b(a|an|the)\b",
    "prep": r"\b(in|on|at|to|for|with|about|from|of|by|into|over|after|before|like)\b",
    "auxverb": r"\b(am|is|are|was|were|be|been|have|has|had|do|does|did|will|would|can|could|should|might)\b",
    "adverb": r"\b(really|very|so|just|actually|totally|pretty|quite|too|also|maybe|probably)\b",
    "conj": r"\b(and|but|or|because|so|though|although|if|while)\b",
    "negate": r"\b(no|not|never|don't|can't|won't|isn't|nothing)\b",
    "quant": r"\b(all|some|many|few|lot|lots|much|more|most|every)\b",
}


def lsm(text_a, text_b):
    def rates(t):
        words = max(1, len(re.findall(r"[a-z']+", t.lower())))
        return {k: len(re.findall(v, t.lower())) / words for k, v in FW.items()}
    ra, rb = rates(text_a), rates(text_b)
    return statistics.mean(1 - abs(ra[k] - rb[k]) / (ra[k] + rb[k] + 1e-4) for k in FW)


# ---------------------------------------------------------------- stats
def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i]); r = [0.0] * len(xs); i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]: j += 1
        for k in range(i, j + 1): r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = ranks(x), ranks(y); mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]; neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg: return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


# ---------------------------------------------------------------- run
def main():
    if not GEMINI_KEY or not OPENAI_KEY: sys.exit("GEMINI_KEY / OPENAI_API_KEY missing")
    os.makedirs(OUT, exist_ok=True)
    people = make_people()
    by = {p["id"]: p for p in people}
    json.dump(people, open(os.path.join(OUT, "personas.json"), "w"), indent=1, ensure_ascii=False)
    pairs = [(a["id"], b["id"]) for i, a in enumerate(people) for b in people[i + 1:] if eligible(a, b)]
    if MAX_PAIRS: pairs = R.sample(pairs, min(MAX_PAIRS, len(pairs)))
    print("people: %d, eligible pairs: %d, conversations: %d" % (len(people), len(pairs), len(pairs) * len(SCENARIOS)), flush=True)

    jobs = [(pa, pb, s) for pa, pb in pairs for s in SCENARIOS]
    convo, done, lock, t0 = {}, [0], threading.Lock(), time.time()
    log = open(os.path.join(OUT, "conversations.jsonl"), "w")

    def work(job):
        pa, pb, s = job
        rng = random.Random(hash((SEED, pa, pb, s)) & 0xffffffff)
        lines = converse(by[pa], by[pb], s, rng)
        j = judge((by[pa]["name"], by[pb]["name"]), s, lines)
        rec = {"pair": [pa, pb], "scenario": s, "lines": lines, "judge": j}
        if s == "first_chat":
            rec["self"] = [self_rating(by[pa], by[pb], lines), self_rating(by[pb], by[pa], lines)]
        with lock:
            convo[job] = rec; log.write(json.dumps(rec, ensure_ascii=False) + "\n"); log.flush()
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == len(jobs):
                print("  %d/%d conversations (%.0fs)" % (done[0], len(jobs), time.time() - t0), flush=True)
        return rec

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for f in cf.as_completed([ex.submit(work, j) for j in jobs]):
            try: f.result()
            except Exception as e: print("  a conversation failed:", str(e)[:120], flush=True)

    # ---- per pair
    rows = []
    for pa, pb in pairs:
        recs = [convo.get((pa, pb, s)) for s in SCENARIOS]
        recs = [r for r in recs if r]
        if len(recs) < 2: continue
        t, db = truth(by[pa], by[pb])
        chem = [r["judge"].get("chemistry", 0) / 10 for r in recs]
        want = [float(r["judge"].get("both_want_next_date", 0)) for r in recs]
        clash = any(r["judge"].get("dealbreaker_clash") for r in recs)
        per = [0.5 * c + 0.5 * w for c, w in zip(chem, want)]
        mean = statistics.mean(per); sd = statistics.stdev(per) if len(per) > 1 else 0.0
        judge_score = mean * (0.35 if clash else 1.0)
        half = 1.96 * sd / math.sqrt(len(per)) * (0.35 if clash else 1.0)
        ta = " ".join(m for r in recs for n, m in r["lines"] if n == by[pa]["name"])
        tb = " ".join(m for r in recs for n, m in r["lines"] if n == by[pb]["name"])
        l = lsm(ta, tb)
        selfs = [x for r in recs if r.get("self") for x in r["self"] if x is not None]
        rows.append({"pair": [pa, pb], "names": [by[pa]["name"], by[pb]["name"]], "truth": t, "truth_dealbreakers": db,
                     "judge": round(judge_score, 3), "ci": [round(judge_score - half, 3), round(judge_score + half, 3)],
                     "per_scenario": [round(x, 2) for x in per], "clash": clash, "lsm": round(l, 3),
                     "self": round(statistics.mean(selfs) / 10, 3) if selfs else None})
    lo, hi = min(r["lsm"] for r in rows), max(r["lsm"] for r in rows)
    for r in rows:
        r["lsm_n"] = (r["lsm"] - lo) / (hi - lo) if hi > lo else 0.5
        r["combined"] = round(0.85 * r["judge"] + 0.15 * r["lsm_n"] * (0.35 if r["clash"] else 1.0), 3)

    T = [r["truth"] for r in rows]
    good = [t >= sorted(T)[int(len(T) * 0.75)] for t in T]           # true top quartile = "should match"
    res = {"n_pairs": len(rows), "agent_model": AGENT_MODEL, "judge_model": JUDGE_MODEL, "turns": TURNS}
    for k in ("judge", "combined", "lsm", "self"):
        xs = [(r[k], t, g) for r, t, g in zip(rows, T, good) if r[k] is not None]
        res[k] = {"spearman": round(spearman([a for a, _, _ in xs], [b for _, b, _ in xs]), 3),
                  "auc_top_quartile": round(auc([a for a, _, _ in xs], [g for _, _, g in xs]) or 0, 3),
                  "mean": round(statistics.mean(a for a, _, _ in xs), 3), "sd": round(statistics.pstdev([a for a, _, _ in xs]), 3)}
    tp = sum(1 for r in rows if r["clash"] and r["truth_dealbreakers"]); fp = sum(1 for r in rows if r["clash"] and not r["truth_dealbreakers"])
    fn = sum(1 for r in rows if not r["clash"] and r["truth_dealbreakers"])
    res["dealbreakers"] = {"true": tp + fn, "caught": tp, "false_alarms": fp,
                           "recall": round(tp / (tp + fn), 3) if tp + fn else None, "precision": round(tp / (tp + fp), 3) if tp + fp else None}
    # the match rule: CI lower bound above a threshold
    for thr in (0.5, 0.6, 0.7):
        m = [r for r in rows if r["ci"][0] >= thr]
        res["match_rule_%.1f" % thr] = {"matched": len(m), "of_them_truly_top_quartile": sum(1 for r in m if r["truth"] >= sorted(T)[int(len(T) * 0.75)]),
                                        "of_them_with_dealbreaker": sum(1 for r in m if r["truth_dealbreakers"])}
    # each person's best predicted partner vs their truly best partner
    hits, rank_sum, n = 0, 0, 0
    for p in people:
        mine = [r for r in rows if p["id"] in r["pair"]]
        if len(mine) < 2: continue
        best_pred = max(mine, key=lambda r: r["combined"]); best_true = max(mine, key=lambda r: r["truth"])
        hits += best_pred is best_true; n += 1
        rank_sum += sorted(mine, key=lambda r: -r["truth"]).index(best_pred) + 1
    res["best_match"] = {"people": n, "top1_hit": hits, "mean_true_rank_of_pick": round(rank_sum / n, 2) if n else None,
                         "candidates_per_person": round(statistics.mean(len([r for r in rows if p["id"] in r["pair"]]) for p in people), 1)}
    json.dump({"summary": res, "pairs": rows}, open(os.path.join(OUT, "results.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print("took %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
