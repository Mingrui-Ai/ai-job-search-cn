"""Fictional jobsTable empty-state layouts; no real tenant or network."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jobsearch_cn import beisen, collect, htmltext
from tests.test_cn_beisen import TENANTS, legacy_list

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
HEADER = '<tr class="title bgGray"><td>职位名称</td><td>职位类型</td><td>工作地点</td><td>发布时间</td></tr>'
EMPTY = '<tr><td colspan="10" class="tcenter"><p><span class="noResult"></span>没有搜索到相应职位</p></td></tr>'
SIDEBAR = '<aside><a href="/zpdetail/123456">示例侧栏职位</a></aside>'


def main_table(rows=EMPTY, *, header=HEADER, attrs="", module_attrs="", after=""):
    return (f'<div class="positionlist-smallblue" {module_attrs}><div class="joblist">'
            f'<table class="jobsTable" {attrs}><tbody>{header}{rows}</tbody></table></div>'
            f'{after}<div class="pager"></div></div>')


class Tab:
    headless = True

    def __init__(self, html, *, status=200, title="示例搜索"):
        self.html, self.status, self.title = html, status, title
        self.calls = []

    def open(self, url, ready):
        self.calls.append((url, ready))
        if len(self.calls) > 1:
            raise AssertionError("empty/unknown page must not open another page or a sidebar job")
        return collect.Snapshot(url, self.title, self.html, self.status)

    def load_more(self, *args):
        raise AssertionError("empty/unknown page must not scroll")


class LegacyEmpty(unittest.TestCase):
    def setUp(self):
        self.rules = beisen.tenant_rules(TENANTS["example-legacy"], "campus")

    def run_page(self, html, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tab = Tab(html, **kwargs)
            options = collect.make_search_options(beisen.searches(TENANTS["example-legacy"], []),
                                                  max_pages=1, max_jobs=1)
            result = collect.run(tab, options, root, sleep=lambda _: None, clock=lambda: NOW)
            self.assertEqual(len(tab.calls), 1)
            self.assertEqual(result["saved"], 0)
            self.assertIsNone(result["batch_dir"])
            self.assertFalse((root / "inbox").exists())
            return result, tab

    def assert_changed(self, html):
        self.assertFalse(self.rules.list_is_empty(htmltext.parse(html)))
        result, _ = self.run_page(html)
        self.assertEqual((result["status"], collect.exit_code(result)), ("page_changed", 4))

    def test_explicit_main_empty_ends_without_visiting_sidebar(self):
        markup = main_table() + SIDEBAR
        root = htmltext.parse(markup)
        self.assertTrue(self.rules.list_is_empty(root))
        self.assertEqual(self.rules.parse_cards(root, self.rules.search_url("", "4401")), ([], 0))
        result, _ = self.run_page(markup)
        self.assertEqual((result["status"], result["finished"], collect.exit_code(result)), ("done", "no_results", 0))

    def test_ready_selector_is_scoped_to_main_table(self):
        selector = ".positionlist-smallblue .joblist > table.jobsTable"
        self.assertIn(selector, self.rules.LIST_READY)
        self.assertTrue(htmltext.select(htmltext.parse(main_table()), selector))
        self.assertFalse(htmltext.select(htmltext.parse('<aside><table class="jobsTable"></table></aside>'), selector))

    def test_same_empty_marker_and_text_are_required(self):
        variants = [EMPTY.replace('class="noResult"', 'class="other"'),
                    EMPTY.replace('没有搜索到相应职位', ''),
                    EMPTY.replace('没有搜索到相应职位', '没有搜索到相应职位，请重试'),
                    '<tr><td><span class="noResult"></span></td></tr><tr><td>没有搜索到相应职位</td></tr>',
                    EMPTY + '<tr><td>另一个未知结果</td></tr>',
                    EMPTY.replace('<span class="noResult"></span>', '<div class="noResult"></div>')]
        for rows in variants:
            with self.subTest(rows=rows): self.assert_changed(main_table(rows))

    def test_visibility_is_checked_on_marker_row_table_and_ancestors(self):
        for attr in ('hidden', 'style="display:none"', 'style="visibility:hidden !important"'):
            for markup in (main_table(EMPTY.replace('<span ', f'<span {attr} ')),
                           main_table(EMPTY.replace('<tr>', f'<tr {attr}>')),
                           main_table(attrs=attr), main_table(module_attrs=attr)):
                with self.subTest(markup=markup): self.assert_changed(markup)

    def test_main_job_link_or_unknown_nonempty_row_cannot_be_empty(self):
        for rows in (EMPTY + '<tr><td><a href="/zpdetail/123">示例岗位</a></td></tr>',
                     '<tr><td>示例无链接岗位</td></tr>',
                     '<tr><td><a href="/zpdetail/123">示例岗位</a></td></tr>',
                     EMPTY.replace('</p>', '<a href="/zpdetail/123"></a></p>')):
            with self.subTest(rows=rows): self.assert_changed(main_table(rows))

    def test_nonzero_counts_prevent_empty_even_with_unknown_count_markup(self):
        for count in ('<div class="tablenote">共 2 条记录</div>', '<div>共1条</div>',
                      '<div class="pager">共 5 条记录</div>'):
            with self.subTest(count=count): self.assert_changed(main_table(after=count))
        self.assert_changed(main_table() + '<div class="tablenote">共7条记录</div>')

    def test_hidden_count_does_not_override_visible_empty(self):
        self.assertTrue(self.rules.list_is_empty(htmltext.parse(main_table(after='<div hidden>共9条记录</div>'))))

    def test_main_container_is_required(self):
        for markup in (main_table().replace('positionlist-smallblue', 'article'),
                       main_table().replace('class="joblist"', 'class="other"'),
                       main_table().replace('<table ', '<div><table ').replace('</table>', '</table></div>'),
                       '<article>没有搜索到相应职位</article>' + SIDEBAR,
                       '<aside>' + EMPTY + '</aside>', SIDEBAR):
            with self.subTest(markup=markup): self.assert_changed(markup)

    def test_zero_count_cannot_fill_missing_new_template_evidence(self):
        self.assert_changed(main_table(rows='') + '<div class="tablenote">共0条记录</div>')
        self.assert_changed(main_table(EMPTY.replace('noResult', 'other')) + '<div class="zx_nojob">空</div>')

    def test_multiple_main_tables_must_all_be_consistent(self):
        self.assertTrue(self.rules.list_is_empty(htmltext.parse(main_table() + main_table())))
        self.assert_changed(main_table() + main_table(rows=''))
        self.assert_changed(main_table() + main_table('<tr><td>未知结果</td></tr>'))

    def test_mixed_visible_templates_stop_even_if_old_parser_finds_cards(self):
        for old in (legacy_list([], 1, 1, 0), legacy_list([('151000002', '示例甲')], 1, 1, 1)):
            with self.subTest(old=old): self.assert_changed(main_table() + old)

    def test_old_empty_and_nonempty_templates_keep_their_behavior(self):
        old_empty = legacy_list([], 1, 1, 0)
        result, _ = self.run_page(old_empty)
        self.assertEqual(result["finished"], "no_results")
        old_full = htmltext.parse(legacy_list([('151000002', '示例甲')], 1, 1, 1))
        self.assertFalse(self.rules.list_is_empty(old_full))
        self.assertEqual(len(self.rules.parse_cards(old_full, self.rules.search_url('', '4401'))[0]), 1)

    def test_security_checks_take_priority_over_explicit_empty(self):
        for markup, options in ((main_table(), {'status':403}), (main_table(), {'status':429}),
                                (main_table()+'<div class="geetest_panel">验证</div>', {}),
                                (main_table(), {'title':'安全验证'}),
                                (main_table()+'<form action="/login">登录</form>', {})):
            with self.subTest(options=options, markup=markup):
                result, _ = self.run_page(markup, **options)
                self.assertEqual((result['status'], collect.exit_code(result)), ('needs_user',3))


if __name__ == '__main__':
    unittest.main()
