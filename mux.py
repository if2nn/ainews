#!/usr/bin/env python3
"""Concat video segments + build the audio bed (voice, code-synth pad, cut whooshes) -> final mp4.

Usage: mux.py WORKDIR OUT.mp4 [--no-music] [--no-sfx]
Music: no music files are downloaded. If WORKDIR/../music.* or ainews/assets/music/*.{mp3,wav,m4a} exists
it is used (ducked under the voice); otherwise a quiet original pad is synthesised in code (stdlib only).
SFX: ainews/assets/sfx (original procedural sounds from guizang-product-video-skill make_sfx.py).
"""
import json, os, sys, subprocess, math, wave, array, glob, random

HERE = os.path.dirname(os.path.abspath(__file__))


def synth_pad(path, total, cuts, sr=22050):
    """calm brief bed: Fmaj7-Am7-Cmaj7-G6 pad (2.4 s per chord) + soft 8th-note plucks, fades in/out."""
    n = int(total * sr)
    buf = array.array("f", [0.0]) * n
    hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)
    chords = [[53, 57, 60, 64], [57, 60, 64, 67], [48, 52, 55, 59], [55, 59, 62, 64]]
    seg = 2.4
    # pad: per chord, sines with slow attack/release (overlapping 0.6 s)
    for ci in range(int(total / seg) + 1):
        notes = chords[ci % 4]
        t0 = ci * seg
        s0, s1 = int(max(0, t0 - 0.3) * sr), min(n, int((t0 + seg + 0.6) * sr))
        for m in notes:
            f = hz(m)
            w = 2 * math.pi * f / sr
            for i in range(s0, s1):
                tt = i / sr - (t0 - 0.3)
                env = min(1.0, tt / 0.6) * min(1.0, max(0.0, (seg + 0.9 - tt) / 0.6))
                buf[i] += 0.055 * env * (math.sin(w * i) + 0.18 * math.sin(2 * w * i))
    # plucks: chord tones an octave up on 8th notes (100 bpm -> 0.3 s)
    step = 0.3
    rnd = random.Random(7)
    k = 0
    t = 0.0
    while t < total - 0.5:
        notes = chords[int(t / seg) % 4]
        m = notes[[0, 2, 1, 3, 2, 1, 3, 2][k % 8]] + 12
        f = hz(m); w = 2 * math.pi * f / sr
        a = 0.035 if k % 2 == 0 else 0.022
        s0 = int(t * sr)
        for i in range(s0, min(n, s0 + int(0.5 * sr))):
            tt = (i - s0) / sr
            buf[i] += a * math.exp(-tt * 9) * math.sin(w * tt * sr)
        k += 1
        t += step
    # global fade
    fi, fo = int(1.0 * sr), int(2.0 * sr)
    for i in range(min(fi, n)):
        buf[i] *= i / fi
    for i in range(min(fo, n)):
        buf[n - 1 - i] *= i / fo
    pcm = array.array("h", (max(-32767, min(32767, int(v * 32767))) for v in buf))
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(pcm.tobytes())


def main():
    work, out = sys.argv[1], sys.argv[2]
    tm = json.load(open(os.path.join(work, "timing.json")))
    shots, total = tm["shots"], tm["total"]
    # 1) video concat (segments share codec params -> stream copy)
    lst = os.path.join(work, "segments.txt")
    with open(lst, "w") as f:
        for i, s in enumerate(shots):
            f.write(f"file '{os.path.join(work, 'segments', f'{i:02d}_{s['id']}.mp4')}'\n")
    vid = os.path.join(work, "video_only.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", vid], check=True)
    # 2) audio inputs
    ins, filt, labels = [], [], []
    for i, s in enumerate(shots):
        ins += ["-i", os.path.join(work, "audio", s["id"] + ".wav")]
        ms = int(round(s["voice_at"] * 1000))
        filt.append(f"[{i}:a]aresample=48000,adelay={ms}:all=1[v{i}]")
        labels.append(f"[v{i}]")
    nv = len(shots)
    filt.append("".join(labels) + f"amix=inputs={nv}:normalize=0,apad,atrim=0:{total}[voice]")
    filt.append("[voice]asplit=2[vo][vsc]")
    idx = nv
    mix = ["[vo]"]
    music = None
    if "--no-music" not in sys.argv:
        cands = sorted(glob.glob(os.path.join(HERE, "assets", "music", "*.*")))
        if cands:
            music = cands[0]
        else:
            music = os.path.join(work, "pad.wav")
            if not os.path.exists(music) or abs(os.path.getsize(music) / 2 / 22050 - total) > 0.2:
                synth_pad(music, total, [s["start"] for s in shots])
        ins += ["-stream_loop", "-1", "-i", music]
        filt.append(f"[{idx}:a]aresample=48000,atrim=0:{total},volume=0.2,"
                    f"afade=t=out:st={max(0, total - 2):.2f}:d=2[mu]")
        filt.append("[mu][vsc]sidechaincompress=threshold=0.03:ratio=5:attack=30:release=350[mud]")
        mix.append("[mud]")
        idx += 1
    if "--no-sfx" not in sys.argv:
        sfx = []
        for i, s in enumerate(shots[1:], 1):
            sfx.append(("whoosh.wav", s["start"] - 0.12, 0.55))   # cut whoosh lands on the cut
            sfx.append(("click.wav", s["start"] + 0.05, 0.35))    # number block drop
        for j in range(len(shots) - 2):                            # intro TOC rows pop in
            sfx.append(("pop.wav", 0.55 + 0.22 * j, 0.22))
        sl = []
        for k, (name, at, g) in enumerate(sfx):
            ins += ["-i", os.path.join(HERE, "assets", "sfx", name)]
            filt.append(f"[{idx}:a]aresample=48000,volume={g},adelay={int(max(0, at) * 1000)}:all=1[x{k}]")
            sl.append(f"[x{k}]")
            idx += 1
        filt.append("".join(sl) + f"amix=inputs={len(sl)}:normalize=0,apad,atrim=0:{total}[sfx]")
        mix.append("[sfx]")
    filt.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0,atrim=0:{total},"
                "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
    aud = os.path.join(work, "audio_mix.m4a")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + ins + ["-filter_complex", ";".join(filt), "-map", "[aout]",
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2", aud], check=True)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", vid, "-i", aud, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", out], check=True)
    print(f"[mux] {out}  (music: {os.path.basename(music) if music else 'none'})")


if __name__ == "__main__":
    main()
