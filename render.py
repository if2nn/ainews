#!/usr/bin/env python3
"""Render the video track (no audio) with Pillow -> ffmpeg, one mp4 segment per shot.

Usage: render.py WORKDIR [--shots 0-3] [--still]
  --shots a-b   render only those shot indices (0 = intro); lets long renders be split up
  --still       only write one PNG per shot (at 75% of its length) to WORKDIR/stills for layout review
Design: 报纸/电讯稿 brief. Warm white #fafaf9 / charcoal #202020, Noto Sans SC + Noto Serif SC,
one shot = one story: number block, category, EN eyebrow, ZH headline, attached picture card with caption,
key figure, karaoke subtitle of the narration, source line. Top: masthead + progress rail.
"""
import json, os, re, subprocess, sys, math, io, hashlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FD = os.path.join(HERE, "fonts")
W, H, FPS = 1080, 1920, 30
MX = 84                      # side margin
CW = W - 2 * MX              # content width 912
SAFE_BOTTOM = 1670           # nothing below this (platform UI)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

TONES = {
    "light": dict(bg=(250, 250, 249), fg=(37, 37, 37), sub=(108, 102, 94), line=(230, 225, 219),
                  dim=(138, 131, 122), dot=(37, 37, 37, 13), card=(255, 255, 255), kara=(190, 184, 176),
                  block=(37, 37, 37), blockfg=(250, 250, 249)),
    "dark": dict(bg=(32, 32, 32), fg=(250, 250, 249), sub=(186, 181, 174), line=(62, 60, 57),
                 dim=(150, 144, 136), dot=(250, 250, 249, 12), card=(44, 44, 43), kara=(110, 106, 100),
                 block=(250, 250, 249), blockfg=(32, 32, 32)),
}

_fc = {}


