"""Cut the demo: AI story clips + UI stills on one timeline, voiceover placed per beat, ambient under it, subtitles."""
import os, subprocess, json

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT, SHOTS, BUILD = os.path.join(ROOT, "out"), os.path.join(ROOT, "ui", "shots"), os.path.join(ROOT, "build")
os.makedirs(BUILD, exist_ok=True)

def run(cmd): subprocess.run(cmd, check=True)
def dur(p): return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).decode())

# (kind, source, seconds or None for the clip's own length)
TIMELINE = [("clip", "s1_pass", None), ("clip", "s2_glow", None), ("clip", "s3_life", None),
            ("still", "a1", 3), ("still", "a2", 4), ("still", "a3", 4), ("still", "a4", 4.5),
            ("clip", "s4_notify", None), ("still", "b1", 2.5), ("still", "b1t", 1), ("still", "b2", 4),
            ("still", "c", 14.5), ("still", "d1", 3), ("still", "d1t", 1), ("still", "d2", 3),
            ("clip", "s6_ride", None), ("clip", "s5_date", None), ("still", "e", 5),
            ("clip", "s7_after", None), ("clip", "s8_tap", None), ("clip", "s9_recv", None), ("clip", "s10_end", None),
            ("still", "end", 7)]
# voiceover: (file, starts with this timeline item, delay into it, text)
VO = [("vo1", "s1_pass", 0.8, "What if your AI already knew you'd click with someone — before you said a word?"),
      ("vo2", "s3_life", 0.3, "Every conversation trains your Second You — an agent that learns how you talk, what you value, and what you won't compromise on."),
      ("vo3", "a1", 0.4, "Agents meet first. They test chemistry across a first chat, planning a date, even the hard questions — kids, faith, where to live. Your photos and identity stay hidden."),
      ("vo4", "s4_notify", 1.0, "Only when confidence is high does it reach you. And only if you both say yes, do you see each other."),
      ("vo5", "c", 0.5, "In 246 simulated agent dates, our independent judge ranked real chemistry at 0.73 correlation, and caught 41 of 43 dealbreakers."),
      ("vo6", "d1", 0.3, "Your agent plans the first date — the restaurant, the time, the ride. You just confirm, and show up."),
      ("vo7", "s5_date", 0.6, "With both your consent, it listens. Afterwards, you and your agent each rate the date. Great score? It plans the next one."),
      ("vo8", "s8_tap", 1.0, "And when you're apart — two taps. They know you're thinking of them."),
      ("vo9", "end", 0.5, "Second You. Your agent finds them. You fall in love.")]

# 1. voiceover: trim silence at both ends, a touch faster
vo_len = {}
for name, *_ in VO:
    src, dst = os.path.join(OUT, name + ".wav"), os.path.join(BUILD, name + ".wav")
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-af",
         "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,atempo=1.07",
         "-ar", "48000", "-ac", "2", dst])
    vo_len[name] = dur(dst)

# 2. every timeline item as a normalized segment (1280x720, 30 fps, stereo 48 kHz; stills silent)
segs, starts, t = [], {}, 0.0
for i, (kind, src, secs) in enumerate(TIMELINE):
    seg = os.path.join(BUILD, "seg%02d.mp4" % i)
    if kind == "clip":
        p = os.path.join(OUT, src + ".mp4"); secs = dur(p)
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", p, "-vf", "scale=1280:720,fps=30,format=yuv420p",
             "-af", "highpass=f=90,lowpass=f=9000,afftdn=nf=-25,volume=0.09,aresample=48000", "-ac", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-c:a", "aac", "-b:a", "160k", "-t", "%.3f" % secs, seg])
    else:
        p = os.path.join(SHOTS, src + ".png")
        run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", p, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-vf", "scale=1280:720,fps=30,format=yuv420p", "-t", "%.3f" % secs, "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-c:a", "aac", "-b:a", "160k", "-shortest", seg])
    starts[src] = t; t += secs; segs.append(seg)
total = t

# 3. place the voiceover; never let two lines overlap
placed, last_end = [], 0.0
for name, at, delay, text in VO:
    s = max(starts[at] + delay, last_end + 0.35)
    placed.append((name, s, text)); last_end = s + vo_len[name]
