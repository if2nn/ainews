#!/usr/bin/env python3
"""Build news.json + processed images for the AI 早报 email (Plan A+ 配图版).

Usage: make_news.py DATE OUTDIR [--build VIDEO_BUILD_DIR] [--n 8]

Inputs (in order of preference)
  items      VIDEO_BUILD/items.json (from fetch.py). If its items lack `image_meta` or the file lacks
             `cover_image` (older fetch.py), VIDEO_BUILD/juya.md is re-parsed with fetch.parse().
             No VIDEO_BUILD at all -> fetch.py DATE OUTDIR/_fetch is run.
  selection  VIDEO_BUILD/script.json `stories[].num` (reviewed). Missing -> rule: sort by
             要闻>模型>产品>行业 then juya order, take --n (default 8, min 5).
  comments   OUTDIR/DATE_comments.json  {"notes": [...2-3 strings...], "lead": optional, "headline": optional}
             (a bare JSON list is accepted as notes). Missing -> 点评 section omitted.
Output: OUTDIR/news.json, OUTDIR/official/*.jpg|gif (raw downloads in official/raw/), OUTDIR/gifs/*.gif
"""
import json, os, re, subprocess, sys, datetime, shutil, io
from urllib.parse import urlparse
from PIL import Image, ImageSequence

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fetch  # noqa: E402  (ainews/fetch.py)

UA = fetch.UA
PRIO = {"要闻": 0, "模型": 1, "开发": 2, "产品": 2, "行业": 3, "争议": 3}
EML_LIMIT = 3_000_000          # final message.eml must stay under this
GIF_LIMIT = 400_000            # each in-article GIF
HTML_EST = 80_000              # email.html is ~75 KB


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def log(*a):
    print("[news]", *a, flush=True)


def load_items(date, out, build):
    d = None
    if build and os.path.exists(os.path.join(build, "items.json")):
        d = json.load(open(os.path.join(build, "items.json"), encoding="utf-8"))
        md_path = os.path.join(build, "juya.md")
        stale = any("image_meta" not in i for i in d["items"]) or "cover_image" not in d
        if stale and os.path.exists(md_path):
            md = open(md_path, encoding="utf-8").read()
            d["items"] = fetch.parse(md)
            cov = re.search(r"!\[[^\]]*\]\((https?://assets\.juya\.uk/cover/[^)]+)\)", md)
            d["cover_image"] = cov.group(1) if cov else None
            log("items.json predates image_meta -> re-parsed", md_path)
    if d is None:
        work = os.path.join(out, "_fetch")
        local = os.path.join(os.environ.get("AINEWS_LIB", os.path.join(os.path.dirname(HERE), "output")), "项目", f"{date}_AI早报", "juya.md")
        subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "fetch.py"), date, work, "--local", local], check=True)
        d = json.load(open(os.path.join(work, "items.json"), encoding="utf-8"))
    return d


def select(items, script, n):
    by = {i["num"]: i for i in items}
    chosen = []
    if script:
        for s in script.get("stories", []):
            it = by.get(s.get("num"))
            if it:
                chosen.append((it, s))
        log(f"selection from reviewed script.json: {[i['num'] for i, _ in chosen]}")
    if len(chosen) < 5:
        have = {i["num"] for i, _ in chosen}
        rest = sorted([i for i in items if i["num"] not in have], key=lambda i: (i["priority"], i["num"]))
        chosen += [(i, {}) for i in rest[: max(0, n - len(chosen))]]
        log(f"selection by rule (要闻>模型>产品>行业): {[i['num'] for i, _ in chosen]}")
    chosen = chosen[:8]
    cat = lambda p: p[1].get("category") or p[0]["category"]
    chosen.sort(key=lambda p: PRIO.get(cat(p), 3))  # stable: keeps script order inside a category
    return chosen


NUM_RE = re.compile(r"(?<![\w.])([+\-]?\d+(?:\.\d+)?\s?(?:%|万亿|亿美元|亿元|亿|万|倍|TPS|B|T|K|M|GB|美元))(?![A-Za-z])")


