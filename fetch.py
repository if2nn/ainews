#!/usr/bin/env python3
"""Fetch the 橘鸦 AI 早报 markdown for a date and parse it into items.json.

Usage: fetch.py DATE WORKDIR [--local PATH]
Order of sources: https://daily.juya.uk/markdown/DATE.md > --local saved copy > RSS (https://daily.juya.uk/rss.xml)
"""
import json, os, re, subprocess, sys, html

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def curl(url, timeout=40):
    r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", UA, "-w", "\n%{http_code}", url],
                       capture_output=True)
    body, _, code = r.stdout.rpartition(b"\n")
    return int(code or 0), body.decode("utf-8", "replace")


def from_rss(date):
    code, xml = curl("https://daily.juya.uk/rss.xml")
    if code != 200:
        return None
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        if date in item or date.replace("-", "") in item:
            m = re.search(r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", item, re.S) or \
                re.search(r"<description>(.*?)</description>", item, re.S)
            if m:
                return html.unescape(m.group(1))  # may be HTML; parser below copes with markdown only
    return None


SECTION_CAT = {  # juya section -> (display category, priority)
    "要闻": ("要闻", 0), "模型发布": ("模型", 1), "开发生态": ("产品", 2), "产品应用": ("产品", 2),
    "技术与洞察": ("行业", 3), "行业动态": ("行业", 3),
}


def parse(md):
    items, section = [], None
    body_part = md.split("\n---\n", 1)[1] if "\n---\n" in md else md
    blocks = re.split(r"\n(?=## |### )", "\n" + body_part)
    for b in blocks:
        b = b.strip()
        if b.startswith("## "):
            section = b[3:].splitlines()[0].strip()
            continue
        if not b.startswith("### "):
            continue
        head = b.splitlines()[0]
        m = re.match(r"### \[(.+?)\]\((.+?)\)\s*`#(\d+)`", head)
        if not m:
            continue
        title, url, num = m.groups()
        quote = " ".join(l[1:].strip() for l in b.splitlines() if l.startswith(">"))
        paras = [l.strip() for l in b.splitlines()[1:] if l.strip() and not l.startswith((">", "!", "-", "相关链接", "---"))]
        # official 橘鸦 images in document order; `images` stays a list of URL strings (video pipeline reads images[0])
        imgs = re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", b)
        meta = [{"url": u, "alt": (a or title), "kind": "gif" if u.lower().split("?")[0].endswith(".gif") else "still"}
                for a, u in re.findall(r"!\[([^\]]*)\]\((https?://[^)]+)\)", b)]
        links = re.findall(r"^- \[(https?://[^\]]+)\]", b, re.M)
        cat, prio = SECTION_CAT.get(section, ("行业", 3))
        clean = lambda s: re.sub(r"[*`]", "", s)
        items.append({"num": int(num), "section": section, "category": cat, "priority": prio,
                      "title": title, "url": url, "summary": clean(quote), "body": clean(" ".join(paras))[:1200],
                      "images": imgs, "image_meta": meta, "links": links or [url]})
    return items


def main():
    date, work = sys.argv[1], sys.argv[2]
    local = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None
    os.makedirs(work, exist_ok=True)
    md, src = None, None
    url = f"https://daily.juya.uk/markdown/{date}.md"
    code, txt = curl(url)
    if code == 200 and "###" in txt:
        md, src = txt, url
    elif local and os.path.exists(local):           # offline / site down: use the saved copy
        md, src = open(local, encoding="utf-8").read(), local
    else:
        txt = from_rss(date)
        if txt:
            md, src = txt, "https://daily.juya.uk/rss.xml"
        else:  # GitHub markdown backup (repo jujuyaya/juya-ai-daily, folder BACKUP); returned 404 on 2026-10-07, kept as last resort
            for gh in (f"https://raw.githubusercontent.com/jujuyaya/juya-ai-daily/main/BACKUP/{date}.md",
                       f"https://raw.githubusercontent.com/jujuyaya/juya-ai-daily/master/BACKUP/{date}.md"):
                c, t = curl(gh)
                if c == 200 and "###" in t:
                    md, src = t, gh
                    break
    if not md:
        sys.exit(f"[fetch] no juya content for {date}")
    open(os.path.join(work, "juya.md"), "w", encoding="utf-8").write(md)
    items = parse(md)
    if not items:
        sys.exit("[fetch] parsed 0 items (format changed? RSS may be HTML)")
    cov = re.search(r"!\[[^\]]*\]\((https?://assets\.juya\.uk/cover/[^)]+)\)", md)  # cover sits above the H1
    json.dump({"date": date, "source": src, "cover_image": cov.group(1) if cov else None, "items": items}, open(os.path.join(work, "items.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"[fetch] {len(items)} items from {src}")


if __name__ == "__main__":
    main()
