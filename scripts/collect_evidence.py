#!/usr/bin/env python3
"""Read-only lark-cli search collector. Config/output must be outside this repo.

python scripts/collect_evidence.py /private/search-config.json /private/evidence
Resumable, preserves every page and coverage. Never calls a write API.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def collect(job, root):
    key = hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()[:16]
    folder = root / key
    folder.mkdir(exist_ok=True)
    ledger = {'job': job, 'key': key, 'pages': 0, 'count': 0, 'complete': False}
    cursor = None
    seen = set()
    for page in range(1, 1001):
        path = folder / f'{page:04}.json'
        cmd = ['lark-cli'] + (['im', '+messages-search', '--no-reactions', '--page-size', '50']
                                if job['kind'] == 'im' else ['drive', '+search', '--page-size', '20'])
        cmd += ['--as', 'user', '--query', job['query']]
        for flag in ('start', 'end', 'chat-id', 'sender', 'created-since', 'created-until'):
            if job.get(flag):
                cmd += ['--' + flag, job[flag]]
        if cursor:
            cmd += ['--page-token', cursor]
        if path.exists():
            result = json.loads(path.read_text())
        else:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if proc.returncode:
                    ledger['error'] = proc.stderr[-2500:]
                    break
                result = json.loads(proc.stdout)
            except (subprocess.TimeoutExpired, ValueError) as exc:
                ledger['error'] = str(exc)
                break
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('ok') is not True:
            ledger['error'] = 'unsuccessful envelope'
            break
        data = result['data']
        ledger['count'] += len(data.get('messages', data.get('results', [])))
        ledger['pages'] = page
        ledger['has_more'] = data.get('has_more')
        cursor = data.get('page_token')
        ledger['next_cursor'] = cursor
        if data.get('has_more') is False:
            ledger['complete'] = True
            break
        if not cursor or cursor in seen:
            ledger['error'] = 'missing/repeated cursor; coverage incomplete'
            break
        seen.add(cursor)
    ledger['checked_at'] = datetime.now(timezone.utc).isoformat()
    (folder / 'coverage.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    return ledger


def main():
    os.umask(0o077)
    config, root = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    repo = Path(__file__).resolve().parents[1]
    if root == repo or repo in root.parents or config == repo or repo in config.parents:
        raise SystemExit('Private search config and evidence must be outside the public repository')
    root.mkdir(parents=True, exist_ok=True)
    jobs = json.loads(config.read_text())['jobs']
    ledgers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(collect, job, root) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            ledger = future.result()
            ledgers.append(ledger)
            print(json.dumps(ledger, ensure_ascii=False), flush=True)
            (root / 'coverage.json').write_text(json.dumps(ledgers, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