def callout(it, s):
    key, lab = (s.get("key") or "").strip(), (s.get("key_label") or "").strip()
    if key and re.search(r"\d", key) and len(key) <= 12:
        return {"big": key, "small": lab}
    txt = it.get("summary") or it.get("body") or ""
    m = NUM_RE.search(txt)
    if not m:
        return None
    clause = next((c for c in re.split(r"[，。；、,;]", txt) if m.group(1) in c), "").strip()
    if len(clause) > 26:
        clause = clause[:25] + "…"
    return {"big": m.group(1).replace(" ", " "), "small": clause}


def src_label(it, s):
    if s.get("source"):
        return s["source"]
    h = urlparse(it["url"]).netloc.replace("www.", "")
    if h in ("x.com", "twitter.com"):
        u = urlparse(it["url"]).path.strip("/").split("/")[0]
        return f"x.com/@{u}" if u else h
    return h


LATIN = re.compile(r"[A-Za-z][A-Za-z0-9.\-]*(?:\s+(?:[A-Z0-9][A-Za-z0-9.\-]*))*")


def latin_name(*texts):
    for t in texts:
        m = LATIN.search(t or "")
        if m and len(m.group(0)) >= 2:
            return m.group(0).upper()
    return None


def short_title(it, s, lim=20):
    t = s.get("short") or s.get("title_zh") or it["title"]
    return t if len(t) <= lim else t[: lim - 1] + "…"


def curl_get(url, dest):
    r = subprocess.run(["curl", "-sL", "--max-time", "60", "-A", UA, "-o", dest, "-w", "%{http_code}", url], capture_output=True, text=True)
    return r.stdout.strip() == "200" and os.path.exists(dest) and os.path.getsize(dest) > 500


def to_jpeg(src, dest, width=1080, q=82):
    im = Image.open(src)
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    im = im.convert("RGBA")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    if bg.width > width:
        bg = bg.resize((width, round(bg.height * width / bg.width)), Image.LANCZOS)
    bg.save(dest, "JPEG", quality=q, optimize=True)
    return os.path.getsize(dest)


