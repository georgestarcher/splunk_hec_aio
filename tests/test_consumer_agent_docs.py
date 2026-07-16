import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = ROOT / "AGENTS.md"
GUIDE_PATH = ROOT / "docs" / "consumer-agent-guide.md"
README_PATH = ROOT / "README.md"
EXAMPLES_README_PATH = ROOT / "examples" / "README.md"
EXAMPLES = sorted((ROOT / "examples").glob("*.py"))


class TestConsumerAgentDocumentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = AGENTS_PATH.read_text(encoding="utf-8")
        cls.normalized_agents = " ".join(cls.agents.split())
        cls.guide = GUIDE_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")
        cls.examples_readme = EXAMPLES_README_PATH.read_text(encoding="utf-8")

    def test_readme_and_maintainer_contract_route_consumers_to_the_guide(self):
        link = "docs/consumer-agent-guide.md"

        self.assertIn(link, self.readme)
        self.assertIn(link, self.agents)
        self.assertIn("../docs/consumer-agent-guide.md", self.examples_readme)
        self.assertIn(
            "consumer guidance does not grant permission",
            self.normalized_agents.lower(),
        )
        self.assertIn("repository-maintainer contract", self.normalized_agents)

    def test_guide_covers_the_supported_decision_contract(self):
        required = (
            "## Start with the smallest required facts",
            "## Select and pin the release",
            "## Integration decision tree",
            "## Guided adoption and verification",
            "## Prohibited shortcuts",
            "## Consumer integration checklist",
            "v3.0.0",
            "v2.1.2",
            "Python 3.9 or later",
            "post_data()` and `flush()",
            "post_data_strict()` and `flush_strict()",
            "post_data_ack()` and `flush_ack()",
            "matching `_async` queue and flush methods",
            "set_payload_json_format(False)",
            "Splunk Cloud Platform",
            "Splunk Enterprise",
            "port `8088`",
            "Never ask the user to paste a HEC token",
            "health is not a prerequisite",
            "can create duplicates",
            "one standalone event",
            "one three-event batch",
            "four individual event rows",
        )

        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.guide)

    def test_every_maintained_example_is_linked(self):
        for path in EXAMPLES:
            with self.subTest(example=path.name):
                self.assertIn("../examples/{}".format(path.name), self.guide)

    def test_python_blocks_are_syntactically_valid(self):
        blocks = re.findall(r"```python\n(.*?)```", self.guide, re.DOTALL)
        self.assertGreater(len(blocks), 0)

        for index, block in enumerate(blocks, start=1):
            with self.subTest(block=index):
                ast.parse(block, filename="{}:block-{}".format(GUIDE_PATH, index))

    def test_maintainer_contract_keeps_live_work_protected(self):
        required = (
            "deterministic, secret-free, and isolated from public networks",
            "protected workflow",
            "unique marker",
            "separate searchable rows",
            "1Password MCP server",
            "`splunkquery`",
        )

        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.normalized_agents)


if __name__ == "__main__":
    unittest.main()
