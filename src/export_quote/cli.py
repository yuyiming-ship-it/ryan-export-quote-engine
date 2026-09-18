from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .engine import normalize_request, validate_quote, calculate_quote, compare_quotes, build_scenarios, screen_funders, digest
from .outputs import customer_quote, export_moss, markdown_report
from .storage import read_json, load_rules, save_snapshot, private_write, diff_rules, approve_rules


def main():
    parser = argparse.ArgumentParser(description='出口报价引擎；真实资料和结果请放在私有目录')
    parser.add_argument('command', choices=['normalize', 'funders', 'validate', 'calculate', 'compare', 'export-moss', 'customer', 'report', 'rules-diff', 'rules-approve', 'replay'])
    parser.add_argument('input', help='JSON 路径或 -（stdin）')
    parser.add_argument('--rules', help='已批准的私有规则包')
    parser.add_argument('--mapping', help='MOSS 页面字段映射')
    parser.add_argument('--out', help='输出文件；禁止覆盖既有文件')
    parser.add_argument('--store', help='不可变报价快照目录')
    parser.add_argument('--reviewer')
    parser.add_argument('--expected-hash')
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin) if args.input == '-' else read_json(args.input)
        rules = load_rules(args.rules) if args.command in ('funders', 'validate', 'calculate', 'compare') else None
        if args.command == 'normalize':
            result = normalize_request(data)
        elif args.command == 'funders':
            result = screen_funders(data, rules)
        elif args.command == 'validate':
            result = validate_quote(data, rules)
        elif args.command == 'calculate':
            result = calculate_quote(data, rules)
            path = save_snapshot(result, args.store)
            print('快照：' + path, file=sys.stderr)
        elif args.command == 'compare':
            requests = build_scenarios(data['base'], data['options']) if isinstance(data, dict) else data
            result = compare_quotes(requests, rules)
            for item in result['quotes']:
                save_snapshot(item, args.store)
        elif args.command == 'export-moss':
            result = export_moss(data.get('result', data), read_json(args.mapping) if args.mapping else None)
        elif args.command == 'customer':
            result = customer_quote(data.get('result', data))
        elif args.command == 'report':
            result = markdown_report(data.get('result', data))
        elif args.command == 'rules-diff':
            result = diff_rules(read_json(args.rules) if args.rules else {}, data)
        elif args.command == 'rules-approve':
            if not args.out or not args.reviewer or not args.expected_hash:
                raise ValueError('批准规则需 --reviewer --expected-hash --out（新版本路径）')
            result = approve_rules(data, args.reviewer, args.expected_hash, args.out)
            args.out = None
        else:
            from .storage import verify_result
            old = data.get('result', data)
            verify_result(old)
            replayed = calculate_quote(old['input_snapshot'], old['rules_snapshot'])
            result = {'identical': replayed == old, 'original_hash': old['result_hash'], 'recomputed_hash': replayed['result_hash']}
        if args.out:
            if isinstance(result, str):
                import os
                fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(result)
            else:
                private_write(args.out, result)
        else:
            print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and (result.get('status') == 'blocked' or result.get('valid') is False):
            return 2
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
