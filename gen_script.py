#!/usr/bin/env python3
"""Pick 5-7 stories and write script.json (narration + bilingual titles).

Usage: gen_script.py WORKDIR [--n 7] [--force]
- Existing WORKDIR/script.json is kept unless --force (so a hand-edited script survives re-runs).
- Tries an OpenRouter free model (env ORFREE_KEY); falls back to a deterministic heuristic.
"""
import json, os, re, subprocess, sys, datetime
from urllib.parse import urlparse

CAT_EN = {"要闻": "TOP STORY", "模型": "MODEL", "产品": "PRODUCT", "行业": "INDUSTRY"}
CAT_ORDER = {"要闻": 0, "模型": 1, "产品": 2, "行业": 3}
MODELS = os.environ.get("AINEWS_LLM_MODELS", "nvidia/nemotron-3-super-120b-a12b:free,openrouter/free").split(",")
WEEK = "一二三四五六日"

PROMPT = """你是中文 AI 早报竖屏短视频的编辑。下面是橘鸦 AI 早报 {date} 的全部条目（JSON）。
任务：选出 {n} 条最重要的新闻，排序规则：要闻 > 模型 > 产品 > 行业（同类里按重要性）。
优先：影响面大的模型/产品发布、AI 工具与 agent、开源或免费模型、隐私与安全。不要机械地取前 {n} 条：同一公司同一件事只留一条，要覆盖至少两个类别，行业里有隐私/安全/监管类重要事件要选上。
每条输出字段：
- num: 原条目编号(int)
- category: 要闻/模型/产品/行业 之一（可按内容修正原分类）
- title_zh: 中文标题，≤16 个汉字，保留产品英文名
- title_en: 英文标题，≤42 个字符，新闻标题式
- short: 目录用极短标题，≤11 个字
- narration: 一句话旁白，中文，严格 28–46 个字（超过就删修饰语，不要罗列参数），口语、事实准确、只用原文信息；数字写成便于朗读的形式（如“五千零一十亿”“百分之五十”）；不要“第一条”之类序号
- key: 画面关键数字或关键词，≤8 字符（如 "+50%"、"501B"、"免费 2 周"）
- key_label: key 的中文说明，≤12 字
只输出 JSON：{{"stories":[...]}}，不要任何解释。

条目：
{items}
"""


def domain(u):
    p = urlparse(u)
    d = p.netloc.lower()
    d = d[4:] if d.startswith("www.") else d
    if d in ("x.com", "twitter.com") and p.path.strip("/"):
        return "x.com/@" + p.path.strip("/").split("/")[0]
    return d


def call_llm(prompt):
    key = os.environ.get("ORFREE_KEY")
    if not key:
        return None
    for model in MODELS:
        body = json.dumps({"model": model, "temperature": 0.3, "max_tokens": 4000, "reasoning": {"enabled": False}, "messages": [{"role": "user", "content": prompt}]})
        r = subprocess.run(["curl", "-s", "--max-time", "50", "https://openrouter.ai/api/v1/chat/completions",
                            "-H", "Authorization: Bearer " + key, "-H", "Content-Type: application/json",
                            "-d", "@-"], input=body.encode(), capture_output=True)
        try:
            txt = json.loads(r.stdout)["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", txt, re.S)
            data = json.loads(m.group(0))
            if data.get("stories"):
                print(f"[script] LLM ok: {model}")
                return data["stories"]
        except Exception as e:
            print(f"[script] LLM {model} failed: {str(e)[:120]}")
    return None


SHORTEN = """把下面每条旁白改写成一句 28–44 个汉字的中文口播（只保留最关键的事实，数字写成便于朗读的中文），保持 num 不变。
只输出 JSON：{{"items":[{{"num":..,"narration":".."}}]}}
{rows}"""


