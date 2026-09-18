"""Small lark-cli adapter for private Feishu rule documents and snapshot folders."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess


FEISHU_HOSTS = ('.feishu.cn', '.larksuite.com')


def is_feishu_url(value):
    return isinstance(value, str) and value.startswith('https://') and any(host in value.split('/', 3)[2] for host in FEISHU_HOSTS)


def _identity():
    identity = os.environ.get('EXPORT_QUOTE_FEISHU_IDENTITY', 'user')
    if identity not in ('user', 'bot'):
        raise ValueError('EXPORT_QUOTE_FEISHU_IDENTITY 仅支持 user 或 bot')
    return identity


def _run_lark(args, cwd=None):
    binary = shutil.which('lark-cli')
    if not binary:
        raise ValueError('配置使用飞书地址，但未找到 lark-cli；请先安装并登录飞书 CLI')
    try:
        completed = subprocess.run([binary, *args], cwd=cwd, text=True, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('lark-cli 操作超时，请检查网络后重试') from exc
    except OSError as exc:
        raise ValueError(f'lark-cli 无法启动：{exc}') from exc
    try:
        envelope = json.loads(completed.stdout or completed.stderr)
    except json.JSONDecodeError as exc:
        raise ValueError('lark-cli 未返回可解析的 JSON') from exc
    if completed.returncode or not envelope.get('ok'):
        message = envelope.get('error', {}).get('message') or '飞书读取或写入失败'
        raise ValueError(message)
    return envelope['data']


def _extract_json_document(markdown):
    candidates = re.findall(r'```json\s*(\{.*?\})\s*```', markdown, re.DOTALL)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if value.get('schema_version'):
            return value
    raise ValueError('飞书文档中没有找到包含 schema_version 的有效 JSON 代码块')


def read_json_source(source):
    """Read a local JSON path or fetch the executable JSON block from a Feishu doc."""
    if not is_feishu_url(source):
        return json.loads(Path(source).read_text(encoding='utf-8'))
    data = _run_lark(['docs', '+fetch', '--doc', source, '--doc-format', 'markdown',
                      '--scope', 'keyword', '--keyword', 'schema_version',
                      '--as', _identity(), '--format', 'json'])
    return _extract_json_document(data['document']['content'])


def folder_token(source):
    if not is_feishu_url(source):
        return None
    match = re.search(r'/drive/folder/([^/?#]+)', source)
    if not match:
        raise ValueError('EXPORT_QUOTE_STORE 的飞书地址必须是 /drive/folder/<token>')
    return match.group(1)


def upload_snapshot(path, folder_url, marker_root):
    """Upload once per result hash; an absent marker means a failed upload can retry."""
    token = folder_token(folder_url)
    path = Path(path)
    marker = Path(marker_root) / token / (path.stem + '.json')
    if marker.exists():
        return json.loads(marker.read_text(encoding='utf-8'))
    data = _run_lark(['drive', '+upload', '--file', path.name, '--folder-token', token,
                      '--name', path.name, '--as', _identity(), '--format', 'json'], cwd=path.parent)
    marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return json.loads(marker.read_text(encoding='utf-8'))
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)
    return data
