// Screenshot preview.html at 390 / 600 and write layout checks to .shot.json (cwd = day folder).
// Headless Chromium hangs on pages with several large animated GIFs (seen 2026-10-07), so the screenshot is taken of
// .preview_shot.html, a copy whose .gif srcs point at still PNGs (middle frame). The email keeps the real GIFs;
// GIF validity is checked separately (mime.py / qa.py).
import { chromium } from 'playwright';
import { execSync } from 'child_process';
import fs from 'fs';
const cwd = process.cwd();
fs.mkdirSync('.static', { recursive: true });
execSync(`python3 - <<'PY'
import glob, re
from PIL import Image
for f in glob.glob('gifs/*.gif') + glob.glob('official/*.gif'):
    im = Image.open(f); n = getattr(im, 'n_frames', 1); im.seek(n // 2)
    im.convert('RGB').save('.static/' + f.replace('/', '__') + '.png')
h = open('preview.html', encoding='utf-8').read()
h = re.sub(r'src="((?:gifs|official)/[^"]+\\.gif)"', lambda m: 'src=".static/' + m.group(1).replace('/', '__') + '.png"', h)
h = re.sub(r'<link[^>]+fonts\\.googleapis[^>]*>|@import url\\(https?://[^)]*\\);?', '', h)  # no network in screenshots
open('.preview_shot.html', 'w', encoding='utf-8').write(h)
PY`);
const b = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] });
const res = {};
for (const w of [390, 600]) {
  const p = await b.newPage({ viewport: { width: w, height: 800 }, deviceScaleFactor: 1 });
  await p.route(/^https?:/, r => r.abort());
  await p.goto('file://' + cwd + '/.preview_shot.html', { waitUntil: 'load', timeout: 60000 });
  await p.waitForTimeout(500);
  res[w] = await p.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const wide = [...document.querySelectorAll('img,table,div')].filter(e => e.getBoundingClientRect().right > vw + 1)
      .slice(0, 5).map(e => e.tagName + (e.getAttribute('src') ? ':' + e.getAttribute('src') : ''));
    return {
      scrollWidth: document.documentElement.scrollWidth, clientWidth: vw, overflow: document.documentElement.scrollWidth > vw + 1,
      overflowing_elements: wide, height: document.documentElement.scrollHeight,
      images: document.images.length,
      broken: [...document.images].filter(i => !i.complete || i.naturalWidth === 0).map(i => i.getAttribute('src')),
    };
  });
  await p.screenshot({ path: `preview_${w}.png`, fullPage: true, timeout: 60000 });
  await p.close();
}
await b.close();
fs.writeFileSync('.shot.json', JSON.stringify(res, null, 1));
console.log(JSON.stringify(res));
