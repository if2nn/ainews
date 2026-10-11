# ainews · AI 早报竖屏短视频 + 邮件流水线

一条命令把当天的[橘鸦 AI 早报](https://daily.juya.uk)做成 1080×1920 竖屏快讯视频（配音、逐字高亮字幕、垫乐、音效、自动质检），也能出一封杂志版式的 HTML 邮件。

## 快速开始

```bash
git clone <this repo> && cd ainews
cp .env.example .env        # 填 SONIOX_KEY（配音/ASR）和 ORFREE_KEY（OpenRouter 免费模型写稿）
pip install pillow          # 另需系统 ffmpeg / ffprobe / curl
bash ainews.sh 2026-10-06 --suffix _test
```
成片在 `output/视频作品/<日期>_AI早报/`。邮件版另需 Node 18+：`cd email && npm install`。

新闻内容与配图版权归原作者/橘鸦所有，本仓库只含处理脚本。

---

# AI 早报竖屏短视频流水线（ainews）

把当天的「橘鸦 AI 早报」做成一支 1080×1920 / 30fps / 45–75 秒的竖屏快讯视频。
风格：报纸/电讯稿排版，暖白 `#fafaf9` / 炭黑 `#202020`，一镜一新闻，随稿配图卡，标题中英双语，旁白逐字高亮字幕。

## 一条命令

```bash
bash ainews.sh 2026-10-06            # 正式片
bash ainews.sh 2026-10-06 --suffix _test --asr
```

成片：`output/视频作品/<日期>_AI早报/<日期>_AI早报<suffix>.mp4`
中间文件：同目录 `_build/`（script.json、timing.json、audio/、segments/、qa/）。

### 参数
| 参数 | 作用 |
|---|---|
| `--suffix _test` | 输出文件名后缀 |
| `--n 7` | 选几条（5–7） |
| `--from STAGE` / `--only STAGE` | 从某一步开始 / 只跑某一步：`fetch script tts render mux qa` |
| `--force-script` | 丢掉已有 script.json 重新生成（默认保留，方便手改） |
| `--force-tts` | 强制重新配音（默认按文本缓存） |
| `--asr` | 质检时用 Soniox 云端 ASR 回听旁白，对比稿子找错读 |
| `--no-music` / `--no-sfx` | 不要垫乐 / 不要音效 |

## 推荐流程（要好片就过一遍编辑）

1. `ainews.sh DATE --only fetch && ainews.sh DATE --only script` → 生成 `_build/script.json` 草稿。
2. **人工/助手审稿**：免费 LLM 的草稿常见问题是旁白太长、数字写法怪（如“约五十%”）、选题偏向列表前几条。直接改 `script.json`：
   - `stories[]` 每条：`category`(要闻/模型/产品/行业)、`title_zh`(≤16 字)、`title_en`、`short`(片头目录用)、`narration`(一句话，约 30–45 字，数字写成中文读法)、`key`(大字，≤8 字符；`+50%`/`501B` 这类会滚动计数)、`key_label`、`tone`(light/dark)、`image`(可改成别的图 URL 或 null)。
   - 排序按 要闻 > 模型 > 产品 > 行业。
3. `ainews.sh DATE --from tts` → 配音、渲染、合成、质检。
4. 看 `_build/qa/contact_*.jpg`（2fps 联系表）和 `qa_report.json`。

## 各步做什么

| 步骤 | 脚本 | 说明 |
|---|---|---|
| fetch | `fetch.py` | 取 `https://daily.juya.uk/markdown/DATE.md`；失败用 `output/项目/DATE_AI早报/juya.md`，再失败用 RSS `https://daily.juya.uk/rss.xml`。解析成 `items.json`（分类、摘要、配图、链接）。每条 `images` 仍是 URL 字符串列表（视频取 images[0]），另有 `image_meta`（url/alt/kind=still|gif）；顶层 `cover_image` 为橘鸦封面 URL。 |
| script | `gen_script.py` | OpenRouter 免费模型（`ORFREE_KEY`，默认 `nvidia/nemotron-3-super-120b-a12b:free`，备用 `openrouter/free`，可用 `AINEWS_LLM_MODELS` 覆盖）选题+写旁白，自动二次缩写；LLM 不可用时用规则兜底。已有 script.json 只补缺字段。 |
| tts | `tts.py` | Soniox `tts-rt-v2`，voice = `SONIOX_VOICE`（预置名或你自己克隆的音色 id，默认 `Adrian`），失败自动换预置 `Adrian`。PCM→去首尾静音→`atempo 1.10`（`AINEWS_TTS_SPEED` 可调）→48k wav。镜头时长 = 0.30s 前置 + 实际语音 + 0.50s 收尾，按帧取整，写入 `timing.json`。 |
| render | `render.py` | Pillow 逐帧绘制 → ffmpeg x264，每镜一个片段（约 35 秒渲完全片）。`--still` 每镜出一张静帧，`--shots 2-4` 只渲部分。会写 `layout_warnings.json`（越出安全区、字幕超 3 行等）。 |
| mux | `mux.py` | 片段无损拼接；旁白按 `voice_at` 对位；垫乐用代码合成的原创 pad（或放一首到 `assets/music/` 自动使用），侧链压低在人声下约 14 dB；切镜 whoosh + 编号 click + 片头目录 pop；loudnorm −16 LUFS。 |
| qa | `qa.py` | ffprobe（分辨率/帧率/时长/音轨）、黑帧、每镜人声电平、旁白是否超出镜头、2fps 联系表，`--asr` 回听对稿。 |

## 画面规范（render.py 顶部可改）
- 安全区：左右 84px，内容不低于 y=1670（下方留给平台 UI）。
- 每镜结构：编号方块 + 分类（中/英）→ 英文眉题（衬线大写）→ 中文大标题（≥72px 单行，否则均衡两行）→ 随稿配图卡（长图自动缓慢滚动）+ 图注域名 → 关键数字（可计数）→ 旁白字幕（随语音逐字变深）→ 来源行。顶部进度轨按镜头点亮。
- 无配图的条目改为反色大字卡。要闻镜头和倒数第二镜默认用炭黑底制造节奏。

## 依赖与素材
- 只用系统已有的 python3 + Pillow + ffmpeg/ffprobe + curl，不装浏览器、本地 TTS/ASR、LaTeX。
- 字体：`fonts/` 下 Noto Sans SC / Noto Serif SC（SIL OFL 1.1，见 `fonts/LICENSE.txt`）。
- 音效：`assets/sfx/`，来自 guizang-product-video-skill 的 `make_sfx.py` 原创合成音（无第三方录音）。
- 密钥：复制 `.env.example` 为 `.env` 填入（`SONIOX_KEY`、`ORFREE_KEY` 等），脚本只读取，不打印；`.env` 已在 .gitignore 里。

## 邮件版（Plan A+ 杂志配图版，`email/`）

同一天的 fetch 结果 + 审过的 `script.json` → 一封 HTML 邮件（Plan A+ 杂志版式）。

```bash
# 只生成+截图+质检（默认）
bash email/email.sh 2026-10-08
# 生成并发送到 .env 里的 MAIL_TO（需要已登录的 gws CLI）
bash email/email.sh 2026-10-08 --send
```

输出：`output/项目/早报邮件/<日期>/`：`news.json`、`email.html`（cid 版，发信用）、`preview.html`、`preview_390.png` / `preview_600.png`、`qa.json`、`message.eml`、发送后 `send_result.json`。

**每日任务顺序**：`ainews.sh DATE --only fetch` → `--only script` → 审 `_build/script.json`（选 5–8 条）→ 写点评 `output/项目/早报邮件/DATE/DATE_comments.json` → `email.sh DATE --send` → 看 `qa.json` / 预览图。

| 参数 | 作用 |
|---|---|
| `--send` / `--no-send` | 发送 / 只生成（默认） |
| `--force` | `send_result.json` 已存在也重发；或质检不过也强行发 |
| `--n 8` | 没有 script.json 时按规则选几条（5–8） |
| `--build DIR` | 指定视频 `_build` 目录（默认 `output/视频作品/DATE_AI早报/_build`） |

点评文件格式（没有就不出“给你的点评”区）：
```json
{"notes": ["🟢 开放/免费模型……", "🟡 ……", "🔴 ……"], "lead": "可选：导语一句", "headline": "可选：覆盖标题/邮件主题"}
```
圆点颜色由开头 emoji 决定（🟢 绿 / 🟡 黄 / 🔴 红）。2–3 条。

各步：
| 脚本 | 说明 |
|---|---|
| `make_news.py` | 读 `items.json`（旧版缺 `image_meta`/`cover_image` 时自动用同目录 `juya.md` 重新解析；没有 `_build` 就跑 `fetch.py` 到 `输出/_fetch`）；选题优先 `script.json` 的 `stories[].num`，否则按 要闻>模型>产品>行业 取前 N；按分类排序。正文 = 橘鸦摘要原文（引用块），标题 = 橘鸦原标题，来源 = script 的 `source` 或域名。数字大字：script 的 `key`（含数字才用）+`key_label`，否则从摘要正则抽（%/B/亿/倍/TPS…），抽不到不放。每条最多 2 张橘鸦配图：静图 JPEG q82 ≤1080 宽；GIF 用 ffmpeg 双遍调色板压到 <400KB（先降帧率/色数再降宽度，压不下去改首帧 JPEG）。整封预算 message.eml < 3MB：超了先压 GIF→删 GIF→静图改 720/q75→删第二张图→删图。封面故事 = 第 1 条（script `title_zh`，最后一个词标红；有“A → B 单位”优先做大数字，避免与标题重复）；要点 = 第 2–5 条 `short`。封面动效 GIF（`render_cover.mjs` + `anim.html`）每天重渲，底部一行 = 前 4 条的英文名（≤44 字符）。`title.gif` 和无图条目的图标（模型=芯片 icon2、产品=画框 icon4、其他=文档 icon3）用 `email/assets/` 固定素材。 |
| `build.mjs` | MJML → `email.html`（`cid:xxx@aizaobao`）和 `preview.html`（本地路径）。 |
| `shot.mjs` | 390 / 600 宽全页截图 + 溢出/坏图检查。截图用 `.preview_shot.html`：GIF 换成中间帧 PNG、去掉 Google Fonts 外链（外链会让 headless chromium 卡死）。 |
| `mime.py` | `message.eml`：multipart/alternative（纯文本 + HTML），HTML 内 multipart/related 内联 CID 图；校验 HTML 里每个 cid 都有对应附件。From `$MAIL_FROM`，To `$MAIL_TO`，主题 `AI 早报 YYYY-MM-DD｜<标题>`。 |
| `qa.py` | `qa.json`：eml 大小 <3MB、HTML <102KB（Gmail 截断线）、条数 5–8、390/600 无横向溢出、无坏图、正文 GIF <400KB、MJML 无错误、页脚在。任一不过则退出码 1，`--send` 也不会发（除非 `--force`）。 |
| 发送 | `gws gmail users messages send --params '{"userId":"me"}' --upload message.eml --upload-content-type message/rfc822`；成功写 `send_result.json`（id/threadId/sent_at），失败写 `send_failed.json` + `send_err.txt`。`send_result.json` 存在时 `--send` 直接退出、不重建不重发。 |

环境：沙箱重启会丢系统包，脚本发现没有 `/usr/bin/chromium` 或 Noto CJK 字体会自动 `sudo apt-get install chromium fonts-noto-cjk`（约 20 秒）。node 依赖（mjml、playwright）在 `email/node_modules`。

已知限制：导语/封面标题是规则生成（有 `DATE_comments.json` 的 `lead`/`headline` 就用它们）；橘鸦配图多为截图，alt 文本多为“配图：标题”；数字自动抽取只认阿拉伯数字（橘鸦偶尔写“一万亿”这类中文数字），有 script.json 的 `key` 时以它为准。

## 已知限制
- 免费 LLM 草稿质量不稳，正式发布前建议按上面第 2 步审稿。
- 垫乐是代码合成的简单 pad + 拨弦，偏“能用”；有更好的授权音乐放进 `assets/music/` 即可替换。
- juya 配图多为推文/网页截图，信息由中文排版承担，图只作“随稿附图”。
