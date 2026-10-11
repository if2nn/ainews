#!/usr/bin/env python3
"""Automatic checks + 2 fps contact sheets for the final video.

Usage: qa.py WORKDIR VIDEO.mp4 [--asr]
Writes WORKDIR/qa/{contact_1.jpg,...,qa_report.json}. Look at the contact sheets yourself afterwards:
automatic checks prove structure, not taste.
--asr  sends the mixed audio to Soniox async ASR (cloud, SONIOX_KEY) and diffs it against the script
       to catch TTS misreadings.
"""
import json, os, re, subprocess, sys, difflib, time

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(video):
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
             "-of", "json", video])
    return json.loads(r.stdout)


def contact_sheets(video, outdir, cols=10, rows=4):
    # 2 fps, 108x192 thumbs, timestamp burned in; 40 thumbs (20 s) per sheet
    pat = os.path.join(outdir, "contact_%d.jpg")
    vf = (f"fps=2,scale=216:384,drawtext=fontfile={HERE}/fonts/NotoSansSC-Bold.otf:text='%{{pts\\:hms}}':"
          f"x=6:y=6:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6,tile={cols}x{rows}:padding=4:color=gray")
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", vf, "-q:v", "3", pat])
    return sorted(f for f in os.listdir(outdir) if f.startswith("contact_"))


def asr_check(work, video, script_text):
    key = os.environ.get("SONIOX_KEY")
    if not key:
        return {"skipped": "no SONIOX_KEY"}
    B = "https://api.soniox.com/v1"
    H = ["-H", "Authorization: Bearer " + key]
    wav = os.path.join(work, "qa", "asr.mp3")
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", wav])
    j = lambda r: json.loads(r.stdout or "{}")
    models = j(run(["curl", "-s", *H, B + "/models"])).get("models", [])
    model = next((m["id"] for m in models if m.get("transcription_mode") == "async"), None)
    if not model:
        return {"error": "no async model"}
    fid = j(run(["curl", "-s", *H, "-F", f"file=@{wav}", B + "/files"])).get("id")
    body = json.dumps({"file_id": fid, "model": model, "language_hints": ["zh", "en"]})
    tid = j(run(["curl", "-s", *H, "-H", "Content-Type: application/json", "-d", body, B + "/transcriptions"])).get("id")
    st = {}
    for _ in range(60):
        st = j(run(["curl", "-s", *H, f"{B}/transcriptions/{tid}"]))
        if st.get("status") in ("completed", "error"):
            break
        time.sleep(2)
    txt = j(run(["curl", "-s", *H, f"{B}/transcriptions/{tid}/transcript"])).get("text", "")
    run(["curl", "-s", "-X", "DELETE", *H, f"{B}/transcriptions/{tid}"])
    run(["curl", "-s", "-X", "DELETE", *H, f"{B}/files/{fid}"])
    norm = lambda s: re.sub(r"[\s，。、；：？！,.!?\"'“”]", "", s).lower()
    a, b = norm(script_text), norm(txt)
    sm = difflib.SequenceMatcher(None, a, b)
    diffs = [(a[i1:i2], b[j1:j2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    return {"status": st.get("status"), "similarity": round(sm.ratio(), 3), "transcript": txt,
            "diffs_script_vs_heard": diffs[:40]}


def main():
    work, video = sys.argv[1], sys.argv[2]
    qd = os.path.join(work, "qa"); os.makedirs(qd, exist_ok=True)
    tm = json.load(open(os.path.join(work, "timing.json")))
    sc = json.load(open(os.path.join(work, "script.json")))
    p = probe(video)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    a = [s for s in p["streams"] if s["codec_type"] == "audio"]
    dur = float(p["format"]["duration"])
    rep = {"video": video, "duration": round(dur, 2), "size_mb": round(int(p["format"]["size"]) / 1e6, 2),
           "width": v["width"], "height": v["height"], "fps": v["r_frame_rate"],
           "audio": a[0] if a else None, "problems": []}
    if (v["width"], v["height"]) != (1080, 1920):
        rep["problems"].append("resolution not 1080x1920")
    if v["r_frame_rate"] != "30/1":
        rep["problems"].append("fps not 30")
    if not a:
        rep["problems"].append("no audio track")
    if not 45 <= dur <= 75:
        rep["problems"].append(f"duration {dur:.1f}s outside 45-75 s")
    if abs(dur - tm["total"]) > 0.15:
        rep["problems"].append(f"duration {dur:.2f} != timeline {tm['total']:.2f}")
    # black frames
    r = run(["ffmpeg", "-v", "info", "-i", video, "-vf", "blackdetect=d=0.1:pix_th=0.08", "-an", "-f", "null", "-"])
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)
    rep["black_segments"] = blacks
    if blacks:
        rep["problems"].append(f"black frames: {blacks}")
    # loudness + silence: every shot must contain speech after voice_at
    r = run(["ffmpeg", "-v", "info", "-i", video, "-af", "ebur128", "-vn", "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    rep["integrated_lufs"] = float(m[-1]) if m else None
    r = run(["ffmpeg", "-v", "info", "-i", video, "-af", "silencedetect=n=-40dB:d=1.2", "-vn", "-f", "null", "-"])
    rep["long_silences"] = re.findall(r"silence_start: ([\d.]+)", r.stderr)
    shot_rep = []
    for s in tm["shots"]:
        seg = run(["ffmpeg", "-v", "info", "-ss", str(s["voice_at"]), "-t", str(max(0.5, s["speech"])), "-i", video,
                   "-af", "volumedetect", "-vn", "-f", "null", "-"])
        mv = re.search(r"mean_volume: (-?[\d.]+)", seg.stderr)
        mean = float(mv.group(1)) if mv else -99
        shot_rep.append({"id": s["id"], "start": s["start"], "dur": round(s["dur"], 2), "speech": s["speech"],
                         "mean_db_during_speech": mean})
        if mean < -35:
            rep["problems"].append(f"{s['id']}: no audible speech in its window")
        if s["voice_at"] + s["speech"] > s["start"] + s["dur"]:
            rep["problems"].append(f"{s['id']}: speech overruns its shot")
    rep["shots"] = shot_rep
    lw = os.path.join(work, "layout_warnings.json")
    if os.path.exists(lw):
        for k, ws in json.load(open(lw)).items():
            rep["problems"] += ws
    rep["contact_sheets"] = [os.path.join(qd, f) for f in contact_sheets(video, qd)]
    if "--asr" in sys.argv:
        text = "".join([sc["intro"]["narration"]] + [s["narration"] for s in sc["stories"]] + [sc["outro"]["narration"]])
        rep["asr"] = asr_check(work, video, text)
    json.dump(rep, open(os.path.join(qd, "qa_report.json"), "w"), ensure_ascii=False, indent=1)
    print(f"[qa] {rep['width']}x{rep['height']} {rep['fps']} {rep['duration']}s {rep['size_mb']}MB "
          f"LUFS={rep['integrated_lufs']} audio={'yes' if a else 'NO'}")
    if "asr" in rep:
        print(f"[qa] ASR similarity {rep['asr'].get('similarity')}  diffs: {rep['asr'].get('diffs_script_vs_heard')}")
    print("[qa] problems:", rep["problems"] or "none")
    for c in rep["contact_sheets"]:
        print("[qa] contact sheet:", c)


if __name__ == "__main__":
    main()
