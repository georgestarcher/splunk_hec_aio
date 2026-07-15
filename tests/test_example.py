import builtins
import copy
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import splunk_hec_aio.splunk_hec_aio as runtime_module

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "example.py"


@unittest.skipUnless(
    EXAMPLE_PATH.is_file(), "repository-only root example is unavailable"
)
class TestRootExample(unittest.TestCase):
    def test_example_uses_the_public_class_without_network_access(self):
        sender = MagicMock()
        sender.check_connectivity.return_value = True
        sender.get_post_max_byte_size.return_value = 10000
        posted_payloads = []
        sender.post_data.side_effect = lambda payload: posted_payloads.append(
            copy.deepcopy(payload)
        )

        original_range = range
        limited_builtins = vars(builtins).copy()
        limited_builtins["range"] = lambda _stop: original_range(3)
        namespace = {
            "__builtins__": limited_builtins,
            "__file__": str(EXAMPLE_PATH),
            "__name__": "__main__",
        }

        with patch.object(
            runtime_module, "SplunkHecAio", return_value=sender
        ) as sender_class:
            source = EXAMPLE_PATH.read_text(encoding="utf-8")
            exec(compile(source, str(EXAMPLE_PATH), "exec"), namespace)

        sender_class.assert_called_once_with("MYINSTANCE.splunkcloud.com", "MYTOKEN")
        sender.set_port.assert_called_once_with(443)
        sender.set_index.assert_called_once_with("starcher_hec")
        sender.set_sourcetype.assert_called_once_with("aio_json")
        sender.set_host.assert_called_once_with("dollybean")
        sender.set_source.assert_called_once_with("aio_python")
        sender.set_concurrent_post_limit.assert_called_once_with(20)
        sender.set_post_max_byte_size.assert_called_once_with(10000)
        sender.check_connectivity.assert_called_once_with()
        self.assertEqual(
            [payload["event"]["count"] for payload in posted_payloads], [0, 1, 2]
        )
        sender.flush.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
