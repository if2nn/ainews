#!/usr/bin/env python3
"""Soniox TTS for every segment of script.json -> WORKDIR/audio/*.wav + timing.json.

Usage: tts.py WORKDIR [--force]
Needs SONIOX_KEY in env (put it in .env). The key is never printed.
Each segment: POST https://tts-rt.soniox.com/tts (pcm_s16le 24 kHz), trim leading/trailing silence,
write 48 kHz mono wav. Voice: $SONIOX_VOICE (preset name or your cloned voice id); falls back to preset "Adrian".
Shot length = LEAD + speech + TAIL (min MIN_SHOT), snapped to whole frames.
"""
import json, os, subprocess, sys, time, math

URL = "https://tts-rt.soniox.com/tts"
VOICE = os.environ.get("SONIOX_VOICE", "Adrian")  # preset voice, or your own cloned voice id
FALLBACK_VOICE = "Adrian"
FPS = 30
LEAD, TAIL, MIN_SHOT = 0.30, 0.50, 3.0
SPEED = float(os.environ.get("AINEWS_TTS_SPEED", "1.10"))  # atempo


def tts(text, voice, out_pcm):
    key = os.environ["SONIOX_KEY"]
    body = json.dumps({"model": "tts-rt-v2", "language": "zh", "voice": voice,
                       "audio_format": "pcm_s16le", "sample_rate": 24000, "text": text})
    r = subprocess.run(["curl", "-s", "--max-time", "60", "-o", out_pcm, "-w", "%{http_code}", "-X", "POST", URL,
                        "-H", "Authorization: Bearer " + key, "-H", "Content-Type: application/json",
                        "-d", "@-"], input=body.encode(), capture_output=True)
    code = r.stdout.decode().strip()
    ok = code == "200" and os.path.exists(out_pcm) and os.path.getsize(out_pcm) > 4800
    if not ok and os.path.exists(out_pcm):
        err = open(out_pcm, "rb").read(200)
        print(f"[tts]   HTTP {code} {err[:120]!r}")
    return ok


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", path]).decode().strip())


def main():
    work = sys.argv[1]
    force = "--force" in sys.argv
    sc = json.load(open(os.path.join(work, "script.json")))
    adir = os.path.join(work, "audio"); os.makedirs(adir, exist_ok=True)
    segs = [("intro", sc["intro"]["narration"])] + \
           [(f"s{k + 1:02d}", s["narration"]) for k, s in enumerate(sc["stories"])] + \
           [("outro", sc["outro"]["narration"])]
    old = {}
    tpath = os.path.join(work, "timing.json")
    if os.path.exists(tpath):
        old = {s["id"]: s for s in json.load(open(tpath))["shots"]}
    shots, t = [], 0.0
    for sid, text in segs:
        wav = os.path.join(adir, sid + ".wav")
        reuse = (not force and old.get(sid, {}).get("speed") == SPEED and os.path.exists(wav) and old.get(sid, {}).get("text") == text)
        voice = old.get(sid, {}).get("voice", VOICE)
        if not reuse:
            pcm = os.path.join(adir, sid + ".pcm")
            voice = VOICE
            ok = False
            for attempt in range(3):
                if tts(text, VOICE, pcm):
                    ok = True; break
                time.sleep(2)
            if not ok:
                print(f"[tts] {sid}: clone voice failed, using preset {FALLBACK_VOICE}")
                voice = FALLBACK_VOICE
                if not tts(text, FALLBACK_VOICE, pcm):
                    sys.exit(f"[tts] {sid}: TTS failed with both voices")
            # trim silence at both ends (keep 40 ms), resample to 48 kHz
            trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,"
                    "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06,areverse,"
                    f"atempo={SPEED}")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", pcm,
                            "-af", trim, "-ar", "48000", wav], check=True)
            os.remove(pcm)
        d = dur(wav)
        shot = max(MIN_SHOT, LEAD + d + TAIL)
        frames = math.ceil(shot * FPS)
        shots.append({"id": sid, "text": text, "voice": voice, "speed": SPEED, "speech": round(d, 3), "start": round(t, 4),
                      "frames": frames, "dur": frames / FPS, "voice_at": round(t + LEAD, 4)})
        t += frames / FPS
        print(f"[tts] {sid}: speech {d:5.2f}s  shot {frames / FPS:5.2f}s  {'(cached)' if reuse else ''}")
    json.dump({"fps": FPS, "total": round(t, 3), "shots": shots}, open(tpath, "w"), ensure_ascii=False, indent=1)
    print(f"[tts] total {t:.2f}s")


if __name__ == "__main__":
    main()
