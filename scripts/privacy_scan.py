#!/usr/bin/env python3
"""Small release guard for company evidence accidentally copied into the public tree."""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else '.')
skip = {'.git', '.venv', '__pycache__', 'build', 'dist'}
patterns = {
    'Feishu tenant links': re.compile(r'https://[^/]*feishu\.cn/(?:docx|sheets|wiki)/'),
    'MOSS production host': re.compile(r'https?://moss\.[^\s/]+'),
    'private sibling path': re.compile(r'价格引擎-private'),
}
hits = []
for path in root.rglob('*'):
    if not path.is_file() or any(part in skip for part in path.parts):
        continue
    if path.resolve() == Path(__file__).resolve():
        continue
    try:
        text = path.read_text(errors='strict')
    except (UnicodeDecodeError, OSError):
        continue
    for name, pattern in patterns.items():
        if pattern.search(text):
            hits.append(f'{path}: {name}')
if hits:
    print('\n'.join(hits), file=sys.stderr)
    raise SystemExit(1)
print('privacy scan passed')
