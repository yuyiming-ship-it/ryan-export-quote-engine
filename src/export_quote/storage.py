"""Local private storage; OS permissions are the access boundary, not caller-supplied identities."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from .engine import digest
from .feishu import is_feishu_url, read_json_source, upload_snapshot


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load_rules(path=None):
    path = path or os.environ.get('EXPORT_QUOTE_RULES')
    if not path:
        return None
    pack = read_json_source(path)
    if pack.get('schema_version') != '1.0' or not pack.get('version'):
        raise ValueError('规则包需要 schema_version=1.0 和 version')
    if pack.get('status') != 'confirmed' or not pack.get('approved_by') or not pack.get('approved_at'):
        raise ValueError('规则包尚未经负责人确认；不能作为生效规则自动加载')
    for name in ('fee_rules', 'profit_targets', 'funding_options'):
        ids = [r.get('id') for r in pack.get(name, [])]
        if None in ids or len(ids) != len(set(ids)):
            raise ValueError(f'{name} 中规则 id 缺失或重复')
    return pack


def save_snapshot(result, root=None):
    configured = root or os.environ.get('EXPORT_QUOTE_STORE')
    feishu_root = configured if is_feishu_url(configured) else None
    root = Path.home() / '.export-quote' / 'quotes' if feishu_root else Path(configured or Path.home() / '.export-quote' / 'quotes')
    snapshot = {'saved_at': datetime.now(timezone.utc).isoformat(), 'result': result}
    path = root / (result['result_hash'] + '.json')
    if path.exists():
        if read_json(path)['result'] != result:
            raise ValueError('已有快照不一致，拒绝覆盖')
    else:
        private_write(path, snapshot)
    if feishu_root:
        upload_snapshot(path, feishu_root, Path.home() / '.export-quote' / 'feishu-uploaded')
    return str(path)


def verify_result(result):
    body = {k: v for k, v in result.items() if k != 'result_hash'}
    if digest(body) != result.get('result_hash'):
        raise ValueError('报价快照已变更，请重新计算')


def diff_rules(old, new):
    changed = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            changed.append({'field': key, 'before': old.get(key), 'after': new.get(key)})
    return {'old_hash': digest(old), 'candidate_hash': digest(new), 'changes': changed,
            'history_policy': '历史报价保留其规则快照，不随此次更新重算'}


def approve_rules(candidate, reviewer, expected_hash, output):
    if not reviewer.strip() or digest(candidate) != expected_hash:
        raise ValueError('负责人或候选规则摘要不匹配，请重新检查差异')
    candidate = dict(candidate)
    candidate.update({'status': 'confirmed', 'approved_by': reviewer,
                      'approved_at': datetime.now(timezone.utc).isoformat()})
    # Individual pending rules remain pending even when the pack is released.
    private_write(output, candidate)
    return {'path': str(output), 'hash': digest(candidate), 'version': candidate.get('version')}
