"""Site-independent limits and run-loop regressions with a fictional adapter."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from jobsearch_cn import collect
from tests.fixtures.collect_personal import example
from tests.test_cn_collect_boundaries import FakeTab, listing, DETAIL, NOW


def rules(**changes):
    values = {name: getattr(example, name) for name in dir(example) if not name.startswith('_')}
    return SimpleNamespace(**{**values, **changes})


class RunLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.delays = []

    def run_batch(self, tab, site=example, **kwargs):
        options = collect.make_options('Java', city='广州', site=site, **kwargs)
        return collect.run(tab, options, self.root, sleep=self.delays.append,
                           uniform=random.Random(7).uniform, clock=lambda: NOW)

    def test_slow_read_only_and_limits(self):
        tab = FakeTab()
        result = self.run_batch(tab, max_jobs=2)
        self.assertEqual((result['saved'], result['finished']), (2, 'max_jobs'))
        self.assertEqual(len(self.delays), len(tab.calls) - 1)
        self.assertTrue(all(4 <= value <= 9 for value in self.delays))
        self.assertGreater(len(set(self.delays)), 1)

    def test_invalid_limits_and_unconfigured_site_fail_before_run(self):
        with self.assertRaises(collect.CollectError):
            collect.make_options('Java', city='广州')
        for override in ({'query': ''}, {'query': 'x' * 51}, {'city': '火星'}, {'max_jobs': 0},
                         {'max_jobs': 51}, {'max_pages': 0}, {'max_pages': 11}, {'batch': '../bad'}):
            with self.subTest(override=override), self.assertRaises(collect.CollectError):
                collect.make_options(**{'query': 'Java', 'city': '广州', 'site': example, **override})

    def test_city_name_rule_and_page_cap(self):
        named = rules(CITY_CODES=None)
        self.assertEqual(collect.make_options('Java', city='佛山', site=named).city_code, '佛山')
        with self.assertRaises(collect.CollectError):
            collect.make_options('Java', city='佛山', city_code='x', site=named)
        result = self.run_batch(FakeTab(), max_jobs=3, max_pages=1)
        self.assertEqual((result['saved'], result['list_loads'], result['finished']), (2, 1, 'max_pages'))

    def test_scroll_403_and_blank_later_list_stop_before_details(self):
        class ScrollTab(FakeTab):
            def load_more(self, selectors, ready):
                self.calls.append('scroll')
                return self.next_page
        scroll = rules(PAGINATION='scroll')
        for status, html, expected in ((403, listing(), 3), (429, listing(), 3), (200, '', 4)):
            with self.subTest(status=status, html=html):
                tab = ScrollTab()
                tab.next_page = collect.Snapshot(example.search_url('Java', 'CITY_45'), '', html, status)
                result = self.run_batch(tab, site=scroll, max_jobs=3)
                self.assertEqual((collect.exit_code(result), result['saved'], len(tab.calls)), (expected, 0, 2))

    def test_unknown_detail_preserves_first_record(self):
        for second, expected in (('', 4), (collect.Snapshot(example.canonical_url('900003'), '', DETAIL), 4)):
            with tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                result = self.run_batch(FakeTab(details={'900002': second}), max_jobs=2)
                self.assertEqual((collect.exit_code(result), result['saved']), (expected, 1))

    def test_framework_rejects_placeholder_even_if_adapter_does_not(self):
        permissive = rules(parse_detail=lambda root: {'title': '示例后端实习生', 'description': 'Ｌｏａｄｉｎｇ...'},
                           detail_text=lambda fields: fields['description'])
        result = self.run_batch(FakeTab(), site=permissive, max_jobs=1)
        self.assertEqual((result['saved'], collect.exit_code(result)), (0, 4))
