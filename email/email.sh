#!/usr/bin/env bash
# AI 早报邮件（Plan A+ 杂志配图版）— 一条命令出邮件，可选发送
# 用法: email.sh YYYY-MM-DD [--send | --no-send] [--force] [--n 8] [--build DIR]
#   默认 --no-send：只生成 + 截图 + 质检。
#   --send  用 gws (Google Workspace CLI) 发送到 $MAIL_TO（发件人 $MAIL_FROM）
#   --force 已有 send_result.json 也重发（默认绝不重发）
#   --build 视频流水线 _build 目录（默认 library/视频作品/DATE_AI早报/_build，读 items.json + 审过的 script.json）
# 输出: library/项目/早报邮件/DATE/  （news.json email.html preview.html preview_390/600.png qa.json message.eml send_result.json）
# 点评: 把 {"notes":["🟢 ...","🟡 ..."], "lead":"可选", "headline":"可选"} 写到 输出目录/DATE_comments.json 再跑；没有就不出点评区。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$(dirname "$HERE")/.env" ]] && { set -a; source "$(dirname "$HERE")/.env"; set +a; }
LIB="${AINEWS_LIB:-$(dirname "$HERE")/output}"
DATE="${1:?用法: email.sh YYYY-MM-DD [--send|--no-send] [--force]}"; shift
[[ "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "日期格式应为 YYYY-MM-DD"; exit 2; }
SEND=0; FORCE=0; N=8; BUILD="$LIB/视频作品/${DATE}_AI早报/_build"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --send) SEND=1; shift;;
    --no-send) SEND=0; shift;;
    --force) FORCE=1; shift;;
    --n) N="$2"; shift 2;;
    --build) BUILD="$2"; shift 2;;
    *) echo "未知参数 $1"; exit 2;;
  esac
done
OUT="$LIB/项目/早报邮件/$DATE"
mkdir -p "$OUT"
BARG=(); [[ -d "$BUILD" ]] && BARG=(--build "$BUILD")

# 沙箱重启会丢系统包：缺 chromium / 中文字体就装（约 20 秒；仅在临时容器里需要）
CJK=$(fc-list 2>/dev/null | grep -ci "Noto Serif CJK" || true)
if [[ ! -x /usr/bin/chromium || "${CJK:-0}" -eq 0 ]]; then
  echo "== 安装 chromium + fonts-noto-cjk =="
  { sudo apt-get update -qq && sudo apt-get install -y -qq chromium fonts-noto-cjk; } > "$OUT/.apt.log" 2>&1 \
    || { echo "chromium 安装失败，见 $OUT/.apt.log"; exit 1; }
fi
for t in node ffmpeg python3 curl; do command -v $t >/dev/null || { echo "缺少 $t"; exit 1; }; done

if [[ $SEND -eq 1 && -f "$OUT/send_result.json" && $FORCE -eq 0 ]]; then
  echo "已发送过（$OUT/send_result.json 存在），不重建也不重发；要重发加 --force"; exit 0
fi

echo "== news + images =="
python3 "$HERE/make_news.py" "$DATE" "$OUT" "${BARG[@]}" --n "$N"
cd "$OUT"
echo "== mjml =="
node "$HERE/build.mjs" cid
node "$HERE/build.mjs" local
echo "== screenshots =="
node "$HERE/shot.mjs" > /dev/null
echo "== eml =="
python3 "$HERE/mime.py"
echo "== qa =="
QA_OK=1; python3 "$HERE/qa.py" || QA_OK=0

if [[ $SEND -eq 1 ]]; then
  if [[ $QA_OK -eq 0 && $FORCE -eq 0 ]]; then
    echo "质检未通过（见 qa.json），不发送；确认无误可加 --force"; exit 1
  fi
  echo "== send =="
  if gws gmail users messages send --params '{"userId":"me"}' --upload message.eml --upload-content-type message/rfc822 > .send_out.json 2> send_err.txt \
     && python3 -c "import json,sys; d=json.load(open('.send_out.json')); sys.exit(0 if d.get('id') else 1)"; then
    python3 - <<'PY'
import json, datetime
d = json.load(open('.send_out.json'))
d['sent_at'] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
import os; d['to'] = os.environ.get('MAIL_TO', '')
d['subject'] = json.load(open('qa.json'))['subject']
json.dump(d, open('send_result.json', 'w'), ensure_ascii=False, indent=1)
PY
    rm -f .send_out.json
    echo "已发送: $(cat send_result.json | tr -d '\n')"
  else
    mv -f .send_out.json send_failed.json 2>/dev/null || true
    echo "发送失败，见 $OUT/send_err.txt / send_failed.json"; exit 1
  fi
fi
echo "输出: $OUT"
echo "预览: $OUT/preview_390.png  $OUT/preview_600.png"
[[ $QA_OK -eq 1 ]] || exit 1