if last_end + 1.0 > total:      # the last line runs past the end card: hold the end card longer
    extra = last_end + 1.0 - total
    run(["ffmpeg", "-loglevel", "error", "-y", "-stream_loop", "-1", "-i", segs[-1], "-t", "%.3f" % (dur(segs[-1]) + extra),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", segs[-1] + ".long.mp4"])
    os.replace(segs[-1] + ".long.mp4", segs[-1]); total += extra

# 4. join the picture + ambient
lst = os.path.join(BUILD, "list.txt")
open(lst, "w").write("".join("file '%s'\n" % s for s in segs))
base = os.path.join(BUILD, "base.mp4")
run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", base])

# 5. (an .srt too, for platforms that take one)
def ts(x): h, r = divmod(x, 3600); m, s = divmod(r, 60); return "%02d:%02d:%06.3f" % (h, m, s)
srt, n = [], 1
for name, s, text in placed:
    chunks = [c.strip() for c in text.replace("? ", "?|").replace(". ", ".|").split("|") if c.strip()]
    L = vo_len[name]; total_chars = sum(len(c) for c in chunks); cur = s
    for c in chunks:
        d = L * len(c) / total_chars
        srt.append("%d\n%s --> %s\n%s\n" % (n, ts(cur).replace(".", ","), ts(cur + d).replace(".", ","), c)); n += 1; cur += d
open(os.path.join(BUILD, "subs.srt"), "w").write("\n".join(srt))

# 6. caption images (rendered by caption.html in the browser: build/caps/capNN.png), then mix and overlay
cues = []
for name, st, text in placed:
    chunks = [c.strip() for c in text.replace("? ", "?|").replace(". ", ".|").split("|") if c.strip()]
    L = vo_len[name]; total_chars = sum(len(c) for c in chunks); cur = st
    for c in chunks:
        d = L * len(c) / total_chars; cues.append({"text": c, "start": round(cur, 2), "end": round(cur + d, 2)}); cur += d
json.dump(cues, open(os.path.join(BUILD, "cues.json"), "w"), ensure_ascii=False)
caps = os.path.join(BUILD, "caps")
if not os.path.exists(os.path.join(caps, "cap%02d.png" % (len(cues) - 1))):
    print("CUES_READY", len(cues)); raise SystemExit(0)

inputs, filters = ["-i", base], []
for i, (name, st, _) in enumerate(placed):
    inputs += ["-i", os.path.join(BUILD, name + ".wav")]
    ms = int(st * 1000)
    filters.append("[%d:a]highpass=f=70,adelay=%d|%d,volume=1.0[v%d]" % (i + 1, ms, ms, i))
k0 = len(placed) + 1
for j in range(len(cues)):
    inputs += ["-i", os.path.join(caps, "cap%02d.png" % j)]
mix = "[0:a]" + "".join("[v%d]" % i for i in range(len(placed))) + "amix=inputs=%d:duration=first:normalize=0,loudnorm=I=-16:TP=-2:LRA=9,alimiter=limit=0.7:level=false,afade=t=out:st=%.2f:d=1.5[a]" % (len(placed) + 1, total - 1.5)
chain, last = [], "[0:v]"
for j, c in enumerate(cues):
    out = "[o%d]" % j
    chain.append("%s[%d:v]overlay=x=0:y=H-h-22:enable='between(t,%.2f,%.2f)'%s" % (last, k0 + j, c["start"], c["end"], out)); last = out
chain.append("%sfade=t=in:st=0:d=0.8,fade=t=out:st=%.2f:d=1.5[v]" % (last, total - 1.5))
final = os.path.join(ROOT, "SecondYou_VexoHacks_demo.mp4")
run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(filters + [mix] + chain),
     "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-c:a", "aac", "-b:a", "192k",
     "-movflags", "+faststart", final])
print(json.dumps({"total_seconds": round(total, 1), "vo": [(n, round(st, 1), round(vo_len[n], 1)) for n, st, _ in placed]}))
print(final)
