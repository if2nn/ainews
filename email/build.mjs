// AI 早报 email — Plan A+ 配图版 (Plan A+ layout).
// Usage (cwd = day folder with news.json): node build.mjs cid|local
import mjml2html from 'mjml';
import fs from 'fs';

const d = JSON.parse(fs.readFileSync('news.json', 'utf8'));
const MODE = process.argv[2] || 'cid'; // cid -> email.html ; local -> preview.html
const img = n => MODE === 'cid' ? `cid:${n}@aizaobao` : `gifs/${n}.gif`;
const oimg = o => MODE === 'cid' ? `cid:${o.cid}@aizaobao` : o.file;
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escA = s => esc(s).replace(/"/g, '&quot;');

const CREAM = '#F1EBDD', INK = '#141210', VERM = '#E8452C', PAPER = '#FBF8F1', MUTED = '#4a443c';
const serif = "'Songti SC','Noto Serif CJK SC','Source Han Serif SC',STSong,Georgia,serif";
const sans = "'PingFang SC','Noto Sans CJK SC','Microsoft YaHei','Helvetica Neue',Arial,sans-serif";
const TAG = { 要闻: VERM, 模型: '#2B4BDB', 开发: '#0F8A5F', 产品: '#7A3FD1', 行业: '#B7791F', 争议: '#C0262D' };

const card = (x, i) => {
  const e = x.callout || {};
  const c = TAG[x.tag] || VERM;
  const num = String(i + 1).padStart(2, '0');
  const head = `
   <mj-text padding="0 0 6px" font-family="${sans}" font-size="11px" letter-spacing="2px" font-weight="700" color="${INK}"><span style="color:${INK}">${num}</span>&nbsp;&nbsp;<span style="background-color:${c};color:#FFFFFF;padding:2px 7px;border-radius:3px;letter-spacing:1px">${esc(x.tag)}</span></mj-text>
   <mj-text padding="0 0 8px" font-family="${serif}" font-size="19px" line-height="1.4" font-weight="900" color="${INK}">${esc(x.title)}</mj-text>`;
  const body = `
   <mj-text padding="0" font-family="${sans}" font-size="14px" line-height="1.75" color="${MUTED}">${esc(x.body)}</mj-text>`;
  const callout = e.big ? `
   <mj-text padding="12px 0 0" font-family="${serif}" font-size="34px" line-height="1.1" font-weight="900" color="${VERM}">${esc(e.big)}</mj-text>${e.small ? `
   <mj-text padding="2px 0 0" font-family="${sans}" font-size="12px" letter-spacing="1px" color="${MUTED}">${esc(e.small)}</mj-text>` : ''}` : '';
  const src = `
   <mj-text padding="12px 0 0" font-family="${sans}" font-size="12px" color="#8a8276"><a href="${escA(x.url)}" target="_blank" style="color:#8a8276;text-decoration:underline">来源：${esc(x.src)} ↗</a></mj-text>`;
  const ims = (x.images || []).slice(0, 2);
  const pics = ims.map((o, k) => `
   <mj-image src="${oimg(o)}" alt="${escA(o.alt)}" border-radius="6px" padding="${k ? '8px' : '4px'} 0 ${k === ims.length - 1 ? '12px' : '0'}" />`).join('');
  const inner = head + pics + body + callout + src;
  if (x.icon && !ims.length) {
    return `
<mj-section background-color="${CREAM}" padding="0 20px 12px"><mj-group background-color="${PAPER}">
 <mj-column width="22%" background-color="${PAPER}" padding="20px 0 20px 16px" border-top="3px solid ${INK}" vertical-align="top"><mj-image src="${img(x.icon)}" width="64px" padding="0" align="left" alt="" /></mj-column>
 <mj-column width="78%" background-color="${PAPER}" padding="20px 18px 20px 6px" border-top="3px solid ${INK}" vertical-align="top">${inner}
 </mj-column></mj-group></mj-section>`;
  }
  return `
<mj-section background-color="${CREAM}" padding="0 20px 12px"><mj-column background-color="${PAPER}" padding="20px 18px" border-top="3px solid ${INK}">${inner}
</mj-column></mj-section>`;
};

const dot = { '🟡': '#F2B82E', '🟢': '#3BB273', '🔴': VERM };
const notes = (d.notes || []).map(n => {
  let color = '#F2B82E';
  for (const k of Object.keys(dot)) if (n.startsWith(k)) { color = dot[k]; n = n.slice(k.length).trim(); }
  n = n.replace(/🐱/g, '').trim();
  return `<mj-text padding="12px 0 0" font-family="${sans}" font-size="14px" line-height="1.75" color="#E9E2D3"><span style="color:${color}">●</span>&nbsp; ${esc(n)}</mj-text>`;
}).join('\n');
const notesSection = notes ? `
<mj-section background-color="${CREAM}" padding="10px 20px 26px"><mj-column background-color="${INK}" padding="22px 20px">
 <mj-text font-family="${serif}" font-size="20px" font-weight="900" color="${CREAM}">给你的点评</mj-text>
 ${notes}
</mj-column></mj-section>` : `
<mj-section background-color="${CREAM}" padding="0 0 14px"><mj-column background-color="${CREAM}"><mj-text font-size="1px" line-height="1px">&nbsp;</mj-text></mj-column></mj-section>`;

// cover story (auto from item 1)
const cv = d.cover;
// headline size from estimated width: CJK glyph = 1em, latin/digits ≈ .55em (fits 552px desktop / 342px mobile)
const units = [...(cv.pre + ' ' + cv.hi)].reduce((a, ch) => a + (/[\u3000-\u9fff\uff00-\uffef]/.test(ch) ? 1 : .55), 0);
const hlSize = Math.max(28, Math.min(44, Math.floor(540 / units)));
const hlMobile = Math.max(24, Math.min(36, Math.floor(330 / units)));
const bColors = [CREAM, '#F2B82E', '#2B4BDB', VERM];
const bullets = cv.bullets.map((b, i) => `<span style="color:${bColors[i % 4]}">●</span> ${esc(b)}`).join('<br/>');
// cover number: avoid repeating the headline's figure; prefer an "A → B unit" expression from the label (approved look)
let co = cv.callout && { ...cv.callout };
if (co && co.big) {
  const digits = (co.big.match(/\d[\d.]*/) || [''])[0];
  const arrow = (co.small || '').match(/(\d[\d.,]*\s*→\s*\d[\d.,]*)\s*([A-Za-z%]+)?/);
  if (arrow) co = { big: arrow[1], small: arrow[2] || '' };
  else if (digits && (cv.pre + cv.hi).includes(digits)) co = null;
}
const coverNum = co && co.big ? `
 <mj-text css-class="cover-num" padding="14px 0 0" font-family="${serif}" font-size="52px" line-height="1.05" font-weight="900" color="${CREAM}">${esc(co.big).replace(/→/g, `<span style="color:${VERM}">→</span>`)}${co.small && [...co.small].length <= 12 ? ` <span style="font-size:20px;letter-spacing:2px;color:#bdb5a6">${esc(co.small)}</span>` : ''}</mj-text>${co.small && [...co.small].length > 12 ? `
 <mj-text padding="6px 0 0" font-family="${sans}" font-size="12px" letter-spacing="2px" color="#bdb5a6">${esc(co.small)}</mj-text>` : ''}` : '';

const src = `<mjml lang="zh-CN"><mj-head>
<mj-title>AI 早报 · ${d.dotdate}</mj-title>
<mj-preview>${esc(d.lead)}</mj-preview>
<mj-raw><meta name="color-scheme" content="light only" /><meta name="supported-color-schemes" content="light only" /></mj-raw>
<mj-attributes><mj-all padding="0" /></mj-attributes>
<mj-style>
:root{color-scheme:light only;supported-color-schemes:light only}
body,.body{background-color:${INK} !important}
a{color:inherit}
@media only screen and (max-width:480px){.cs-big div{font-size:${hlMobile}px !important}.cover-num div{font-size:40px !important}}
</mj-style>
</mj-head>
<mj-body background-color="${INK}" width="600px">
<mj-section background-color="${CREAM}" padding="18px 24px 6px"><mj-group>
 <mj-column width="50%" background-color="${CREAM}"><mj-text font-family="${sans}" font-size="10px" letter-spacing="3px" font-weight="700" color="${INK}">${d.vol}</mj-text></mj-column>
 <mj-column width="50%" background-color="${CREAM}"><mj-text align="right" font-family="${sans}" font-size="10px" letter-spacing="3px" font-weight="700" color="${INK}">${d.weekday_en} · ${d.datestr}</mj-text></mj-column>
</mj-group></mj-section>
<mj-section background-color="${CREAM}" padding="0"><mj-column background-color="${CREAM}"><mj-image src="${img('title')}" width="600px" alt="AI 早报" /></mj-column></mj-section>
<mj-section background-color="${CREAM}" padding="8px 24px 18px"><mj-column background-color="${CREAM}">
 <mj-text font-family="${serif}" font-size="15px" font-style="italic" color="${INK}">The Morning Machine — 本期精选 ${d.items.length} 条</mj-text>
 <mj-text padding="8px 0 0" font-family="${sans}" font-size="14px" line-height="1.7" color="${MUTED}">${esc(d.lead)}</mj-text>
</mj-column></mj-section>
<mj-section padding="0" background-color="${INK}"><mj-column background-color="${INK}"><mj-image src="${img('cover')}" width="600px" alt="封面动效" /></mj-column></mj-section>
<mj-section background-color="${INK}" padding="10px 24px 30px"><mj-column background-color="${INK}">
 <mj-text font-family="${sans}" font-size="11px" letter-spacing="4px" color="#F2B82E" font-weight="700" padding="0 0 10px">COVER STORY</mj-text>
 ${d.cover_image ? `<mj-image src="${oimg(d.cover_image)}" alt="${escA(d.cover_image.alt)}" border-radius="6px" padding="0 0 16px" />` : ''}
 <mj-text css-class="cs-big" font-family="${serif}" font-size="${hlSize}px" line-height="1.12" font-weight="900" color="${CREAM}">${esc(cv.pre)} <span style="color:${VERM}">${esc(cv.hi)}</span></mj-text>${coverNum}
 <mj-text font-family="${sans}" font-size="14px" line-height="1.7" color="#bdb5a6" padding="10px 0 18px">${esc(cv.summary)}</mj-text>
 <mj-divider border-color="${CREAM}" border-width="1px" padding="0 0 14px" />
 <mj-text font-family="${serif}" font-size="16px" line-height="1.75" color="${CREAM}" font-weight="700">${bullets}</mj-text>
</mj-column></mj-section>
<mj-section background-color="${CREAM}" padding="28px 24px 14px"><mj-column background-color="${CREAM}">
 <mj-text font-family="${serif}" font-size="28px" font-weight="900" color="${INK}">本期要闻</mj-text>
</mj-column></mj-section>
${d.items.map(card).join('\n')}
${notesSection}
<mj-section background-color="${VERM}" padding="20px 24px"><mj-column background-color="${VERM}">
 <mj-text font-family="${sans}" font-size="11px" letter-spacing="2px" color="${INK}" font-weight="700">内容来源：橘鸦 AI 早报 · 由 Hark 编排</mj-text>
</mj-column></mj-section>
</mj-body></mjml>`;

fs.writeFileSync('email.mjml', src);
const r = await mjml2html(src, { validationLevel: 'soft' });
if (r.errors.length) console.error(JSON.stringify(r.errors, null, 1));
const out = MODE === 'cid' ? 'email.html' : 'preview.html';
fs.writeFileSync(out, r.html);
fs.writeFileSync(`.mjml_errors_${MODE}.json`, JSON.stringify(r.errors));
console.log(out, r.html.length, 'errors', r.errors.length);
