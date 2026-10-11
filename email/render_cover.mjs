// Render the animated cover GIF (approved Plan A+ design) with a per-day caption line.
// Usage: node render_cover.mjs OUT_GIF "GPT-6 · BEAM · RHO-1"
import { chromium } from 'playwright';
import { execSync } from 'child_process';
import fs from 'fs'; import os from 'os'; import path from 'path'; import { fileURLToPath } from 'url';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const [out, cap = ''] = process.argv.slice(2);
const N = 36, FPS = 12, W = 600, H = 380;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cover-'));
const b = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] });
const p = await b.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 2 });
await p.goto('file://' + HERE + '/anim.html?m=cover&cap=' + encodeURIComponent(cap));
await p.waitForTimeout(400);
for (let i = 0; i < N; i++) {
  await p.evaluate(t => render(t), i / N);
  await p.screenshot({ path: `${tmp}/${String(i).padStart(3, '0')}.png` });
}
await b.close();
fs.mkdirSync(path.dirname(out), { recursive: true });
execSync(`ffmpeg -y -loglevel error -framerate ${FPS} -i ${tmp}/%03d.png -vf "split[a][b];[a]palettegen=max_colors=64:stats_mode=full[p];[b][p]paletteuse=dither=none" -loop 0 "${out}"`);
fs.rmSync(tmp, { recursive: true, force: true });
console.log('cover', out, fs.statSync(out).size);
