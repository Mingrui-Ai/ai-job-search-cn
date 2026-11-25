"""Work addresses must not turn street names into extra work cities."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from jobsearch_cn import jd_parser, schema

REPO = Path(__file__).resolve().parent.parent


def parse(address):
    [record], _ = jd_parser.parse_text("职位名称：软件开发工程师\n" + address + "\n任职要求：熟悉Python。")
    return record


class AddressCities(unittest.TestCase):
    def test_street_names_do_not_add_cities(self):
        for address, expected in (
                ("工作地点：上海市黄浦区南京东路100号", ["上海"]),
                ("工作地址：杭州市中山北路100号", ["杭州"]),
                ("办公地点：青岛市香港中路100号", ["青岛"]),
                ("工作城市：广州市北京路100号", ["广州"]),
                ("上班地点：天津市重庆道100号", ["天津"]),
                ("base 上海市南京西路与成都北路交叉口", ["上海"])):
            with self.subTest(address=address):
                record = parse(address)
                self.assertEqual(record["cities"], expected)
                self.assertEqual(record["evidence"]["cities"], {"text": address, "method": "rule"})
                self.assertEqual(schema.validate(record), [])

    def test_street_alone_does_not_establish_a_city(self):
        for street in ("南京西路100号", "北京路100号", "香港中路100号", "中山大道100号", "重庆道100号"):
            with self.subTest(street=street):
                record = parse("工作地址：" + street)
                self.assertEqual(record["cities"], [])
                self.assertNotIn("cities", record["evidence"])

    def test_city_after_street_is_still_read(self):
        record = parse("工作地点：南京西路100号（上海）")
        self.assertEqual(record["cities"], ["上海"])

    def test_multiple_addresses_keep_their_real_cities(self):
        record = parse("工作地点：上海市南京东路100号/南京市中山北路100号")
        self.assertEqual(record["cities"], ["上海", "南京"])

    def test_city_lists_and_administrative_names_still_match(self):
        for address, expected in (
                ("工作地点：南京/中山/香港", ["南京", "中山", "香港"]),
                ("工作地点：南京市鼓楼区；办公地点：北京市朝阳区", ["南京", "北京"]),
                ("工作地点：上海/上海/北京", ["上海", "北京"]),
                ("工作地点：深圳南山区；面试地点：北京", ["深圳"]),
                ("工作地点：南京，负责道路设计", ["南京"])):
            with self.subTest(address=address):
                self.assertEqual(parse(address)["cities"], expected)

    def test_file_import_does_not_match_a_city_named_only_by_the_street(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            shutil.copytree(REPO / "tests/fixtures/cn/profile/tech", data / "profile")
            profile_file = data / "profile/profile.json"
            profile = json.loads(profile_file.read_text(encoding="utf-8"))
            profile["availability"].update(cities=["南京"], remote_ok=False, relocate=False)
            profile_file.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            source = root / "job.txt"
            source.write_text("职位名称：软件开发工程师\n工作地点：上海市黄浦区南京东路100号\n"
                              "任职要求：熟悉Python，负责后端服务开发。\n", encoding="utf-8")

            def cli(*args):
                result = subprocess.run([sys.executable, "-m", "jobsearch_cn", *map(str, args),
                                         "--data-dir", str(data)], cwd=REPO,
                                        capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            parsed = cli("jd", "parse", source, "--save")
            job_id = parsed["jobs"][0]["id"]
            filtered = cli("match", "filter", job_id)
            location = next(item for item in filtered["checks"] if item["check"] == "location")
            self.assertEqual(location["result"], "conflict")
            stored = cli("jd", "show", job_id)
            self.assertEqual(stored["cities"], ["上海"])
            self.assertIn("南京东路", stored["raw_text"])


if __name__ == "__main__":
    unittest.main()
