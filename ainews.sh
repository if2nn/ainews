#!/usr/bin/env bash
# AI 早报竖屏短视频流水线 — 入口
# 用法: ainews.sh YYYY-MM-DD [--suffix _test] [--n 7] [--from STAGE] [--only STAGE]
#                 [--force-script] [--force-tts] [--asr] [--no-music] [--no-sfx]
# STAGE: fetch | script | tts | render | mux | qa
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="${AINEWS_LIB:-$HERE/output}"
DATE="${1:?用法: ainews.sh YYYY-MM-DD [options]}"; shift
SUFFIX=""; N=7; FROM="fetch"; ONLY=""; FS=""; FT=""; ASR=""; MUX_OPTS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suffix) SUFFIX="$2"; shift 2;;
    --n) N="$2"; shift 2;;
    --from) FROM="$2"; shift 2;;
    --only) ONLY="$2"; shift 2;;
    --force-script) FS="--force"; shift;;
    --force-tts) FT="--force"; shift;;
    --asr) ASR="--asr"; shift;;
    --no-music|--no-sfx) MUX_OPTS+=("$1"); shift;;
    *) echo "未知参数 $1"; exit 2;;
  esac
done
OUTDIR="$LIB/视频作品/${DATE}_AI早报"
WORK="$OUTDIR/_build"
OUT="$OUTDIR/${DATE}_AI早报${SUFFIX}.mp4"
LOCAL_MD="$LIB/项目/${DATE}_AI早报/juya.md"
mkdir -p "$WORK"
# keys (never echoed)
set +x; [[ -f "$HERE/.env" ]] && { set -a; source "$HERE/.env"; set +a; }
STAGES=(fetch script tts render mux qa)
run=0
for st in "${STAGES[@]}"; do
  [[ "$st" == "$FROM" ]] && run=1
  [[ -n "$ONLY" && "$st" != "$ONLY" ]] && continue
  [[ -z "$ONLY" && $run -eq 0 ]] && continue
  echo "== $st =="
  case "$st" in
    fetch)  python3 "$HERE/fetch.py" "$DATE" "$WORK" --local "$LOCAL_MD";;
    script) python3 "$HERE/gen_script.py" "$WORK" --n "$N" $FS;;
    tts)    python3 "$HERE/tts.py" "$WORK" $FT;;
    render) python3 "$HERE/render.py" "$WORK";;
    mux)    python3 "$HERE/mux.py" "$WORK" "$OUT" "${MUX_OPTS[@]}";;
    qa)     python3 "$HERE/qa.py" "$WORK" "$OUT" $ASR;;
  esac
done
echo "成片: $OUT"
