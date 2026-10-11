#!/usr/bin/env python3
"""Build message.eml (multipart/alternative text+html, html multipart/related with inline CID images).
Usage (cwd = day folder): mime.py   -> message.eml ; asserts every cid: in email.html has a part.
"""
import json, re
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from PIL import Image

import os
FROM, TO = os.environ.get('MAIL_FROM', 'me@example.com'), os.environ.get('MAIL_TO', 'you@example.com')
d = json.load(open('news.json', encoding='utf-8'))
html = open('email.html', encoding='utf-8').read()


def plain(n):
    for e in ('🟡', '🟢', '🔴', '🐱'):
        n = n.replace(e, '')
    return n.strip()


cv = d['cover']
lines = [f"AI 早报 · {d['date']}", '', d['lead'], '',
         f"COVER STORY：{cv['pre']} {cv['hi']}" + (f" —— {cv['callout']['big']} {cv['callout'].get('small', '')}".rstrip() if cv.get('callout') else ''),
         cv['summary'], '']
for i, x in enumerate(d['items'], 1):
    lines += [f"{i:02d} [{x['tag']}] {x['title']}", x['body'], f"来源：{x['src']} {x['url']}", '']
if d.get('notes'):
    lines += ['给你的点评'] + ['· ' + plain(n) for n in d['notes']] + ['']
lines += ['内容来源：橘鸦 AI 早报 · 由 Hark 编排']

msg = EmailMessage()
msg['From'] = FROM
msg['To'] = TO
msg['Subject'] = f"AI 早报 {d['date']}｜{d['headline']}"
msg['Date'] = formatdate(localtime=True)
msg['Message-ID'] = make_msgid(domain='gmail.com')
msg.set_content('\n'.join(lines))
msg.add_alternative(html, subtype='html')
html_part = msg.get_payload()[1]

parts = [('title', 'gifs/title.gif'), ('cover', 'gifs/cover.gif')]
parts += [(ic, f'gifs/{ic}.gif') for ic in sorted({x['icon'] for x in d['items'] if x.get('icon') and not x['images']})]
if d.get('cover_image'):
    parts.append((d['cover_image']['cid'], d['cover_image']['file']))
for x in d['items']:
    for o in x.get('images', [])[:2]:
        parts.append((o['cid'], o['file']))
refs = set(re.findall(r'cid:([A-Za-z0-9_]+)@aizaobao', html))
assert refs == {n for n, _ in parts}, ('cid mismatch', refs ^ {n for n, _ in parts})
for n, f in parts:
    data = open(f, 'rb').read()
    sub = 'gif' if f.endswith('.gif') else 'jpeg'
    if f.startswith('gifs/') and n in ('title', 'cover'):
        assert Image.open(f).n_frames > 1, f
    html_part.add_related(data, maintype='image', subtype=sub, cid=f'<{n}@aizaobao>',
                          disposition='inline', filename=f.split('/')[-1])
raw = msg.as_bytes()
open('message.eml', 'wb').write(raw)
print('message.eml', len(raw), 'bytes;', len(parts), 'inline parts; subject:', msg['Subject'])
