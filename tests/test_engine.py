from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from export_quote.engine import calculate_quote, validate_quote, compare_quotes, normalize_request, digest, build_scenarios, screen_funders
from export_quote.outputs import customer_quote, export_moss
from export_quote.storage import save_snapshot, read_json, approve_rules, load_rules

ROOT = Path(__file__).resolve().parents[1]


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.q = json.loads((ROOT / 'examples/standard.json').read_text())

    def result(self):
        return calculate_quote(self.q)

    def blocked(self, code):
        result = self.result()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn(code, [x['code'] for x in result['issues']])
        return result

    def test_standard_mixed_fx_and_interest(self):
        r = self.result()
        expected = Decimal(32000 + 150 + 300 + 1800) + Decimal('35.2') + Decimal('25600') * Decimal('.08') * 30 / 365
        self.assertEqual(r['status'], 'ready')
        self.assertLess(abs(Decimal(r['totals']['complete_cost']) - expected), Decimal('0.000000001'))
        self.assertEqual(r['totals']['suggested_price'], '35353.53')

    def test_no_mutation(self):
        old = deepcopy(self.q)
        self.result()
        self.assertEqual(old, self.q)

    def test_decimal_float_rejected(self):
        self.q['costs'][0]['amount'] = 10000.1
        self.blocked('calculation_input')

    def test_missing_amount_is_not_zero(self):
        self.q['costs'][4]['amount'] = None
        r = self.blocked('calculation_input')
        self.assertIsNone(r['totals']['complete_cost'])
        self.assertIsNone(r['totals']['suggested_price'])

    def test_explicit_zero_is_valid(self):
        self.q['costs'][4]['amount'] = '0'
        self.assertEqual(self.result()['status'], 'ready')

    def test_missing_freight_coverage(self):
        self.q['coverage']['transport']['status'] = 'pending'
        self.blocked('coverage')

    def test_missing_profit_has_cost_but_no_price(self):
        del self.q['profit_target']
        r = self.blocked('profit_missing')
        self.assertIsNotNone(r['totals']['complete_cost'])
        self.assertIsNone(r['totals']['suggested_price'])

    def test_estimate_is_conditional(self):
        self.q['costs'][4].update(status='estimated', assumption='近期同路线，待本单确认')
        r = self.result()
        self.assertEqual(r['status'], 'conditional')
        self.assertIsNotNone(r['totals']['suggested_price'])

    def test_estimate_without_basis_blocked(self):
        self.q['costs'][4]['status'] = 'estimated'
        self.blocked('estimate_reason')

    def test_expired_and_future(self):
        self.q['costs'][0]['valid_until'] = '2026-09-17'
        self.blocked('expired')
        self.q['costs'][0]['valid_until'] = '2099-12-31'
        self.q['costs'][0]['valid_from'] = '2026-09-19'
        self.blocked('not_effective')

    def test_source_validity_must_cover_customer_quote(self):
        self.q['costs'][0]['valid_until'] = '2026-09-20'
        self.q['valid_until'] = '2026-09-30'
        r = self.result()
        self.assertEqual(r['status'], 'conditional')
        self.assertIn('validity_gap', [i['code'] for i in r['issues']])

    def test_fixed_sale_price_currency(self):
        self.q.pop('profit_target')
        self.q['sale_price'] = {'amount': '12000', 'currency': 'CNY', 'status': 'confirmed',
                                'source': 'signed quote', 'valid_until': '2099-12-31'}
        self.blocked('sale_price')

    def test_nan_rejected(self):
        self.q['costs'][0]['amount'] = 'NaN'
        self.blocked('calculation_input')

    def test_invalid_quantity(self):
        self.q['vehicles'][0]['quantity'] = 0
        self.blocked('quantity')

    def test_no_vehicles_does_not_crash(self):
        self.q['vehicles'] = []
        self.blocked('vehicles_missing')

    def test_structural_input(self):
        for key, value in [('costs', None), ('vehicles', ['x']), ('fx', [])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                normalize_request({key: value})

    def test_duplicate_component(self):
        extra = deepcopy(self.q['costs'][0]); extra['id'] = 'another'
        self.q['costs'].append(extra)
        self.blocked('duplicate_component')

    def test_packaged_cost_not_counted_twice(self):
        before = self.result()['totals']['complete_cost']
        self.q['costs'][0]['includes'] = ['loading']
        child = deepcopy(self.q['costs'][0])
        child.update(id='included', name='装箱已包含', component='loading', included_in='purchase-a', includes=[])
        self.q['costs'].append(child)
        self.assertEqual(before, self.result()['totals']['complete_cost'])
        child.pop('included_in')
        self.blocked('duplicate_component')

    def test_bad_bearer_shares(self):
        self.q['costs'][0]['bearers'] = {'ours': '.7', 'upstream': '.7'}
        self.blocked('bearers')

    def test_customer_borne_cost_not_in_price(self):
        before = Decimal(self.result()['totals']['complete_cost'])
        self.q['costs'][4]['bearers'] = {'customer': '1'}
        r = self.result()
        self.assertEqual(before - Decimal(r['totals']['complete_cost']), 1800)
        self.assertEqual(Decimal(r['totals']['by_bearer']['customer']), 1800)

    def test_shared_cost_allocation(self):
        self.q['costs'][4]['bearers'] = {'ours': '.25', 'upstream': '.75'}
        r = self.result()
        self.assertEqual(Decimal(r['totals']['by_bearer']['upstream']), 1350)
        row = r['lines'][4]
        self.assertEqual(Decimal(row['vehicle_allocations']['A']), 1200)
        self.assertEqual(Decimal(row['vehicle_allocations']['B']), 600)

    def test_explicit_weights(self):
        self.q['costs'][4].update(allocation='weights', weights={'A': '1', 'B': '1'})
        row = self.result()['lines'][4]
        self.assertEqual(Decimal(row['vehicle_allocations']['A']), 900)

    def test_funding_day_count(self):
        self.q['costs'][-1]['days'] = 31
        self.blocked('calculation_input')
        self.q['costs'][-1]['day_count'] = 'inclusive'
        self.assertEqual(self.result()['status'], 'ready')

    def test_funding_scope(self):
        self.q['costs'][-1]['applies_to'] = {'destination': ['other market']}
        self.blocked('scope_mismatch')

    def test_tax_refund_explicit_credit(self):
        before = Decimal(self.result()['totals']['complete_cost'])
        c = deepcopy(self.q['costs'][0]); c.update(id='refund',component='tax_refund',unit='per_batch',amount='100',effect='credit',credit_basis='合成案例中明确可抵减')
        self.q['costs'].append(c)
        self.assertEqual(before - Decimal(self.result()['totals']['complete_cost']), 100)

    def test_central_4060_and_contract_not_double_counted(self):
        self.q = json.loads((ROOT / 'examples/central.json').read_text())
        r = self.result(); t = r['totals']
        self.assertEqual(r['status'], 'ready')
        self.assertAlmostEqual(Decimal(t['profit']), Decimal(t['suggested_price']) - Decimal(t['complete_cost']))
        self.assertAlmostEqual(Decimal(t['upstream_profit']), Decimal(t['profit']) * Decimal('.4'))
        self.assertAlmostEqual(Decimal(t['upstream_contract_raw']), Decimal(t['by_bearer']['upstream']) + Decimal(t['upstream_profit']))

    def test_margin_not_markup(self):
        self.q['profit_target'] = {'kind': 'margin', 'value': '.2'}
        t = self.result()['totals']
        self.assertLess(abs(Decimal(t['suggested_price']) * Decimal('.8') - Decimal(t['complete_cost'])), Decimal('.01'))

    def test_customer_does_not_leak(self):
        self.q['costs'][0]['source'] = 'private://secret-supplier'
        c = customer_quote(self.result(), as_of='2026-09-18')
        text = json.dumps(c)
        for forbidden in ('secret-supplier', 'profit', 'bearers', 'costs', 'input_snapshot'):
            self.assertNotIn(forbidden, text)
        self.assertIsNotNone(c['total_price'])

    def test_customer_expired_and_replay(self):
        self.q['valid_until'] = '2026-09-18'
        self.assertIsNone(customer_quote(self.result(), as_of='2026-09-19')['total_price'])
        self.q['mode'] = 'replay'
        self.assertIsNone(customer_quote(self.result(), as_of='2026-09-18')['total_price'])

    def test_moss_unknown_fields_not_dumped(self):
        p = export_moss(self.result())
        self.assertEqual(p['fields'], [])
        self.assertTrue(p['unmapped'])
        self.assertFalse(p['submit_automatically'])

    def test_snapshot_tamper(self):
        r = self.result();r['totals']['suggested_price'] = '1'
        with self.assertRaises(ValueError):
            customer_quote(r)

    def test_snapshots_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            r = self.result();p = save_snapshot(r, folder)
            self.q['costs'][0]['amount'] = '999'
            self.result()
            self.assertEqual(read_json(p)['result'], r)
            self.assertEqual(save_snapshot(r, folder), p)

    def test_comparison_unknown_metrics_not_ranked(self):
        alt = deepcopy(self.q);alt['quote_id']='alt';alt.pop('delivery_days')
        r = compare_quotes([self.q, alt])
        self.assertNotIn('fastest_delivery', r['recommendations'])

    def test_comparison_different_scopes(self):
        alt = deepcopy(self.q);alt['payment_terms']='全款'
        self.assertEqual(compare_quotes([self.q,alt])['recommendations'], {})

    def test_rule_profit_override(self):
        rules = {'profit_targets':[{'id':'x','status':'confirmed','match':{'business_mode':'standard'},'target':{'kind':'total','value':'500'}}]}
        self.assertEqual(calculate_quote(self.q,rules)['status'],'blocked')
        self.q['profit_override_reason']='本次特别报价'
        self.assertEqual(calculate_quote(self.q,rules)['status'],'ready')

    def test_rule_pending_never_silently_applied(self):
        self.q['costs'][0]['rule_id']='x'
        rules={'fee_rules':[{'id':'x','status':'pending','values':{'amount':'1'}}]}
        self.assertEqual(calculate_quote(self.q,rules)['status'],'blocked')

    def test_rule_approval_hash_and_no_overwrite(self):
        p={'schema_version':'1.0','version':'test','status':'pending','fee_rules':[]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'pack.json'
            with self.assertRaises(ValueError):approve_rules(p,'reviewer','wrong',path)
            approve_rules(p,'reviewer',digest(p),path)
            self.assertEqual(load_rules(path)['status'],'confirmed')
            with self.assertRaises(FileExistsError):approve_rules(p,'reviewer',digest(p),path)

    def test_scenario_compatibility(self):
        options={'vehicle':[{'id':'v1'},{'id':'v2'}], 'transport':[{'id':'t'}], 'funding':[{'id':'f','requires':['v1']}]}
        self.assertEqual(len(build_scenarios(self.q, options)),1)

    def test_funder_screening_uses_trade_and_payment_terms(self):
        self.q['customer_payment'] = {'deposit_rate':'0.2','balance_trigger':'before_arrival','credit_days':'30','method':'TT'}
        rules = {'funding_options':[
            {'id':'fit','name':'匹配资金方','status':'confirmed','match':{'trade_terms':['CIF'],'balance_triggers':['before_arrival'],'min_deposit_rate':'0.1','max_credit_days':'45'}},
            {'id':'wrong','name':'不匹配资金方','status':'confirmed','match':{'trade_terms':['EXW']}},
            {'id':'pending','name':'待确认资金方','status':'pending','match':{}}
        ]}
        result = screen_funders(self.q, rules)
        self.assertEqual([x['id'] for x in result['eligible']], ['fit'])
        self.assertEqual({x['id'] for x in result['rejected']}, {'wrong','pending'})
        self.assertEqual(validate_quote(self.q, rules)['status'], 'blocked')
        self.q['selected_funder_id'] = 'fit'
        self.q['costs'][-1]['funder_id'] = 'fit'
        self.assertEqual(validate_quote(self.q, rules)['status'], 'ready')

    def test_supplier_quote_requires_traceable_wechat_evidence(self):
        line = self.q['costs'][0]
        line['source_type'] = 'supplier_quote'
        self.assertIn('supplier_evidence', [x['code'] for x in validate_quote(self.q)['issues']])
        line.update(supplier_id='dealer-a', supplier_name='示例车源商', quoted_at='2026-09-18T10:00:00+08:00',
                    quote_channel='WeChat', quote_ref='private://wechat/quote-a.png', owner='采购甲')
        self.assertNotIn('supplier_evidence', [x['code'] for x in validate_quote(self.q)['issues']])


if __name__ == '__main__':unittest.main()
