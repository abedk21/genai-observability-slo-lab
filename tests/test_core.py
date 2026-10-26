import copy
from pathlib import Path
import unittest
from genai_observability.core import (InvalidTrace, Span, burn_rates, load_traces,
    merged_duration, percentile_nearest_rank, safe_attrs, self_times, summarize, trace_cost_usd)
from genai_observability.fixtures import ANCHOR_MS, generate, load_fixture
from genai_observability.report import render_html


class TestTraceObservability(unittest.TestCase):
    def setUp(self):
        self.rows = load_fixture()
        self.groups = load_traces(self.rows)
        self.summary = summarize(self.groups)

    def test_fixture_matches_generator(self):
        self.assertEqual(self.rows, generate())

    def test_forty_traces_four_spans_each(self):
        self.assertEqual(len(self.groups), 40)
        self.assertEqual(sum(map(len, self.groups.values())), 160)

    def test_root_sli_values(self):
        self.assertEqual(self.summary['requests'], 40)
        self.assertAlmostEqual(self.summary['availability'], 0.9)
        self.assertEqual(self.summary['latency_success_fraction'], 0.8)

    def test_p95_nearest_rank(self):
        self.assertEqual(percentile_nearest_rank([3, 1, 2, 4], 0.50), 2)
        self.assertEqual(percentile_nearest_rank([3, 1, 2, 4], 0.95), 4)
        self.assertIsNone(percentile_nearest_rank([], 0.95))
        with self.assertRaises(ValueError):
            percentile_nearest_rank([1], 0)

    def test_overlap_union(self):
        self.assertEqual(merged_duration([(1, 10), (3, 8), (8, 20), (22, 25)]), 22)
        self.assertEqual(merged_duration([]), 0)

    def test_parallel_spans_do_not_double_count(self):
        one = next(iter(self.groups.values()))
        own = self_times(one)
        self.assertTrue(all(value >= 0 for value in own.values()))
        root = next(s for s in one if s.parent_id is None)
        self.assertLessEqual(own[root.span_id], root.duration_ms)

    def test_empty_traces_are_valid_with_null_slis(self):
        summary = summarize(load_traces([]))
        self.assertEqual(summary['requests'], 0)
        self.assertIsNone(summary['availability'])

    def test_duplicate_id_rejected(self):
        with self.assertRaisesRegex(InvalidTrace, 'duplicate'):
            load_traces(self.rows + [self.rows[0]])

    def test_missing_parent_rejected(self):
        corrupted = copy.deepcopy(self.rows[:4])
        corrupted[1]['parent_id'] = 'missing'
        with self.assertRaisesRegex(InvalidTrace, 'parent'):
            load_traces(corrupted)

    def test_child_outside_parent_rejected(self):
        corrupted = copy.deepcopy(self.rows[:4])
        corrupted[1]['end_ms'] = corrupted[0]['end_ms'] + 1
        with self.assertRaisesRegex(InvalidTrace, 'parent timeframe'):
            load_traces(corrupted)

    def test_multiple_roots_rejected(self):
        corrupted = copy.deepcopy(self.rows[:4])
        corrupted[1]['parent_id'] = None
        with self.assertRaisesRegex(InvalidTrace, 'one request root'):
            load_traces(corrupted)

    def test_negative_and_zero_duration_rejected(self):
        corrupted = copy.deepcopy(self.rows[:4])
        corrupted[2]['end_ms'] = corrupted[2]['start_ms']
        with self.assertRaisesRegex(InvalidTrace, 'timestamps'):
            load_traces(corrupted)

    def test_hidden_prompt_excluded(self):
        attrs = safe_attrs({'model':'mock-small','prompt':'PRIVATE DATA','output':'SECRET','authorization':'TOKEN'})
        self.assertEqual(attrs, {'model':'mock-small'})

    def test_bad_token_count_rejected(self):
        for value in [-1, '123', True, 10_000_001]:
            with self.assertRaises(InvalidTrace):
                safe_attrs({'input_tokens':value})

    def test_known_cost_nonzero(self):
        one = next(iter(self.groups.values()))
        self.assertGreater(trace_cost_usd(one), 0)
        self.assertGreater(self.summary['estimated_cost_usd'], 0)

    def test_unknown_model_rejected(self):
        rows = copy.deepcopy(self.rows[:4])
        rows[2]['attributes']['model'] = 'unknown-model'
        one = next(iter(load_traces(rows).values()))
        with self.assertRaisesRegex(InvalidTrace, 'unknown'):
            trace_cost_usd(one)

    def test_multiwindow_burn_alert(self):
        alert = burn_rates(self.summary, ANCHOR_MS)
        self.assertTrue(alert['alert'])
        self.assertEqual(alert['short_window']['violations'], 2)  # final two failures inside five-minute window
        self.assertEqual(alert['long_window']['violations'], 4)

    def test_empty_windows_do_not_alert(self):
        alert = burn_rates(self.summary, ANCHOR_MS + 100_000_000)
        self.assertFalse(alert['alert'])
        self.assertIsNone(alert['short_window']['burn_rate'])

    def test_healthy_traffic_does_not_alert(self):
        rows = copy.deepcopy(self.rows)
        for x in rows:
            x['status'] = 'ok'
        healthy = summarize(load_traces(rows))
        self.assertFalse(burn_rates(healthy, ANCHOR_MS)['alert'])

    def test_invalid_alert_parameters(self):
        with self.assertRaises(ValueError):
            burn_rates(self.summary, ANCHOR_MS, objective=1)
        with self.assertRaises(ValueError):
            summarize(self.groups, latency_target_ms=0)

    def test_html_static_and_escaped(self):
        html = render_html(self.groups)
        self.assertIn('<table>', html)
        self.assertNotIn('<script', html)
        self.assertIn('Synthetic GenAI tracing', html)

    def test_html_escapes_trace_identifiers(self):
        malicious = copy.deepcopy(self.rows[:4])
        for row in malicious:
            row['trace_id'] = '<unsafe>'
        html = render_html(load_traces(malicious))
        self.assertNotIn('<unsafe>', html)
        self.assertIn('&lt;unsafe&gt;', html)


if __name__ == '__main__':
    unittest.main()