def shorten(stories):
    long = [{"num": s["num"], "narration": s["narration"]} for s in stories if len(s.get("narration", "")) > 50]
    if not long:
        return
    key = os.environ.get("ORFREE_KEY")
    for model in MODELS:
        body = json.dumps({"model": model, "temperature": 0.2, "max_tokens": 2000, "reasoning": {"enabled": False},
                           "messages": [{"role": "user", "content": SHORTEN.format(rows=json.dumps(long, ensure_ascii=False))}]})
        r = subprocess.run(["curl", "-s", "--max-time", "50", "https://openrouter.ai/api/v1/chat/completions",
                            "-H", "Authorization: Bearer " + (key or ""), "-H", "Content-Type: application/json",
                            "-d", "@-"], input=body.encode(), capture_output=True)
        try:
            txt = json.loads(r.stdout)["choices"][0]["message"]["content"]
            new = {x["num"]: x["narration"] for x in json.loads(re.search(r"\{.*\}", txt, re.S).group(0))["items"]}
            for s in stories:
                if s["num"] in new and 15 <= len(new[s["num"]]) < len(s["narration"]):
                    s["narration"] = new[s["num"]]
            print(f"[script] shortened {len(new)} narrations via {model}")
            return
        except Exception as e:
            print(f"[script] shorten via {model} failed: {str(e)[:100]}")


def heuristic(items, n):
    """No LLM: take items in category order (juya already orders by importance inside a section)."""
    picked = sorted(items, key=lambda i: (i["priority"], i["num"]))[:n]
    out = []
    for i in picked:
        first = re.split(r"(?<=[。；])", i["summary"])[0].rstrip("。；")
        nums = re.findall(r"\d+(?:\.\d+)?\s*(?:%|B|K|万|亿|倍)?", i["title"] + " " + i["summary"])
        out.append({"num": i["num"], "category": i["category"], "title_zh": i["title"][:18],
                    "title_en": "", "short": i["title"][:11], "narration": first[:60] + "。",
                    "key": (nums[0].replace(" ", "") if nums else i["category"]), "key_label": ""})
    return out


def enrich(stories, byn):
    """Fill derived fields (only where missing, so hand edits win)."""
    for s in stories:
        it = byn[s["num"]]
        s.setdefault("cat_en", CAT_EN.get(s["category"], "INDUSTRY"))
        s.setdefault("image", it["images"][0] if it["images"] else None)
        s.setdefault("source", domain(it["url"]))
        s.setdefault("url", it["url"])
        s.setdefault("short", s.get("title_zh", "")[:11])
    if not any("tone" in s for s in stories):
        for s in stories:
            s["tone"] = "dark" if s["category"] == "要闻" else "light"
        if len(stories) >= 5:  # one extra dark beat in the back half for rhythm
            stories[len(stories) - 2]["tone"] = "dark"


def main():
    work = sys.argv[1]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 7
    path = os.path.join(work, "script.json")
    data = json.load(open(os.path.join(work, "items.json")))
    if os.path.exists(path) and "--force" not in sys.argv:
        script = json.load(open(path))
        enrich(script["stories"], {i["num"]: i for i in data["items"]})
        json.dump(script, open(path, "w"), ensure_ascii=False, indent=1)
        print(f"[script] keep existing {path} (missing fields filled)")
        return
    items, date = data["items"], data["date"]
    slim = [{k: i[k] for k in ("num", "category", "title", "summary")} for i in items]
    stories = call_llm(PROMPT.format(date=date, n=n, items=json.dumps(slim, ensure_ascii=False)))
    if not stories:
        print("[script] using heuristic fallback (review script.json!)")
        stories = heuristic(items, n)
    else:
        shorten(stories)
    byn = {i["num"]: i for i in items}
    stories = [s for s in stories if s.get("num") in byn][:n]
    stories.sort(key=lambda s: CAT_ORDER.get(s.get("category"), 3))
    enrich(stories, byn)
    d = datetime.date.fromisoformat(date)
    script = {
        "date": date, "weekday": "星期" + WEEK[d.weekday()],
        "source_name": "橘鸦 AI 早报", "source_url": "https://daily.juya.uk",
        "intro": {"narration": f"{d.month}月{d.day}日 AI 早报，{len(stories)}条新闻，一分钟看完。"},
        "outro": {"narration": "以上内容来自橘鸦 AI 早报，我们明天见。"},
        "stories": stories,
    }
    for s in stories:  # editorial lint: one sentence, short enough for ~6 s of speech
        if len(s.get("narration", "")) > 52 or len(s.get("title_zh", "")) > 18:
            print(f"[script] WARN #{s['num']} narration/title long -> consider editing script.json")
    json.dump(script, open(path, "w"), ensure_ascii=False, indent=1)
    print(f"[script] wrote {path} ({len(stories)} stories)")


if __name__ == "__main__":
    main()
