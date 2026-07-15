import configparser
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestPackagingWorkflow(unittest.TestCase):
    def test_packaging_tool_pins_match_the_development_extra(self):
        workflow_path = ROOT / ".github" / "workflows" / "packaging.yml"
        if not workflow_path.is_file():
            self.skipTest("packaging workflow is not included in distributions")

        configuration = configparser.ConfigParser()
        configuration.read(ROOT / "setup.cfg", encoding="utf-8")
        development_requirements = {
            requirement.strip()
            for requirement in configuration["options.extras_require"][
                "dev"
            ].splitlines()
            if requirement.strip()
        }
        workflow = workflow_path.read_text(encoding="utf-8")

        for requirement in development_requirements:
            with self.subTest(requirement=requirement):
                self.assertIn('"{}"'.format(requirement), workflow)
