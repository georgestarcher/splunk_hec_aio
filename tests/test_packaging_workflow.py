import configparser
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPackagingWorkflow(unittest.TestCase):
    def test_packaging_tool_pins_match_the_development_extra(self):
        configuration = configparser.ConfigParser()
        configuration.read(ROOT / "setup.cfg", encoding="utf-8")
        development_requirements = {
            requirement.strip()
            for requirement in configuration["options.extras_require"]["dev"].splitlines()
            if requirement.strip()
        }
        workflow = (ROOT / ".github" / "workflows" / "packaging.yml").read_text(
            encoding="utf-8"
        )

        for requirement in development_requirements:
            with self.subTest(requirement=requirement):
                self.assertIn('"{}"'.format(requirement), workflow)
