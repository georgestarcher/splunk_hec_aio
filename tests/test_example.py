import os
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import splunk_hec_aio.splunk_hec_aio as runtime_module

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {path.stem: path for path in (ROOT / "examples").glob("*.py")}
EXAMPLES_README_PATH = ROOT / "examples" / "README.md"
README_PATH = ROOT / "README.md"


def example_environment(**overrides):
    environment = {
        "SPLUNK_HEC_HOST": "splunk.example.com",
        "SPLUNK_HEC_TOKEN": "hec-token",
        "SPLUNK_HEC_PORT": "443",
        "SPLUNK_HEC_INDEX": "test",
        "SPLUNK_HEC_SOURCETYPE": "aio_json",
    }
    environment.update(overrides)
    return environment


def execute_example(path, sender, environment):
    namespace = {
        "__file__": str(path),
        "__name__": "__main__",
    }
    with (
        patch.object(
            runtime_module, "SplunkHecAio", return_value=sender
        ) as sender_class,
        patch.dict(os.environ, environment, clear=True),
        patch("builtins.print"),
    ):
        source = path.read_text(encoding="utf-8")
        exec(compile(source, str(path), "exec"), namespace)
    return sender_class


class TestReadmeQuickStart(unittest.TestCase):
    def test_quick_start_uses_the_public_class_without_network_access(self):
        readme = README_PATH.read_text(encoding="utf-8")
        section = re.search(
            r"^## Quick start\n(?P<body>.*?)(?=^## )", readme, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(section)
        code_block = re.search(
            r"```python\n(?P<code>.*?)```", section.group("body"), re.DOTALL
        )
        self.assertIsNotNone(code_block)

        sender = MagicMock()
        environment = {
            "SPLUNK_HEC_HOST": "splunk.example.com",
            "SPLUNK_HEC_TOKEN": "hec-token",
            "SPLUNK_HEC_PORT": "443",
        }
        with (
            patch.object(
                runtime_module, "SplunkHecAio", return_value=sender
            ) as sender_class,
            patch.dict(os.environ, environment, clear=False),
        ):
            exec(compile(code_block.group("code"), str(README_PATH), "exec"), {})

        sender_class.assert_called_once_with("splunk.example.com", "hec-token")
        sender.set_port.assert_called_once_with(443)
        sender.set_index.assert_called_once_with("starcher_hec")
        sender.set_sourcetype.assert_called_once_with("aio_json")
        payload = sender.post_data.call_args.args[0]
        self.assertEqual(payload["event"]["message"], "hello from splunk_hec_aio")
        sender.flush.assert_called_once_with()

    def test_readme_documents_stable_v3_and_the_final_legacy_release(self):
        readme = README_PATH.read_text(encoding="utf-8")

        self.assertNotIn("Version/Date:", readme)
        self.assertIn("latest stable release", readme)
        self.assertIn("splunk_hec_aio.git@v2.1.2", readme)
        self.assertIn("final legacy-compatible v2", readme)
        self.assertIn("splunk_hec_aio.git@v3.0.0", readme)
        self.assertIn("Python 3.9 or later", readme)
        self.assertIn("docs/migrating-to-v3.md", readme)


class TestMaintainedExample(unittest.TestCase):
    def test_examples_readme_lists_every_runnable_example(self):
        readme = EXAMPLES_README_PATH.read_text(encoding="utf-8")

        for path in EXAMPLES.values():
            with self.subTest(example=path.name):
                self.assertIn("[`{}`]({})".format(path.name, path.name), readme)

        self.assertIn("SPLUNK_HEC_TOKEN", readme)
        self.assertIn("SPLUNK_HEC_ENABLE_ACK_EXAMPLE", readme)
        ack_section = readme.split("## Indexer acknowledgment safety gate", 1)[1]
        self.assertIn('SPLUNK_HEC_PORT="8088"', ack_section)
        self.assertIn("not installed by the wheel", readme)

    def test_compatible_example_uses_environment_and_flushes(self):
        sender = MagicMock()
        sender_class = execute_example(
            EXAMPLES["example"],
            sender,
            example_environment(SPLUNK_HEC_EVENT_COUNT="3"),
        )

        sender_class.assert_called_once_with("splunk.example.com", "hec-token")
        sender.set_port.assert_called_once_with(443)
        sender.set_index.assert_called_once_with("test")
        sender.set_sourcetype.assert_called_once_with("aio_json")
        sender.set_source.assert_called_once_with("splunk_hec_aio:compatible-example")
        posted_payloads = [call.args[0] for call in sender.post_data.call_args_list]
        self.assertEqual(
            [payload["event"]["sequence"] for payload in posted_payloads],
            [0, 1, 2],
        )
        sender.flush.assert_called_once_with()

    def test_strict_example_collects_structured_results(self):
        sender = MagicMock()
        result = MagicMock(batch_index=0, event_count=1)
        sender.post_data_strict.return_value = tuple()
        sender.flush_strict.return_value = (result,)

        execute_example(EXAMPLES["strict_delivery"], sender, example_environment())

        sender.post_data_strict.assert_called_once()
        sender.flush_strict.assert_called_once_with()

    def test_async_strict_example_awaits_post_and_flush(self):
        sender = MagicMock()
        result = MagicMock(batch_index=0, event_count=1)
        sender.post_data_strict_async = AsyncMock(return_value=tuple())
        sender.flush_strict_async = AsyncMock(return_value=(result,))

        execute_example(
            EXAMPLES["async_strict_delivery"], sender, example_environment()
        )

        sender.post_data_strict_async.assert_awaited_once()
        sender.flush_strict_async.assert_awaited_once_with()

    def test_raw_example_selects_raw_mode_and_flushes(self):
        sender = MagicMock()

        execute_example(
            EXAMPLES["raw_delivery"],
            sender,
            example_environment(SPLUNK_EVENT_HOST="event-host"),
        )

        sender.set_payload_json_format.assert_called_once_with(False)
        sender.set_host.assert_called_once_with("event-host")
        payload = sender.post_data.call_args.args[0]
        self.assertIsInstance(payload, str)
        self.assertTrue(payload.endswith("\n"))
        sender.flush.assert_called_once_with()

    def test_ack_example_requires_explicit_opt_in(self):
        sender = MagicMock()
        path = EXAMPLES["indexer_acknowledgment"]

        with self.assertRaisesRegex(RuntimeError, "indexer acknowledgment enabled"):
            execute_example(path, sender, example_environment())

    def test_ack_example_uses_bounded_polling_and_flushes(self):
        sender = MagicMock()
        result = MagicMock(batch_index=0, ack_id=42)
        sender.post_data_ack.return_value = tuple()
        sender.flush_ack.return_value = (result,)

        execute_example(
            EXAMPLES["indexer_acknowledgment"],
            sender,
            example_environment(
                SPLUNK_HEC_ENABLE_ACK_EXAMPLE="yes",
                SPLUNK_HEC_ACK_TIMEOUT="5",
                SPLUNK_HEC_ACK_POLL_INTERVAL="0.25",
            ),
        )

        self.assertEqual(sender.post_data_ack.call_args.kwargs["timeout"], 5.0)
        self.assertEqual(sender.post_data_ack.call_args.kwargs["poll_interval"], 0.25)
        sender.flush_ack.assert_called_once_with(timeout=5.0, poll_interval=0.25)


if __name__ == "__main__":
    unittest.main()