def font(name, size):
    k = (name, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(os.path.join(FD, name), size)
    return _fc[k]


SANS_B, SANS_R, SANS_K = "NotoSansSC-Bold.otf", "NotoSansSC-Regular.otf", "NotoSansSC-Black.otf"
SERIF_B, SERIF_R = "NotoSerifSC-Bold.otf", "NotoSerifSC-Regular.otf"

# ---------------------------------------------------------------- easing
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def expo_out(x):
    x = clamp(x)
    return 1 - 2 ** (-10 * x) if x < 1 else 1.0


def p2_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 2


def p1_inout(x):
    x = clamp(x)
    return 0.5 - 0.5 * math.cos(math.pi * x)


# ---------------------------------------------------------------- text helpers
NO_START = set("，。、；：？！）》」』”’,.;:?!)%")


def tokens(text):
    # latin words / numbers stay whole; CJK split per char
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-+/&'%→]*|\s+|.", text)


def wrap(text, fnt, maxw):
    lines, cur = [], ""
    for tok in tokens(text):
        trial = cur + tok
        if fnt.getlength(trial) <= maxw or not cur.strip():
            cur = trial
            continue
        if tok in NO_START:            # kinsoku: punctuation sticks to previous line
            cur = trial
            continue
        lines.append(cur.rstrip())
        cur = tok.lstrip()
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def headline(text, maxw):
    """single line if it fits at >=72px, else a balanced 2-line split (no orphans), else plain wrap."""
    for size in (80, 76, 72):
        if font(SANS_B, size).getlength(text) <= maxw:
            return font(SANS_B, size), [text]
    toks = tokens(text)
    for size in (80, 72, 64):
        f = font(SANS_B, size)
        best = None
        for i in range(1, len(toks)):
            if toks[i] in NO_START:
                continue
            a, b = "".join(toks[:i]).rstrip(), "".join(toks[i:]).lstrip()
            wa, wb = f.getlength(a), f.getlength(b)
            if wa > maxw or wb > maxw or not a or not b:
                continue
            # prefer balanced lines, and breaks at a space / script change
            score = max(wa, wb) - (40 if toks[i - 1].isspace() or toks[i].isspace() else 0)
            if best is None or score < best[0]:
                best = (score, [a, b])
        if best:
            return f, best[1]
    f = font(SANS_B, 64)
    return f, wrap(text, f, maxw)


def text_layer(lines, fnt, color, lh, align="left", width=None):
    asc, desc = fnt.getmetrics()
    width = width or int(max(fnt.getlength(l) for l in lines)) + 4
    h = int(lh * (len(lines) - 1) + asc + desc) + 4
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        x = 0 if align == "left" else (width - fnt.getlength(l)) / 2
        d.text((x, i * lh), l, font=fnt, fill=color)
    return im


def spaced(text, fnt, color, tracking):
    """single line with letter spacing (for EN caps eyebrows / labels)"""
    wds = [fnt.getlength(c) for c in text]
    w = int(sum(wds) + tracking * (len(text) - 1)) + 4
    asc, desc = fnt.getmetrics()
    im = Image.new("RGBA", (max(w, 1), asc + desc + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 0
    for c, cw in zip(text, wds):
        d.text((x, 0), c, font=fnt, fill=color)
        x += cw + tracking
    return im


def fit_one_line(text, name, size, maxw, minsize):
    while size > minsize and font(name, size).getlength(text) > maxw:
        size -= 2
    return font(name, size)


# ---------------------------------------------------------------- images
def fetch_image(url, cache):
    os.makedirs(cache, exist_ok=True)
    p = os.path.join(cache, hashlib.md5(url.encode()).hexdigest()[:12] + ".img")
    if not os.path.exists(p):
        subprocess.run(["curl", "-sL", "--max-time", "40", "-A", UA, "-o", p, url])
    try:
        im = Image.open(p)
        im.seek(0)                      # first frame of gifs
        return im.convert("RGB")
    except Exception:
        return None


def cover(im, w, h):
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


# ---------------------------------------------------------------- elements
class El:
    """A pre-rendered RGBA layer with a simple entrance animation."""

    def __init__(self, im, x, y, t0=0.0, dur=0.5, kind="fadeup", dy=28):
        self.im, self.x, self.y, self.t0, self.dur, self.kind, self.dy = im, int(x), int(y), t0, dur, kind, dy

    @property
    def box(self):
        return (self.x, self.y, self.x + self.im.width, self.y + self.im.height)

    def draw(self, frame, t):
        p = (t - self.t0) / self.dur
        if p <= 0:
            return
        e = expo_out(p)
        im = self.im
        x, y = self.x, self.y
        if self.kind == "fadeup":
            y = self.y + round(self.dy * (1 - e))
        elif self.kind == "drop":
            y = self.y - round(self.dy * (1 - e))
        elif self.kind == "slide":            # enter from the right, clipped to its own box
            off = round((1 - e) * im.width * 0.35)
            if off > 0:
                im = im.crop((0, 0, im.width - off, im.height))
                x = self.x + off
        elif self.kind == "wipe":             # reveal left->right
            w = max(1, round(im.width * e))
            im = im.crop((0, 0, w, im.height))
        a = 1.0 if self.kind == "wipe" else e
        if a < 0.999:
            im = im.copy()
            alpha = im.getchannel("A").point(lambda v: int(v * a))
            im.putalpha(alpha)
        frame.alpha_composite(im, (x, max(0, y)))


def paper(tone):
    T = TONES[tone]
    bg = Image.new("RGBA", (W, H), T["bg"] + (255,))
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(dots)
    for yy in range(12, H, 24):
        for xx in range(12, W, 24):
            d.point((xx, yy), fill=T["dot"])
            d.point((xx + 1, yy), fill=T["dot"])
    bg.alpha_composite(dots)
    return bg


def masthead(base, tone, sc, idx, n):
    T = TONES[tone]
    d = ImageDraw.Draw(base)
    f1 = font(SERIF_B, 34)
    d.text((MX, 86), "AI 早报", font=f1, fill=T["fg"])
    x = MX + f1.getlength("AI 早报") + 18
    base.alpha_composite(spaced("DAILY BRIEF", font(SERIF_R, 22), T["dim"], 5), (int(x), 98))
    date = sc["date"].replace("-", ".") + "  " + sc.get("weekday", "")
    f2 = font(SANS_R, 24)
    d.text((W - MX - f2.getlength(date), 94), date, font=f2, fill=T["sub"])
    d.line((MX, 150, W - MX, 150), fill=T["fg"], width=3)
    d.line((MX, 157, W - MX, 157), fill=T["fg"], width=1)


def rail(frame, tone, idx, n, prog):
    """progress rail: one segment per shot, current one filling."""
    T = TONES[tone]
    d = ImageDraw.Draw(frame)
    gap, y, h = 8, 186, 6
    sw = (CW - gap * (n - 1)) / n
    for i in range(n):
        x0 = MX + i * (sw + gap)
        d.rectangle((x0, y, x0 + sw, y + h), fill=T["line"])
        if i < idx:
            d.rectangle((x0, y, x0 + sw, y + h), fill=T["fg"])
        elif i == idx:
            d.rectangle((x0, y, x0 + sw * clamp(prog), y + h), fill=T["fg"])


def source_line(base, tone, text):
    T = TONES[tone]
    d = ImageDraw.Draw(base)
    f = font(SANS_R, 24)
    y = 1628
    d.line((MX, y - 16, W - MX, y - 16), fill=T["line"], width=2)
    d.text((MX, y), "来源  " + text, font=f, fill=T["dim"])
    tag = "橘鸦 AI 早报"
    d.text((W - MX - f.getlength(tag), y), tag, font=f, fill=T["dim"])


class Karaoke:
    """narration subtitle: grey text darkens char by char with the voice."""

    def __init__(self, text, tone, x, y_bottom, t_on, t_voice, speech):
        T = TONES[tone]
        for size in (40, 37, 34):               # long narration: shrink to stay within 3 lines
            self.f = font(SANS_R, size)
            self.lines = wrap(text, self.f, CW)
            if len(self.lines) <= 3:
                break
        self.lh = int(self.f.size * 1.55)
        self.lo = text_layer(self.lines, self.f, T["kara"], self.lh, width=CW)
        self.hi = text_layer(self.lines, self.f, T["fg"], self.lh, width=CW)
        self.x, self.y = x, y_bottom - self.lo.height
        self.t_on, self.t_voice, self.speech = t_on, t_voice, speech
        # reveal snaps to character boundaries; progress is spread by spoken weight, not pixels
        self.stops = []          # per line: list of (cum_weight, x_px)
        acc = 0.0
        for l in self.lines:
            st, x = [], 0.0
            for ch in l:
                x += self.f.getlength(ch)
                acc += 1.0 if ord(ch) > 0x2E80 and ch not in "，。、；：？！" else (0.45 if ch.isalnum() else 0.15)
                st.append((acc, x))
            self.stops.append(st)
        self.total = acc or 1.0

    def draw(self, frame, t):
        a = expo_out((t - self.t_on) / 0.4)
        if a <= 0:
            return
        lo = self.lo
        if a < 0.999:
            lo = lo.copy(); lo.putalpha(lo.getchannel("A").point(lambda v: int(v * a)))
        frame.alpha_composite(lo, (self.x, self.y))
        done = clamp((t - self.t_voice) / max(0.1, self.speech)) * self.total
        for i, st in enumerate(self.stops):
            xs = [x for w, x in st if w <= done + 1e-6]
            if not xs:
                break
            y0 = i * self.lh
            y1 = min(self.hi.height, y0 + self.lh)
            frame.alpha_composite(self.hi.crop((0, y0, int(xs[-1]) + 2, y1)), (self.x, self.y + y0))
            if len(xs) < len(st):
                break


class Counter:
    """key figure: counts up if numeric, else types in; big Black weight."""

    def __init__(self, key, tone, x, y, t0, size):
        self.T = TONES[tone]
        self.key, self.x, self.y, self.t0 = key, x, y, t0
        self.f = font(SANS_K, size)
        m = re.match(r"^([+\-]?)(\d+(?:\.\d+)?)(%|B|K|M|T|x|倍|万|亿)?$", key)
        self.num = (m.group(1), m.group(2), m.group(3) or "") if m else None   # dates like 10/6 stay static
        self.final = text_layer([key], self.f, self.T["fg"], size)
        self.w, self.h = self.final.width, self.final.height
        self.cache = {}

    def draw(self, frame, t):
        p = (t - self.t0) / 0.9
        if p <= 0:
            return
        if p >= 1 or not self.num:
            a = expo_out(p / 0.5) if not self.num else 1
            im = self.final
            if a < 0.999:
                im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
            frame.alpha_composite(im, (self.x, self.y + (0 if self.num else round(20 * (1 - a)))))
            return
        sign, n, suf = self.num
        v = float(n) * p2_out(p)
        s = sign + (f"{v:.{len(n.split('.')[1])}f}" if "." in n else str(int(round(v)))) + suf
        if s not in self.cache:
            self.cache[s] = text_layer([s], self.f, self.T["fg"], self.f.size)
        frame.alpha_composite(self.cache[s], (self.x, self.y))


# ---------------------------------------------------------------- shots
def build_story(sc, k, st, shot, n_shots, cache):
    tone = st.get("tone", "light")
    T = TONES[tone]
    base = paper(tone)
    masthead(base, tone, sc, k + 1, n_shots)
    source_line(base, tone, st.get("source", ""))
    els, warns = [], []
    # number block + category
    num = f"{k + 1:02d}"
    blk = Image.new("RGBA", (84, 84), T["block"] + (255,))
    fb = font(SANS_K, 44)
    ImageDraw.Draw(blk).text(((84 - fb.getlength(num)) / 2, 6), num, font=fb, fill=T["blockfg"])
    els.append(El(blk, MX, 236, 0.0, 0.34, "drop", 40))
    cat = spaced(st["category"] + "  ·  " + st["cat_en"], font(SANS_B, 28), T["fg"], 4)
    els.append(El(cat, MX + 108, 236 + (84 - cat.height) // 2 + 2, 0.12, 0.45, "wipe"))
    tot = spaced(f"{k + 1} / {len(sc['stories'])}", font(SERIF_R, 26), T["dim"], 2)
    els.append(El(tot, W - MX - tot.width, 236 + (84 - tot.height) // 2, 0.12, 0.4, "fadeup", 12))
    y = 356
    # EN eyebrow (serif, caps)
    en = st.get("title_en", "").upper()
    if en:
        fe = fit_one_line(en, SERIF_R, 30, CW, 20)
        eb = spaced(en, fe, T["sub"], 2)
        if eb.width > CW:
            eb = eb.resize((CW, int(eb.height * CW / eb.width)), Image.LANCZOS)
        els.append(El(eb, MX, y, 0.18, 0.5, "fadeup", 16))
        y += eb.height + 14
    # ZH headline
    fz, lines = headline(st["title_zh"], CW)
    lh = int(fz.size * 1.28)
    for i, l in enumerate(lines):
        li = text_layer([l], fz, T["fg"], lh)
        els.append(El(li, MX, y + i * lh, 0.26 + 0.09 * i, 0.55, "fadeup", 34))
    y += lh * len(lines) + 10
    top = y + 26
    # bottom-up: subtitle, key figure, card fills the rest
    kara = Karaoke(st["narration"], tone, MX, 1582, 0.35, shot["voice_at"] - shot["start"], shot["speech"])
    key_top = kara.y - 40 - 150
    img = fetch_image(st["image"], cache) if st.get("image") else None
    card_h = key_top - 34 - 40 - top          # 40 = caption
    dyn = []
    cnt = None
    if img is not None and card_h >= 300:
        pw = CW - 8
        avail = min(card_h, 640) - 8
        fh = round(img.height * pw / img.width)
        if fh > avail * 2.0:                   # very tall: narrow it so the pan stays readable
            pw = round(pw * avail * 2.0 / fh); fh = round(avail * 2.0)
        fitted = img.resize((pw, fh), Image.LANCZOS)
        ph = min(fh, avail)
        ch = ph + 8
        cy = top + (card_h - ch) // 2
        frame_card = Image.new("RGBA", (CW, ch), T["fg"] + (255,))
        ImageDraw.Draw(frame_card).rectangle((4, 4, CW - 5, ch - 5), fill=T["card"] + (255,))
        dyn.append(("pan", fitted, frame_card, MX, cy, pw, ph))
        cap = text_layer(["图 · " + st.get("source", "")], font(SANS_R, 24), T["dim"], 30)
        els.append(El(cap, MX, cy + ch + 12, 0.9, 0.4, "fadeup", 8))
    else:
        # no usable picture -> inverse typographic panel carrying the key figure (no separate key row)
        ch = min(key_top + 160 - top, 760)
        cy = top + (key_top + 160 - top - ch) // 2
        pan = Image.new("RGBA", (CW, ch), (0, 0, 0, 0))
        ImageDraw.Draw(pan).rounded_rectangle((0, 0, CW - 1, ch - 1), 24, fill=T["block"] + (255,))
        fk = fit_one_line(st["key"], SANS_K, 210, CW - 120, 80)
        kt = text_layer([st["key"]], fk, T["blockfg"], fk.size)
        pan.alpha_composite(kt, ((CW - kt.width) // 2, (ch - kt.height) // 2 - 50))
        if st.get("key_label"):
            kl = text_layer([st["key_label"]], font(SANS_R, 38), T["blockfg"], 46)
            pan.alpha_composite(kl, ((CW - kl.width) // 2, (ch + kt.height) // 2 - 10))
        lab = spaced(st["cat_en"] + " · " + st.get("source", ""), font(SERIF_R, 24), T["blockfg"], 3)
        pan.alpha_composite(lab, ((CW - lab.width) // 2, ch - 70))
        els.append(El(pan, MX, cy, 0.45, 0.6, "slide"))
    if dyn:
        # key figure row
        fsize = 132 if len(st["key"]) <= 5 else 96
        cnt = Counter(st["key"], tone, MX - 6, key_top + (150 - fsize) // 2 - 18, 0.7, fsize)
        lab = text_layer(wrap(st.get("key_label", ""), font(SANS_R, 34), CW - cnt.w - 60) or [" "],
                         font(SANS_R, 34), T["sub"], 46)
        lx = MX + cnt.w + 36
        els.append(El(lab, lx, key_top + (150 - lab.height) // 2, 0.95, 0.5, "fadeup", 14))
        rule = Image.new("RGBA", (CW, 3), T["fg"] + (255,))
        els.append(El(rule, MX, key_top + 168, 0.7, 1.0, "wipe"))
    for e in els:
        if e.box[2] > W - MX + 2 or e.box[3] > SAFE_BOTTOM or e.box[0] < MX - 8:
            warns.append(f"shot {k + 1}: element out of safe area {e.box}")
    if kara.y + kara.lo.height > SAFE_BOTTOM or len(kara.lines) > 3:
        warns.append(f"shot {k + 1}: subtitle {len(kara.lines)} lines")
    if top > key_top - 200:
        warns.append(f"shot {k + 1}: headline pushes card too small")
    return dict(base=base, tone=tone, els=els, kara=kara, counter=cnt, dyn=dyn, warns=warns)


def build_intro(sc, shot, cache):
    tone = "light"; T = TONES[tone]
    base = paper(tone)
    masthead(base, tone, sc, 0, 0)
    els = []
    big = text_layer(["AI 早报"], font(SANS_K, 190), T["fg"], 190)
    els.append(El(big, MX - 8, 226, 0.0, 0.6, "fadeup", 40))
    ey = spaced("THE DAILY AI BRIEF", font(SERIF_R, 34), T["sub"], 8)
    els.append(El(ey, MX, 516, 0.2, 0.5, "fadeup", 16))
    d8 = sc["date"].split("-")
    dl = text_layer([f"{d8[0]} 年 {int(d8[1])} 月 {int(d8[2])} 日  {sc.get('weekday', '')}"], font(SANS_B, 40), T["fg"], 50)
    els.append(El(dl, MX, 578, 0.3, 0.5, "fadeup", 16))
    rule = Image.new("RGBA", (CW, 3), T["fg"] + (255,))
    els.append(El(rule, MX, 664, 0.35, 0.8, "wipe"))
    # table of contents: numbered blocks pop in one by one
    y = 716
    n = len(sc["stories"])
    step = min(118, (1560 - y) // max(1, n))
    for i, st in enumerate(sc["stories"]):
        row = Image.new("RGBA", (CW, step - 14), (0, 0, 0, 0))
        dr = ImageDraw.Draw(row)
        bs = min(72, step - 30)
        dr.rectangle((0, 0, bs, bs), fill=T["block"])
        fb = font(SANS_K, int(bs * 0.5))
        dr.text(((bs - fb.getlength(f"{i + 1:02d}")) / 2, bs * 0.12), f"{i + 1:02d}", font=fb, fill=T["blockfg"])
        ft = fit_one_line(st.get("short", st["title_zh"]), SANS_B, 46, CW - bs - 230, 30)
        dr.text((bs + 28, (bs - ft.size * 1.32) / 2), st.get("short", st["title_zh"]), font=ft, fill=T["fg"])
        fc = font(SANS_R, 26)
        dr.text((CW - fc.getlength(st["category"]), (bs - 36) / 2), st["category"], font=fc, fill=T["dim"])
        dr.line((bs + 28, step - 16, CW, step - 16), fill=T["line"], width=2)
        els.append(El(row, MX, y + i * step, 0.55 + 0.22 * i, 0.4, "fadeup", 22))
    source_line(base, tone, "daily.juya.uk")
    kara = Karaoke(sc["intro"]["narration"], tone, MX, 1582, 0.2, shot["voice_at"] - shot["start"], shot["speech"])
    return dict(base=base, tone=tone, els=els, kara=kara, counter=None, dyn=[], warns=[])


def build_outro(sc, shot, cache):
    tone = "dark"; T = TONES[tone]
    base = paper(tone)
    masthead(base, tone, sc, 0, 0)
    els = []
    a = text_layer(["以上。"], font(SANS_K, 170), T["fg"], 170)
    els.append(El(a, MX - 6, 360, 0.0, 0.6, "fadeup", 40))
    b = spaced("THAT'S THE BRIEF FOR TODAY", font(SERIF_R, 32), T["sub"], 6)
    els.append(El(b, MX, 600, 0.2, 0.5, "fadeup", 14))
    rule = Image.new("RGBA", (CW, 3), T["fg"] + (255,))
    els.append(El(rule, MX, 670, 0.3, 0.8, "wipe"))
    lines = [("内容来源", sc["source_name"] + "  daily.juya.uk"),
             ("本期日期", sc["date"].replace("-", ".") + "  " + sc.get("weekday", "")),
             ("说明", "AI 辅助整理，细节以原文为准")]
    for i, (k_, v) in enumerate(lines):
        row = Image.new("RGBA", (CW, 70), (0, 0, 0, 0))
        dr = ImageDraw.Draw(row)
        dr.text((0, 8), k_, font=font(SANS_R, 30), fill=T["dim"])
        dr.text((200, 4), v, font=font(SANS_B, 36), fill=T["fg"])
        els.append(El(row, MX, 710 + i * 86, 0.45 + 0.15 * i, 0.4, "fadeup", 14))
    c = text_layer(["明天见"], font(SANS_K, 120), T["fg"], 120)
    els.append(El(c, MX - 4, 1100, 0.9, 0.6, "fadeup", 30))
    d2 = spaced("SEE YOU TOMORROW", font(SERIF_R, 30), T["sub"], 6)
    els.append(El(d2, MX, 1260, 1.0, 0.5, "fadeup", 12))
    source_line(base, tone, "daily.juya.uk")
    kara = Karaoke(sc["outro"]["narration"], tone, MX, 1582, 0.2, shot["voice_at"] - shot["start"], shot["speech"])
    return dict(base=base, tone=tone, els=els, kara=kara, counter=None, dyn=[], warns=[])


ENTER_LEAD = 0.15   # entrances start slightly "before" the cut so the first frame is never an empty page


def compose(S, t, dur, idx, n):
    fr = S["base"].copy()
    te = t + ENTER_LEAD
    rail(fr, S["tone"], idx, n, t / dur)
    for kind, fitted, frame_card, x, y, pw, ph in S["dyn"]:
        # card slides in from the right (clipped); a tall picture scrolls slowly like reading a clipping
        e = expo_out((te - 0.4) / 0.7)
        if e <= 0:
            continue
        travel = fitted.height - ph
        oy = int(travel * p1_inout((t - 1.2) / max(1.0, dur - 2.0))) if travel > 0 else 0
        card = frame_card.copy()
        card.paste(fitted.crop((0, oy, pw, oy + ph)), ((card.width - pw) // 2, 4))
        if "mask" not in S:
            S["mask"] = rounded_mask(card.width, card.height, 20)
        card.putalpha(S["mask"])
        off = round((1 - e) * card.width * 0.3)
        if off:
            card = card.crop((0, 0, card.width - off, card.height))
        if e < 0.999:
            card.putalpha(card.getchannel("A").point(lambda v: int(v * e)))
        fr.alpha_composite(card, (x + off, y))
    for el in S["els"]:
        el.draw(fr, te)
    if S["counter"]:
        S["counter"].draw(fr, te)
    S["kara"].draw(fr, t)
    return fr


def main():
    work = sys.argv[1]
    sc = json.load(open(os.path.join(work, "script.json")))
    tm = json.load(open(os.path.join(work, "timing.json")))
    shots = tm["shots"]
    n = len(shots)
    a, b = 0, n - 1
    if "--shots" in sys.argv:
        r = sys.argv[sys.argv.index("--shots") + 1]
        a, b = (int(r.split("-")[0]), int(r.split("-")[-1]))
    still = "--still" in sys.argv
    cache = os.path.join(work, "img_cache")
    seg = os.path.join(work, "segments"); os.makedirs(seg, exist_ok=True)
    os.makedirs(os.path.join(work, "stills"), exist_ok=True)
    warns = []
    for i in range(a, b + 1):
        shot = shots[i]
        if i == 0:
            S = build_intro(sc, shot, cache)
        elif i == n - 1:
            S = build_outro(sc, shot, cache)
        else:
            S = build_story(sc, i - 1, sc["stories"][i - 1], shot, n, cache)
        warns += S["warns"]
        frames, dur = shot["frames"], shot["dur"]
        if still:
            compose(S, dur * 0.75, dur, i, n).convert("RGB").save(os.path.join(work, "stills", f"{i:02d}_{shot['id']}.png"))
            print(f"[render] still {i} {shot['id']}")
            continue
        out = os.path.join(seg, f"{i:02d}_{shot['id']}.mp4")
        p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                              "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                              "-pix_fmt", "yuv420p", "-r", str(FPS), out], stdin=subprocess.PIPE)
        for f in range(frames):
            p.stdin.write(compose(S, f / FPS, dur, i, n).convert("RGB").tobytes())
        p.stdin.close(); p.wait()
        print(f"[render] shot {i} {shot['id']}: {frames} frames -> {os.path.basename(out)}")
    rep = os.path.join(work, "layout_warnings.json")
    old = json.load(open(rep)) if os.path.exists(rep) else {}
    for i in range(a, b + 1):
        old[str(i)] = [w for w in warns if w.startswith(f"shot {i}:")] if 0 < i < n - 1 else []
    json.dump(old, open(rep, "w"), ensure_ascii=False, indent=1)
    for w in warns:
        print("[render] WARN", w)


if __name__ == "__main__":
    main()
