"""Pure quotation functions. No network, arbitrary formulas, or MOSS mutations.

Money and rates cross the interface as decimal strings. Rules are data, never code.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_CEILING, localcontext
import hashlib
import itertools
import json

VERSION = '1.0'
CATEGORIES = ('vehicle', 'transport', 'funding')
PARTIES = ('ours', 'upstream', 'customer')
STATES = ('confirmed', 'estimated', 'pending', 'historical', 'expired', 'conflict')


def decimal(value):
    if isinstance(value, (bool, float)) or value is None:
        raise ValueError('金额、费率必须使用十进制字符串，不接受浮点数、布尔或空值')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('无效十进制数') from exc
    if not result.is_finite() or abs(result) > Decimal('1e18'):
        raise ValueError('数值必须有限且绝对值不超过 1e18')
    return result


def number(value):
    return format(value, 'f')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def normalize_request(request):
    """Normalize a structured request; text is preserved for an AI to extract, never guessed."""
    if isinstance(request, str):
        return {'schema_version': VERSION, 'raw_input': request, 'vehicles': [], 'costs': [],
                'missing': ['请 AI 从原文提取车型、数量、交易条件和费用，并逐项保留来源']}
    if not isinstance(request, dict):
        raise ValueError('request 必须是对象或原始询价文本')
    out = deepcopy(request)
    out.setdefault('schema_version', VERSION)
    out.setdefault('vehicles', [])
    out.setdefault('costs', [])
    out.setdefault('fx', {})
    out.setdefault('exclusions', [])
    out.setdefault('assumptions', [])
    out.setdefault('coverage', {})
    out.setdefault('mode', 'live')
    for key in ('vehicles', 'costs', 'exclusions', 'assumptions'):
        if not isinstance(out[key], list):
            raise ValueError(f'{key} 必须是数组')
    for key in ('fx', 'coverage'):
        if not isinstance(out[key], dict):
            raise ValueError(f'{key} 必须是对象')
    for item in out['vehicles'] + out['costs']:
        if not isinstance(item, dict):
            raise ValueError('车型与费用行必须是对象')
        for field in ('id', 'component', 'name', 'model', 'currency', 'source', 'status', 'included_in'):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f'{field} 必须为字符串')
        for field in ('vehicle_ids', 'includes'):
            if field in item and (not isinstance(item[field], list) or any(not isinstance(x, str) for x in item[field])):
                raise ValueError(f'{field} 必须为字符串数组')
        for field in ('bearers', 'weights', 'applies_to'):
            if field in item and not isinstance(item[field], dict):
                raise ValueError(f'{field} 必须为对象')
    for key in ('profit_target', 'profit_shares', 'sale_price'):
        if key in out and not isinstance(out[key], dict):
            raise ValueError(f'{key} 必须为对象')
    if any(not isinstance(x, dict) for x in out['fx'].values()) or any(not isinstance(x, dict) for x in out['coverage'].values()):
        raise ValueError('汇率及费用完整性说明必须是对象')
    return out


def _issue(issues, code, path, message, owner=None, severity='error'):
    issues.append({'code': code, 'path': path, 'message': message,
                   'owner': owner, 'severity': severity})


def _date(value):
    return date.fromisoformat(value)


def _quantity(q, line=None):
    ids = line.get('vehicle_ids') if line else None
    return sum(decimal(v['quantity']) for v in q['vehicles'] if ids is None or v['id'] in ids)


def _check_evidence(item, path, q, issues):
    state = item.get('status')
    if state not in STATES:
        _issue(issues, 'evidence_status', path, '需明确 confirmed/estimated/pending/historical/expired/conflict')
    if not item.get('source'):
        _issue(issues, 'source_missing', path, '缺少可追溯来源', item.get('owner'))
    if state in ('pending', 'expired', 'conflict') or (state == 'historical' and q['mode'] != 'replay'):
        _issue(issues, 'unusable_evidence', path, '待确认、冲突或失效依据不能作为正式计算依据', item.get('owner'))
    if state == 'estimated':
        if not item.get('assumption'):
            _issue(issues, 'estimate_reason', path, '估值需要说明假设及依据', item.get('owner'))
        _issue(issues, 'estimated', path, '采用估值，只能用于条件测算', item.get('owner'), 'warning')
    try:
        when = _date(q['quote_date'])
        if item.get('valid_from') and _date(item['valid_from']) > when:
            _issue(issues, 'not_effective', path, '该依据在报价日期尚未生效')
        if item.get('valid_until'):
            if _date(item['valid_until']) < when:
                _issue(issues, 'expired', path, '该依据在报价日期已过期', item.get('owner'))
            elif q.get('valid_until') and _date(item['valid_until']) < _date(q['valid_until']):
                _issue(issues, 'validity_gap', path, '该依据早于对客报价有效期失效；需缩短报价有效期或更新依据',
                       item.get('owner'), 'warning')
        elif q['mode'] == 'live':
            _issue(issues, 'validity_missing', path, '缺少有效期，需确认', item.get('owner'), 'warning')
    except (ValueError, KeyError, TypeError):
        _issue(issues, 'invalid_date', path, '日期必须为 YYYY-MM-DD')
    applicability = item.get('applies_to', {})
    for key, allowed in applicability.items():
        actual = q.get(key)
        if key not in ('destination', 'trade_term', 'business_mode', 'payment_terms', 'supplier_id'):
            _issue(issues, 'unsupported_scope', path, f'尚未实现的适用维度 {key}，不能忽略')
        elif actual not in (allowed if isinstance(allowed, list) else [allowed]):
            _issue(issues, 'scope_mismatch', path, f'不符合适用条件 {key}')


def _apply_rules(q, rules):
    if not rules:
        return q
    q = deepcopy(q)
    by_id = {r['id']: r for r in rules.get('fee_rules', [])}
    for line in q['costs']:
        if 'rule_id' not in line:
            continue
        rule = by_id.get(line['rule_id'])
        if not rule:
            line['_rule_error'] = '找不到指定规则'
            continue
        if rule.get('status') != 'confirmed':
            line['_rule_error'] = '规则未经确认，不自动启用'
            continue
        values = rule.get('values', {})
        conflicts = [k for k, v in values.items() if k in line and line[k] != v]
        if conflicts:
            line['_rule_error'] = '规则参数冲突：' + ', '.join(conflicts)
        for key, value in values.items():
            line.setdefault(key, deepcopy(value))
        for key in ('source', 'valid_from', 'valid_until', 'applies_to', 'status'):
            if key in rule:
                line[key] = deepcopy(rule[key])
    matches = [r for r in rules.get('profit_targets', []) if r.get('status') == 'confirmed'
               and all(q.get(k) == v for k, v in r.get('match', {}).items())]
    if len(matches) > 1:
        q['_rule_error'] = '多个利润目标同时匹配，需要解决冲突'
    elif matches:
        target = matches[0]['target']
        if q.get('profit_target') and q['profit_target'] != target:
            if not q.get('profit_override_reason'):
                q['_rule_error'] = '覆盖团队利润目标需要填写原因'
        else:
            q['profit_target'] = deepcopy(target)
    return q


def validate_quote(request, rules=None):
    q = _apply_rules(normalize_request(request), rules)
    issues = []
    if q['schema_version'] != VERSION:
        _issue(issues, 'version', 'schema_version', '不支持的接口版本')
    if q['mode'] not in ('live', 'replay'):
        _issue(issues, 'mode', 'mode', 'mode 仅支持 live 或 replay')
    for key in ('quote_id', 'quote_date', 'currency', 'business_mode', 'trade_term', 'delivery_place',
                'destination', 'payment_terms', 'valid_until'):
        if not q.get(key):
            _issue(issues, 'required', key, f'缺少 {key}')
    if q.get('business_mode') not in ('standard', 'central_procurement'):
        _issue(issues, 'business_mode', 'business_mode', '请选择 standard 或 central_procurement')
    if q.get('trade_term') not in ('EXW', 'FCA', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP'):
        _issue(issues, 'trade_term', 'trade_term', '未支持或未记载的贸易术语', severity='warning' if q['mode'] == 'replay' else 'error')
    try:
        if _date(q['valid_until']) < _date(q['quote_date']):
            _issue(issues, 'quote_expired', 'valid_until', '报价有效期早于报价日')
    except (ValueError, KeyError, TypeError):
        _issue(issues, 'invalid_date', 'quote_date', '报价日和有效期需使用 YYYY-MM-DD')
    if q.get('_rule_error'):
        _issue(issues, 'rule_conflict', 'profit_target', q['_rule_error'])
    ids = []
    if not q['vehicles']:
        _issue(issues, 'vehicles_missing', 'vehicles', '缺少车型配置及数量')
    for i, vehicle in enumerate(q['vehicles']):
        path = f'vehicles.{i}'
        ids.append(vehicle.get('id'))
        if not vehicle.get('id') or not vehicle.get('model'):
            _issue(issues, 'vehicle_identity', path, '车型行需要唯一 id 和 model')
        try:
            qty = decimal(vehicle.get('quantity'))
            if qty <= 0 or qty != qty.to_integral_value():
                raise ValueError()
        except ValueError:
            _issue(issues, 'quantity', path, '车辆数量必须为正整数')
    if len(set(ids)) != len(ids):
        _issue(issues, 'duplicate', 'vehicles', '车型行 id 重复')
    if not q['costs']:
        _issue(issues, 'costs_missing', 'costs', '没有费用明细，不能以零成本报价')
    for v in q['vehicles']:
        if not any(c.get('category') == 'vehicle' and not c.get('included_in') and v.get('id') in c.get('vehicle_ids', ids) for c in q['costs']):
            _issue(issues, 'purchase_missing', 'costs', f"车型 {v.get('id')} 缺少车源费用")
    line_ids = [c.get('id') for c in q['costs']]
    if None in line_ids or '' in line_ids or len(set(line_ids)) != len(line_ids):
        _issue(issues, 'duplicate', 'costs', '费用 id 必须存在且唯一')
    for category in CATEGORIES:
        scope = q['coverage'].get(category, {})
        if scope.get('status') not in ('complete', 'not_applicable') or not scope.get('reason'):
            _issue(issues, 'coverage', f'coverage.{category}', '需要确认该类费用完整性或不适用原因')
        if scope.get('status') == 'complete' and not any(c.get('category') == category for c in q['costs']):
            _issue(issues, 'empty_category', f'coverage.{category}', '标记完整但没有该类费用')
        if scope.get('status') == 'not_applicable' and any(c.get('category') == category and not c.get('included_in') for c in q['costs']):
            _issue(issues, 'scope_conflict', f'coverage.{category}', '不适用类别仍有费用明细')
    for i, line in enumerate(q['costs']):
        path = f'costs.{i}'
        if line.get('_rule_error'):
            _issue(issues, 'rule_conflict', path, line['_rule_error'])
        if line.get('category') not in CATEGORIES:
            _issue(issues, 'category', path, '费用需归属 vehicle/transport/funding')
        if not line.get('name') or not line.get('component'):
            _issue(issues, 'cost_identity', path, '费用需要名称和业务 component')
        selected = line.get('vehicle_ids', ids)
        if not selected or len(set(selected)) != len(selected) or any(v not in ids for v in selected):
            _issue(issues, 'allocation_scope', path, '费用关联车型无效或重复')
        _check_evidence(line, path, q, issues)
        if line.get('included_in'):
            parent = next((x for x in q['costs'] if x.get('id') == line['included_in']), None)
            if not parent or parent is line or parent.get('included_in'):
                _issue(issues, 'included_parent', path, '已含费用必须关联一个有效的顶层打包费用')
            elif line.get('component') not in parent.get('includes', []):
                _issue(issues, 'inclusion_unproven', path, '打包费用未声明包含该项目')
            continue
        shares = line.get('bearers', {})
        try:
            if not shares or any(k not in PARTIES for k in shares) or any(decimal(v) < 0 for v in shares.values()) or sum(map(decimal, shares.values())) != 1:
                raise ValueError()
        except ValueError:
            _issue(issues, 'bearers', path, '费用承担比例必须明确且合计为 1')
        if line.get('allocation') not in ('quantity', 'weights'):
            _issue(issues, 'allocation', path, '明确按数量或指定权重分摊')
        elif line['allocation'] == 'weights':
            weights = line.get('weights', {})
            try:
                if set(weights) != set(selected) or any(decimal(x) < 0 for x in weights.values()) or sum(map(decimal, weights.values())) <= 0:
                    raise ValueError()
            except ValueError:
                _issue(issues, 'weights', path, '分摊权重应覆盖费用关联车型且合计大于零')
        try:
            _line_amount(line, q)
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            _issue(issues, 'calculation_input', path, str(exc) or '计费参数无效', line.get('owner'))
        if not line.get('tax_treatment'):
            _issue(issues, 'tax_basis', path, '缺少含税、未税或不适用的金额口径')
        if not isinstance(line.get('currency'), str) or len(line.get('currency', '')) != 3:
            _issue(issues, 'currency', path, '费用币种必须是三位代码')
        if line.get('effect', 'cost') not in ('cost', 'credit'):
            _issue(issues, 'effect', path, 'effect 必须为 cost 或 credit')
        if line.get('effect') == 'credit' and not line.get('credit_basis'):
            _issue(issues, 'credit_basis', path, '退税或返款抵减需要明确依据')
        currency = line.get('currency')
        if currency != q.get('currency'):
            rate = q['fx'].get(currency, {})
            try:
                if decimal(rate.get('rate')) <= 0:
                    raise ValueError()
            except ValueError:
                _issue(issues, 'fx_missing', path, f'缺少 {currency} 到报价币种的正数汇率')
            _check_evidence(rate, f'fx.{currency}', q, issues)
    # Overlap is evaluated per vehicle, so separate supplier/vehicle rows remain legal.
    occupied = {}
    for i, line in enumerate(q['costs']):
        if line.get('included_in') or line.get('effect') == 'credit':
            continue
        for component in [line.get('component')] + line.get('includes', []):
            for vid in line.get('vehicle_ids', ids):
                key = (vid, component)
                if key in occupied:
                    _issue(issues, 'duplicate_component', f'costs.{i}', f'{vid} 的 {component} 重复计费；分阶段费用需用独立 component')
                occupied[key] = True
    for required in (rules or {}).get('required_components', []):
        if required not in [c.get('component') for c in q['costs']] and required not in q['exclusions']:
            _issue(issues, 'missing_component', 'costs', f'规则要求确认 {required}')
    target = q.get('profit_target')
    if q.get('sale_price'):
        _check_evidence(q['sale_price'], 'sale_price', q, issues)
        try:
            if q['sale_price'].get('currency', q.get('currency')) != q.get('currency'):
                raise ValueError()
            if decimal(q['sale_price'].get('amount')) < 0:
                raise ValueError()
        except ValueError:
            _issue(issues, 'sale_price', 'sale_price', '指定总售价必须为报价币种的非负十进制数')
    if not target and not q.get('sale_price'):
        _issue(issues, 'profit_missing', 'profit_target', '缺少利润目标，不能生成建议售价')
    elif target:
        try:
            value = decimal(target['value'])
            if target['kind'] not in ('per_vehicle', 'total', 'margin') or value < 0 or (target['kind'] == 'margin' and value >= 1):
                raise ValueError()
        except (KeyError, ValueError):
            _issue(issues, 'profit_target', 'profit_target', '利润目标无效；毛利率应在 [0,1) 内')
    if q.get('business_mode') == 'central_procurement':
        try:
            share = q['profit_shares']
            if set(share) != {'ours', 'upstream'} or sum(map(decimal, share.values())) != 1 or any(decimal(v) < 0 for v in share.values()):
                raise ValueError()
        except (ValueError, KeyError):
            _issue(issues, 'profit_shares', 'profit_shares', '集采需明确上游／我方利润比例，合计为 1')
        if q.get('contract_rounding') not in ('cent_half_up', 'unit_ceiling', 'none'):
            _issue(issues, 'rounding', 'contract_rounding', '需明确合同价取整规则')
    for assumption in q['assumptions']:
        _issue(issues, 'assumption', 'assumptions', str(assumption), severity='warning')
    if q['mode'] == 'replay':
        _issue(issues, 'replay_only', 'mode', '历史回放不可作为当前对外报价', severity='warning')
    return {'valid': not any(x['severity'] == 'error' for x in issues),
            'status': 'blocked' if any(x['severity'] == 'error' for x in issues) else ('conditional' if issues else 'ready'),
            'issues': issues, 'normalized': q}


def _line_amount(line, q):
    unit = line.get('unit')
    amount = decimal(line.get('amount'))
    if amount < 0:
        raise ValueError('费用金额不得为负数；抵减使用 effect=credit')
    factor = Decimal(1)
    formula = str(amount)
    if unit == 'per_vehicle':
        factor = _quantity(q, line)
        formula += f' × {factor} 辆'
    elif unit == 'per_batch':
        pass
    elif unit in ('per_container', 'per_day'):
        factor = decimal(line.get('units'))
        if factor < 0 or factor != factor.to_integral_value():
            raise ValueError('柜数／计费天数必须为非负整数')
        formula += f' × {factor} {unit}'
    elif unit == 'percent':
        factor = decimal(line.get('basis'))
        if factor < 0:
            raise ValueError('比例计费基数不得为负')
        if not line.get('basis_description'):
            raise ValueError('必须说明比例计费基数口径；基数币种与费用一致')
        formula = f'{factor} × {amount}'
    elif unit == 'annual_interest':
        principal = decimal(line.get('basis'))
        if principal < 0 or not line.get('basis_description'):
            raise ValueError('资金本金必须非负且说明资金占用口径')
        days = decimal(line.get('days'))
        denominator = decimal(line.get('day_basis'))
        if days < 0 or days != days.to_integral_value() or denominator not in (360, 365, 366):
            raise ValueError('计息天数必须非负整数，年基准为 360/365/366')
        if line.get('start_date') or line.get('end_date'):
            span = (_date(line['end_date']) - _date(line['start_date'])).days
            if span < 0 or line.get('day_count') not in ('exclusive_end', 'inclusive'):
                raise ValueError('计息节点顺序或首尾日口径无效')
            expected = span + (1 if line['day_count'] == 'inclusive' else 0)
            if days != expected:
                raise ValueError('计息天数与付款／回款节点不一致')
        factor = principal * days / denominator
        formula = f'{principal} × {amount} × {days} / {denominator}'
    else:
        raise ValueError('未支持的计费单位')
    return amount * factor, formula


def _round(value, mode='cent_half_up'):
    if mode == 'none':
        return value
    return value.quantize(Decimal('1') if mode == 'unit_ceiling' else Decimal('.01'),
                          rounding=ROUND_CEILING if mode == 'unit_ceiling' else ROUND_HALF_UP)


def calculate_quote(request, rules=None):
    with localcontext() as ctx:
        ctx.prec = 40
        return _calculate(request, rules)


def _calculate(request, rules):
    validation = validate_quote(request, rules)
    q = validation.pop('normalized')
    lines = []
    categories = {k: Decimal(0) for k in CATEGORIES}
    bearers = {k: Decimal(0) for k in PARTIES}
    vehicle_costs = {v.get('id'): Decimal(0) for v in q['vehicles']}
    errors = [x for x in validation['issues'] if x['severity'] == 'error']
    for i, line in enumerate(q['costs']):
        item = deepcopy(line)
        if line.get('included_in'):
            item.update({'calculated': False, 'reason': '已包含在 ' + line['included_in']})
            lines.append(item)
            continue
        if any(e['path'] in (f'costs.{i}', f"fx.{line.get('currency')}") or e['path'].startswith('vehicles') for e in errors):
            item.update({'calculated': False, 'total': None, 'reason': '参数或证据待补齐'})
            lines.append(item)
            continue
        try:
            original, formula = _line_amount(line, q)
            rate = Decimal(1) if line['currency'] == q['currency'] else decimal(q['fx'][line['currency']]['rate'])
            amount = original * rate * (-1 if line.get('effect') == 'credit' else 1)
            allocations = {}
            selected = [v for v in q['vehicles'] if v['id'] in line.get('vehicle_ids', vehicle_costs)]
            weights = {v['id']: decimal(line['weights'][v['id']]) if line['allocation'] == 'weights' else decimal(v['quantity']) for v in selected}
            total_weight = sum(weights.values())
            if total_weight <= 0:
                raise ValueError('分摊基数为零')
            for idx, v in enumerate(selected):
                allocations[v['id']] = amount - sum(allocations.values()) if idx == len(selected) - 1 else amount * weights[v['id']] / total_weight
            for party, share in line['bearers'].items():
                bearers[party] += amount * decimal(share)
            customer_share = decimal(line['bearers'].get('customer', '0'))
            internal = amount * (1 - customer_share)
            categories[line['category']] += internal
            for vid, value in allocations.items():
                vehicle_costs[vid] += value * (1 - customer_share)
            item.update({'calculated': True, 'original_total': number(original), 'fx_rate': number(rate),
                         'formula': formula, 'total': number(amount), 'included_cost': number(internal),
                         'vehicle_allocations': {k: number(v) for k, v in allocations.items()}})
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            item.update({'calculated': False, 'total': None, 'reason': '关联参数无效'})
        lines.append(item)
    subtotal = sum(categories.values())
    totals = {'known_cost': number(subtotal), 'complete_cost': None, 'suggested_price': None,
              'profit': None, 'currency': q.get('currency'),
              'by_category': {k: number(v) for k, v in categories.items()},
              'by_bearer': {k: number(v) for k, v in bearers.items()},
              'vehicle_costs': {k: number(v) for k, v in vehicle_costs.items()}}
    # Only missing profit/contract split permits a complete cost subtotal.
    cost_errors = [e for e in errors if e['path'] not in ('profit_target', 'profit_shares', 'contract_rounding', 'sale_price')]
    if not cost_errors and all(x.get('calculated') or x.get('included_in') for x in lines):
        totals['complete_cost'] = number(subtotal)
        if not any(e['path'] in ('profit_target', 'sale_price') for e in errors):
            if q.get('sale_price'):
                price = decimal(q['sale_price']['amount'])
            else:
                target = q['profit_target']
                value = decimal(target['value'])
                price = subtotal / (1 - value) if target['kind'] == 'margin' else subtotal + value * (_quantity(q) if target['kind'] == 'per_vehicle' else 1)
            price = _round(price)
            profit = price - subtotal
            totals.update({'suggested_price': number(price), 'profit': number(profit),
                           'average_price_per_vehicle': number(price / _quantity(q))})
            if q['business_mode'] == 'central_procurement' and not any(e['path'] in ('profit_shares', 'contract_rounding') for e in errors):
                upstream_profit = profit * decimal(q['profit_shares']['upstream'])
                raw_contract = bearers['upstream'] + upstream_profit
                contract = _round(raw_contract, q['contract_rounding'])
                totals.update({'upstream_profit': number(upstream_profit),
                               'our_profit': number(profit - upstream_profit),
                               'upstream_contract_raw': number(raw_contract),
                               'upstream_contract': number(contract),
                               'contract_rounding_adjustment': number(contract - raw_contract)})
    result = {'schema_version': VERSION, 'engine_version': '0.1.0', 'quote_id': q.get('quote_id'),
              'status': validation['status'], 'issues': validation['issues'], 'totals': totals,
              'lines': lines, 'input_snapshot': q, 'rules_snapshot': deepcopy(rules or {}),
              'rules_version': (rules or {}).get('version', 'explicit-input'), 'input_hash': digest(q),
              'rules_hash': digest(rules or {}), 'mode': q['mode'], 'approved': False}
    result['result_hash'] = digest(result)
    return result


def compare_quotes(requests, rules=None):
    """Only compare identical commercial scope; unknown metrics never win."""
    results = [calculate_quote(q, rules) for q in requests]
    if not results:
        return {'quotes': [], 'recommendations': {}, 'issues': ['没有方案']}
    def scope(result):
        q = result['input_snapshot']
        return {k: q.get(k) for k in ('vehicles', 'currency', 'trade_term', 'delivery_place', 'destination', 'payment_terms', 'exclusions')}
    comparable = all(scope(r) == scope(results[0]) for r in results)
    recommendations, issues = {}, []
    if not comparable:
        issues.append('车型数量、币种、交付或付款边界不同；仅展示，不跨口径排名')
    else:
        ready = [r for r in results if r['status'] == 'ready' and r['mode'] == 'live']
        metrics = {'lowest_cost': lambda r: r['totals']['complete_cost'],
                   'fastest_delivery': lambda r: r['input_snapshot'].get('delivery_days'),
                   'least_advance': lambda r: r['input_snapshot'].get('own_advance')}
        for label, getter in metrics.items():
            if not ready or any(getter(r) is None for r in ready):
                issues.append(f'{label}：可行方案或可比指标不足')
                continue
            try:
                values = [(decimal(getter(r)), r['quote_id']) for r in ready]
                if any(v < 0 for v, _ in values):
                    raise ValueError()
                best = min(v for v, _ in values)
                recommendations[label] = [qid for v, qid in values if v == best]
            except ValueError:
                issues.append(f'{label}：指标无效')
    return {'quotes': results, 'recommendations': recommendations, 'issues': issues}


def build_scenarios(base, options):
    """Combine explicit compatible supplier/transport/funding options, capped at 100."""
    groups = [options.get(k, []) for k in CATEGORIES]
    if any(not group for group in groups):
        raise ValueError('三类方案均需提供；不适用项用无费用的显式选项')
    if len(groups[0]) * len(groups[1]) * len(groups[2]) > 100:
        raise ValueError('组合超过 100；请先筛选候选项')
    scenarios = []
    for combination in itertools.product(*groups):
        chosen = {c['id'] for c in combination}
        if any(not set(c.get('requires', [])).issubset(chosen) or set(c.get('excludes', [])) & chosen for c in combination):
            continue
        q = deepcopy(base)
        q['quote_id'] = base['quote_id'] + ':' + ':'.join(c['id'] for c in combination)
        q['costs'] = deepcopy(base.get('costs', [])) + [deepcopy(line) for c in combination for line in c.get('costs', [])]
        # End-to-end metrics must come from a verified joint scenario; do not add overlapping periods.
        q.pop('delivery_days', None)
        q.pop('own_advance', None)
        scenarios.append(q)
    return scenarios
