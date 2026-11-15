"""Demo-video generation for the VexoHacks entry: reference images (Nano Banana Pro), clips (Gemini Omni 1.2 Flash),
voiceover (Gemini TTS). The API key is read from ~/.attention/vexohacks_gemini_key (never printed).

    python3 gen.py image <name> "<prompt>" [ref.png ...]
    python3 gen.py video <name> "<prompt>" [--dur 8] [--ar 16:9] [--res 720p] [ref.png ...]
    python3 gen.py tts <name> "<text>" [--voice Kore]
Outputs land in out/.
"""
import base64, json, os, sys, time, urllib.request, urllib.error

KEY = open(os.path.expanduser("~/.attention/vexohacks_gemini_key")).read().strip()
BASE = "https://generativelanguage.googleapis.com/v1beta"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)


def post(path, body, timeout=600):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:600]
            if e.code in (429, 500, 503) and attempt < 3:
                print("  retry after", e.code, msg[:120]); time.sleep(5 * (attempt + 1)); continue
            raise SystemExit("HTTP %d: %s" % (e.code, msg))


def img_part(path):
    mime = "image/png" if path.endswith(".png") else "image/jpeg"
    return base64.b64encode(open(path, "rb").read()).decode(), mime


def image(name, prompt, refs):
    parts = [{"inline_data": {"mime_type": m, "data": d}} for d, m in map(img_part, refs)] + [{"text": prompt}]
    r = post("/models/gemini-3-pro-image:generateContent",
             {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"]}})
    for p in r["candidates"][0]["content"]["parts"]:
        data = p.get("inlineData") or p.get("inline_data")
        if data:
            path = os.path.join(OUT, name + ".png")
            open(path, "wb").write(base64.b64decode(data["data"])); print(path); return path
    raise SystemExit("no image in reply: " + json.dumps(r)[:400])


def video(name, prompt, refs, dur="8s", ar="16:9", res="720p"):
    if refs:
        inp = [{"type": "image", "data": d, "mime_type": m} for d, m in map(img_part, refs)] + [{"type": "text", "text": prompt}]
    else:
        inp = prompt
    t0 = time.time()
    r = post("/interactions", {"model": "gemini-omni-1.2-flash", "input": inp,
                                "response_format": {"type": "video", "aspect_ratio": ar, "resolution": res, "duration": dur}})
    for step in r.get("steps", []):
        for c in step.get("content", []) or []:
            if c.get("type") == "video" and c.get("data"):
                path = os.path.join(OUT, name + ".mp4")
                open(path, "wb").write(base64.b64decode(c["data"]))
                print("%s (%.0fs, status %s)" % (path, time.time() - t0, r.get("status"))); return path
    raise SystemExit("no video in reply: " + json.dumps({k: v for k, v in r.items() if k != "steps"})[:400]
                     + " steps: " + json.dumps(r.get("steps"))[:600])


def tts(name, text, voice="Kore"):
    r = post("/models/gemini-3.8-flash-tts:generateContent",
             {"contents": [{"parts": [{"text": text}]}],
              "generationConfig": {"responseModalities": ["AUDIO"],
                                   "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}})
    p = r["candidates"][0]["content"]["parts"][0]
    data = p.get("inlineData") or p.get("inline_data")
    raw = os.path.join(OUT, name + ".pcm"); open(raw, "wb").write(base64.b64decode(data["data"]))
    wav = os.path.join(OUT, name + ".wav")      # 24 kHz 16-bit mono PCM -> wav
    os.system('ffmpeg -loglevel error -y -f s16le -ar 24000 -ac 1 -i "%s" "%s"' % (raw, wav)); os.remove(raw)
    print(wav); return wav


if __name__ == "__main__":
    kind, name, prompt, rest = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    opts, refs, i = {}, [], 0
    while i < len(rest):
        if rest[i].startswith("--"): opts[rest[i][2:]] = rest[i + 1]; i += 2
        else: refs.append(rest[i]); i += 1
    if kind == "image": image(name, prompt, refs)
    elif kind == "video": video(name, prompt, refs, opts.get("dur", "8") + "s", opts.get("ar", "16:9"), opts.get("res", "720p"))
    elif kind == "tts": tts(name, prompt, opts.get("voice", "Kore"))