def shrink_gif(src, dest, limit=GIF_LIMIT):
    """ffmpeg two-pass palette; step down width / fps / colours until under limit."""
    im = Image.open(src)
    w0, n0 = im.width, getattr(im, "n_frames", 1)
    dur = sum((f.info.get("duration", 80) or 80) for f in ImageSequence.Iterator(im)) / 1000 or 2
    w = min(w0, 600)  # keep width as long as possible; trade fps/colours first
    tries = [(w, 12, 128), (w, 8, 96), (w, 6, 64), (w, 5, 48), (int(w * .8), 5, 48), (int(w * .65), 5, 40),
             (int(w * .5), 4, 32)]
    for w, fps, col in tries:
        vf = (f"fps={fps},scale={w}:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors={col}:stats_mode=diff[p];"
              f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", vf, "-loop", "0", dest], check=False)
        if os.path.exists(dest) and os.path.getsize(dest) <= limit:
            return os.path.getsize(dest)
    return os.path.getsize(dest) if os.path.exists(dest) else None


def main():
    date, out = sys.argv[1], sys.argv[2]
    build = arg("--build")
    n = max(5, min(8, int(arg("--n", 8))))
    os.makedirs(os.path.join(out, "official", "raw"), exist_ok=True)
    os.makedirs(os.path.join(out, "gifs"), exist_ok=True)
    warnings, actions = [], []

    data = load_items(date, out, build)
    script = None
    if build and os.path.exists(os.path.join(build, "script.json")):
        script = json.load(open(os.path.join(build, "script.json"), encoding="utf-8"))
    chosen = select(data["items"], script, n)

    cpath = os.path.join(out, f"{date}_comments.json")
    comments = json.load(open(cpath, encoding="utf-8")) if os.path.exists(cpath) else {}
    if isinstance(comments, list):
        comments = {"notes": comments}
    notes = [x for x in comments.get("notes", []) if str(x).strip()][:3]
    if not notes:
        warnings.append("no DATE_comments.json -> 点评 section omitted")

    # ---- items ----
    items = []
    for k, (it, s) in enumerate(chosen, 1):
        tag = s.get("category") or it["category"]
        imgs = []
        for j, m in enumerate(it.get("image_meta") or [{"url": u, "alt": it["title"], "kind": "gif" if u.lower().endswith(".gif") else "still"} for u in it.get("images", [])]):
            if len(imgs) == 2:
                break
            cid = f"n{k}{'ab'[j] if j < 2 else j}"
            imgs.append({"url": m["url"], "kind": m["kind"], "cid": cid,
                         "alt": (m.get("alt") if m.get("alt") and m.get("alt") != it["title"] else f"配图：{it['title']}")})
        items.append({"num": it["num"], "tag": tag, "title": it["title"], "body": it.get("summary") or it.get("body", "")[:220],
                      "src": src_label(it, s), "url": it["url"], "callout": callout(it, s), "images": imgs,
                      "short": short_title(it, s), "title_zh": s.get("title_zh") or it["title"],
                      "narration": s.get("narration"), "latin": latin_name(s.get("short"), s.get("title_zh"), it["title"])})

    # ---- download + process ----
    def fetch_img(o):
        ext = ".gif" if o["kind"] == "gif" else os.path.splitext(urlparse(o["url"]).path)[1] or ".img"
        raw = os.path.join(out, "official", "raw", o["cid"] + ext)
        if not (os.path.exists(raw) and os.path.getsize(raw) > 500) and not curl_get(o["url"], raw):
            warnings.append(f"download failed: {o['url']}")
            return False
        try:
            if o["kind"] == "gif" and getattr(Image.open(raw), "n_frames", 1) > 1:
                o["file"] = f"official/{o['cid']}.gif"
                sz = shrink_gif(raw, os.path.join(out, o["file"]))
                if not sz or sz > GIF_LIMIT:
                    o["file"] = f"official/{o['cid']}.jpg"; o["kind"] = "still"
                    to_jpeg(raw, os.path.join(out, o["file"]))
                    actions.append(f"{o['cid']}: GIF could not get <400KB -> first frame JPEG")
            else:
                o["kind"] = "still"; o["file"] = f"official/{o['cid']}.jpg"
                to_jpeg(raw, os.path.join(out, o["file"]))
        except Exception as e:  # corrupt / unsupported
            warnings.append(f"image failed {o['url']}: {e}")
            return False
        return True

    for x in items:
        x["images"] = [o for o in x["images"] if fetch_img(o)]
    cover_image = None
    if data.get("cover_image"):
        o = {"url": data["cover_image"], "kind": "still", "cid": "jcover", "alt": f"橘鸦 AI 早报 {date} 封面"}
        if fetch_img(o):
            cover_image = o

    # ---- static gifs + animated cover ----
    for g in ("title", "icon2", "icon3", "icon4"):
        shutil.copy(os.path.join(HERE, "assets", f"{g}.gif"), os.path.join(out, "gifs", f"{g}.gif"))
    caps, total = [], 0
    for x in items[:4]:
        if x["latin"] and x["latin"] not in caps and total + len(x["latin"]) + 3 <= 44:
            caps.append(x["latin"]); total += len(x["latin"]) + 3
    caption = " · ".join(caps) if len(caps) >= 2 else f"AI 早报 · {date[5:].replace('-', '.')}"
    cover_gif = os.path.join(out, "gifs", "cover.gif")
    stamp = os.path.join(out, "gifs", ".cover_caption")
    if not (os.path.exists(cover_gif) and os.path.exists(stamp) and open(stamp).read() == caption):
        subprocess.run(["node", os.path.join(HERE, "render_cover.mjs"), cover_gif, caption], check=True)
        open(stamp, "w").write(caption)

    # icons for items without images (generic, approved set; icon1 is GPT-specific so unused)
    ICON = {"模型": "icon2", "产品": "icon4"}
    for x in items:
        x["icon"] = None if x["images"] else ICON.get(x["tag"], "icon3")

    # ---- size budget ----
    def est():
        files = [cover_gif, os.path.join(out, "gifs", "title.gif")]
        files += [os.path.join(out, "gifs", f"{x['icon']}.gif") for x in items if x["icon"]]
        files += [os.path.join(out, o["file"]) for x in items for o in x["images"]]
        if cover_image:
            files.append(os.path.join(out, cover_image["file"]))
        raw = sum(os.path.getsize(f) for f in set(files))
        return int((raw + HTML_EST * 2) * 1.37) + 20_000

    def drop(pred, why):
        for x in reversed(items):
            for o in list(reversed(x["images"])):
                if est() < EML_LIMIT:
                    return
                if pred(x, o):
                    x["images"].remove(o)
                    actions.append(f"{o['cid']}: {why}")
                    if not x["images"]:
                        x["icon"] = ICON.get(x["tag"], "icon3")

    if est() >= EML_LIMIT:
        for x in items:  # 1) shrink GIFs harder
            for o in x["images"]:
                if o["kind"] == "gif" and est() >= EML_LIMIT:
                    raw = [f for f in os.listdir(os.path.join(out, "official", "raw")) if f.startswith(o["cid"] + ".")][0]
                    shrink_gif(os.path.join(out, "official", "raw", raw), os.path.join(out, o["file"]), limit=200_000)
                    actions.append(f"{o['cid']}: GIF shrunk to <=200KB for budget")
        drop(lambda x, o: o["kind"] == "gif", "GIF dropped for budget")
        if est() >= EML_LIMIT:  # 3) recompress stills smaller
            for x in items:
                for o in x["images"]:
                    raw = [f for f in os.listdir(os.path.join(out, "official", "raw")) if f.startswith(o["cid"] + ".")][0]
                    to_jpeg(os.path.join(out, "official", "raw", raw), os.path.join(out, o["file"]), width=720, q=75)
            actions.append("all stills recompressed 720px q75 for budget")
        drop(lambda x, o: o is x["images"][-1] and len(x["images"]) > 1, "2nd image dropped for budget")
        drop(lambda x, o: True, "image dropped for budget")

    # ---- cover story + header ----
    lead_item = items[0]
    head = comments.get("headline") or lead_item["title_zh"]
    toks = head.split()
    if len(toks) >= 2:
        cover_html = (" ".join(toks[:-1]), toks[-1])
    else:
        cut = max(2, min(4, len(head) // 3))
        cover_html = (head[:-cut], head[-cut:])
    # cover blurb: juya's own first sentence (TTS narration spells numbers out, so it is not used here)
    summ = re.split(r"[。；！？]", lead_item["body"])[0].strip()
    if len(summ) > 80:
        cut = summ[:80].rfind("，")
        summ = summ[:cut] if cut > 30 else summ[:79] + "…"
    summ = summ.rstrip("，、") + ("" if summ.endswith("…") else "。")
    lead = comments.get("lead") or ("今日看点：" + "、".join(x["short"] for x in items[:3]) + f" 等 {len(items)} 条。")
    dt = datetime.date.fromisoformat(date)
    news = {
        "date": date, "weekday_en": dt.strftime("%a").upper(), "vol": f"VOL.{date[2:4]} · NO.{date[5:7]}{date[8:10]}",
        "datestr": f"{date[5:7]}.{date[8:10]}.{date[:4]}", "dotdate": date.replace("-", "."),
        "headline": head, "lead": lead,
        "cover": {"pre": cover_html[0], "hi": cover_html[1], "callout": lead_item["callout"], "summary": summ,
                  "bullets": [x["short"] for x in items[1:5]]},
        "cover_caption": caption, "cover_image": cover_image, "items": items, "notes": notes,
        "source": data.get("source"), "selection": "script.json" if script else "rule",
        "warnings": warnings, "budget_actions": actions, "eml_estimate": est(),
    }
    json.dump(news, open(os.path.join(out, "news.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"{len(items)} items, {sum(len(x['images']) for x in items)} images, est eml {est():,} B; warnings={len(warnings)} actions={len(actions)}")


if __name__ == "__main__":
    main()
