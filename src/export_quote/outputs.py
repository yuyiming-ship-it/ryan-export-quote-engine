"""Separate internal, customer, and MOSS views; never export raw snapshots to a customer."""
from __future__ import annotations
import csv
import io
from datetime import date
from .storage import verify_result


def customer_quote(result, as_of=None):
    verify_result(result)
    q = result['input_snapshot']
    today = date.fromisoformat(as_of) if as_of else date.today()
    expired = not q.get('valid_until') or date.fromisoformat(q['valid_until']) < today
    allowed = result['status'] != 'blocked' and result['mode'] == 'live' and not expired
    return {'type': 'customer_draft', 'status': result['status'] if allowed else 'unavailable',
            'requires_human_review': True, 'quote_id': q.get('quote_id'),
            'vehicles': [{k: v[k] for k in ('model', 'configuration', 'color', 'quantity') if k in v} for v in q['vehicles']],
            'currency': q.get('currency'), 'total_price': result['totals']['suggested_price'] if allowed else None,
            'trade_term': q.get('trade_term'), 'delivery_place': q.get('delivery_place'),
            'payment_terms': q.get('payment_terms'), 'valid_until': q.get('valid_until'),
            'included': q.get('customer_inclusions', []), 'excluded': q.get('customer_exclusions', []),
            'notice': '条件测算，待确认后报价' if result['status'] == 'conditional' else '报价草稿，需人工核对',
            'expired': expired}


def _get(obj, path):
    current = obj
    for part in path.split('.'):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def export_moss(result, mapping=None):
    verify_result(result)
    fields, unmapped = [], []
    mapping = mapping or {'version': 'unverified', 'fields': []}
    mapped = set()
    for rule in mapping.get('fields', []):
        value = _get(result, rule['source'])
        field = {'label': rule['label'], 'value': value, 'source': rule['source'],
                 'unit': rule.get('unit'), 'verification': rule.get('verification', 'unverified')}
        if rule.get('verification') != 'verified' or not rule.get('evidence'):
            field['reason'] = '字段尚未通过页面核验'
            unmapped.append(field)
        else:
            fields.append(field)
            mapped.add(rule['source'])
    for key, value in result['totals'].items():
        if f'totals.{key}' not in mapped:
            unmapped.append({'source': f'totals.{key}', 'value': value, 'reason': '无已核验的对应字段，不并入其他费用'})
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter='\t', lineterminator='\n')
    writer.writerow(['字段', '值', '单位/口径'])
    for field in fields:
        value = field['value']
        if isinstance(value, (dict, list)):
            import json
            value = json.dumps(value, ensure_ascii=False)
        # Prevent accidental formula execution when pasted into spreadsheets.
        value = '待补齐' if value is None else str(value)
        if value.startswith(('=', '+', '-', '@')):
            value = "'" + value
        writer.writerow([field['label'], value, field.get('unit') or ''])
    return {'quote_id': result['quote_id'], 'status': result['status'], 'mapping_version': mapping['version'],
            'fields': fields, 'unmapped': unmapped, 'clipboard_tsv': buf.getvalue(),
            'cost_details': result['lines'], 'issues': result['issues'], 'submit_automatically': False,
            'instructions': ['核对询价单、车型、数量、币种与交易边界', '只填写已核验字段，未映射项目单独核对',
                             '填写后逐字段回读，对比本次计算结果；保存和提交由人完成']}


def markdown_report(result):
    verify_result(result)
    t = result['totals']
    text = [f"# 报价测算 {result['quote_id']}", '', f"状态：{result['status']}；币种：{t['currency']}；未经业务审批。", '',
            f"已知成本：{t['known_cost']}；完整成本：{t['complete_cost'] or '待补齐'}；建议总售价：{t['suggested_price'] or '待补齐'}。", '',
            '| 费用 | 类别 | 原币 | 公式 | 折算金额 |', '|---|---|---|---|---|']
    def esc(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    for row in result['lines']:
        text.append('| ' + ' | '.join(esc(row.get(k, '—')) for k in ('name', 'category', 'currency', 'formula', 'total')) + ' |')
    text += ['', '## 待补齐与假设', '']
    text += [f"- {x['path']}：{x['message']}；确认人：{x.get('owner') or '待指派'}" for x in result['issues']] or ['无计算缺项；对客发送前仍需人工核对。']
    text += ['', '## 合作分配', '', *[f'- {k}：{t[k]}' for k in ('upstream_profit', 'our_profit', 'upstream_contract', 'contract_rounding_adjustment') if k in t],
             '', f"规则版本：{result['rules_version']}；快照摘要：{result['result_hash']}", '']
    return '\n'.join(text)
