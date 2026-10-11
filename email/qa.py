#!/usr/bin/env python3
"""Write qa.json for a built day folder (cwd). Exit 1 if a hard check fails."""
import json, os, re, sys

d = json.load(open('news.json', encoding='utf-8'))
shot = json.load(open('.shot.json')) if os.path.exists('.shot.json') else {}
html = open('email.html', encoding='utf-8').read()
eml = os.path.getsize('message.eml') if os.path.exists('message.eml') else None
errs = []
for m in ('cid', 'local'):
    p = f'.mjml_errors_{m}.json'
    if os.path.exists(p):
        errs += json.load(open(p))
imgs = [o for x in d['items'] for o in x['images']]
files = sorted(set(['gifs/title.gif', 'gifs/cover.gif'] + [f"gifs/{x['icon']}.gif" for x in d['items'] if x.get('icon') and not x['images']]
                   + [o['file'] for o in imgs] + ([d['cover_image']['file']] if d.get('cover_image') else [])))
sizes = {f: os.path.getsize(f) for f in files}
gif_over = [f for f in files if f.startswith('official/') and f.endswith('.gif') and sizes[f] > 400_000]
checks = {
    'items_5_to_8': 5 <= len(d['items']) <= 8,
    'eml_under_3MB': eml is not None and eml < 3_000_000,
    'html_under_102KB_gmail_clip': len(html.encode()) < 102_000,
    'no_overflow_390': not shot.get('390', {}).get('overflow', True),
    'no_overflow_600': not shot.get('600', {}).get('overflow', True),
    'no_broken_images': not any(shot.get(w, {}).get('broken') for w in ('390', '600')) and bool(shot),
    'article_gifs_under_400KB': not gif_over,
    'mjml_no_errors': not errs,
    'footer_present': '内容来源：橘鸦 AI 早报 · 由 Hark 编排' in html,
}
qa = {
    'date': d['date'], 'ok': all(checks.values()), 'checks': checks,
    'subject': f"AI 早报 {d['date']}｜{d['headline']}",
    'eml_bytes': eml, 'html_bytes': len(html.encode()), 'inline_asset_bytes': sum(sizes.values()),
    'item_count': len(d['items']), 'article_image_count': len(imgs), 'gif_count': sum(f.endswith('.gif') for f in files),
    'inline_part_count': len(files), 'cover_image': bool(d.get('cover_image')), 'notes_count': len(d.get('notes') or []),
    'selection': d.get('selection'), 'items': [{'num': x['num'], 'tag': x['tag'], 'title': x['title'], 'images': len(x['images']),
                                                'callout': (x.get('callout') or {}).get('big')} for x in d['items']],
    'asset_sizes': sizes, 'layout': shot, 'mjml_errors': errs,
    'warnings': d.get('warnings', []), 'budget_actions': d.get('budget_actions', []),
}
json.dump(qa, open('qa.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('[qa]', 'OK' if qa['ok'] else 'FAIL', {k: v for k, v in checks.items() if not v} or '', f"eml={eml} images={len(imgs)}")
sys.exit(0 if qa['ok'] else 1)
