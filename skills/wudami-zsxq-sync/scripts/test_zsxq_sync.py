#!/usr/bin/env python3
"""Local tests for wudami-zsxq-sync scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import zsxq_fetcher
import zsxq_sync


class FetcherTests(unittest.TestCase):
    def test_normalize_topic_extracts_core_fields(self) -> None:
        topic = {
            "topic_id": 123,
            "topic_uid": 456,
            "create_time": "2026-04-28T08:10:00+0800",
            "talk": {
                "text": "实操教程\n第一步打开页面。",
                "images": [{"url": "a"}, {"url": "b"}],
            },
            "type": "talk",
        }
        item = zsxq_fetcher.normalize_topic(
            topic,
            link_template="https://wx.zsxq.com/topic/{topic_id}",
            summary_length=10,
            category_keywords=zsxq_fetcher.DEFAULT_CATEGORY_KEYWORDS,
        )
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["topic_id"], "123")
        self.assertEqual(item["topic_uid"], "456")
        self.assertEqual(item["created_at"], "2026-04-28 08:10:00")
        self.assertEqual(item["image_count"], 2)
        self.assertEqual(item["category"], "干货教程")
        self.assertTrue(item["url"].endswith("/123"))

    def test_share_url_candidates_prefers_topic_uid(self) -> None:
        item = {"topic_id": "123", "topic_uid": "456"}
        self.assertEqual(zsxq_fetcher.share_url_candidates(item), ["456", "123"])

    def test_share_url_candidates_deduplicates_matching_ids(self) -> None:
        item = {"topic_id": "123", "topic_uid": "123"}
        self.assertEqual(zsxq_fetcher.share_url_candidates(item), ["123"])

    def test_classify_falls_back_to_other(self) -> None:
        self.assertEqual(zsxq_fetcher.classify_text("今天随便聊两句"), "其他")

    def test_summary_interprets_instead_of_copying_body(self) -> None:
        text = "私信通AI已经可以完整导入知识库了！！\n你们的小红书企业和员工号也可以根据用户需求来回复啦~"
        summary = zsxq_fetcher.summarize_text(text, 100, title="私信通AI已经可以完整导入知识...", category="互动问答")
        self.assertIn("介绍", summary)
        self.assertIn("业务自动化", summary)
        self.assertNotEqual(summary, text[:100])


class SyncTests(unittest.TestCase):
    def test_extract_json_with_cli_noise(self) -> None:
        payload = zsxq_sync.extract_json("[identity: user]\n{\"items\": []}\n")
        self.assertEqual(payload, {"items": []})

    def test_existing_topic_records_reads_fields(self) -> None:
        records = [{"record_id": "rec1", "fields": {"topic_id": [{"text": "888"}]}}]
        self.assertEqual(zsxq_sync.existing_topic_records(records), {"888": "rec1"})

    def test_sync_with_fake_lark_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_lark = tmp_path / "lark-cli"
            log_path = tmp_path / "calls.jsonl"
            fake_lark.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys

                    log = {str(log_path)!r}
                    with open(log, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")

                    args = sys.argv[1:]
                    if "+field-list" in args:
                        print(json.dumps({{"items": [{{"name": "topic_id"}}], "total": 1}}, ensure_ascii=False))
                    elif "+field-create" in args:
                        print(json.dumps({{"created": True}}, ensure_ascii=False))
                    elif "+record-list" in args:
                        print(json.dumps({{"items": [{{"record_id": "rec_old", "fields": {{"topic_id": "old-topic"}}}}], "total": 1}}, ensure_ascii=False))
                    elif "+record-upsert" in args:
                        print(json.dumps({{"created": True}}, ensure_ascii=False))
                    else:
                        print(json.dumps({{"ok": True}}, ensure_ascii=False))
                    """
                ),
                encoding="utf-8",
            )
            fake_lark.chmod(0o755)

            config = tmp_path / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "zsxq": {"link_template": "https://wx.zsxq.com/topic/{topic_id}"},
                        "feishu": {"base_token": "base_x", "table_id": "tbl_x"},
                        "sync": {"summary_length": 20},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            input_path = tmp_path / "topics.json"
            input_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"topic_id": "old-topic", "text": "已存在"},
                            {"topic_id": "new-topic", "text": "工具推荐：这个AI工具很好用", "created_at": "2026-04-28 10:00:00"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("zsxq_sync.py")),
                    "--config",
                    str(config),
                    "--input",
                    str(input_path),
                    "--lark-bin",
                    str(fake_lark),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["created_records"], 1)
            self.assertEqual(report["skipped_existing"], 1)
            calls = log_path.read_text(encoding="utf-8")
            self.assertIn("+field-create", calls)
            self.assertIn("+record-upsert", calls)


if __name__ == "__main__":
    unittest.main()
