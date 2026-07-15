import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / ".github" / "scripts" / "verify_release_candidate.py"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-verification.yml"
REUSABLE_WORKFLOW_PATHS = (
    ROOT / ".github" / "workflows" / "compatibility.yml",
    ROOT / ".github" / "workflows" / "quality.yml",
    ROOT / ".github" / "workflows" / "packaging.yml",
)
IS_REPOSITORY_CHECKOUT = (ROOT / ".git").exists()
REPOSITORY_ASSETS = (HELPER_PATH, RELEASE_WORKFLOW_PATH, *REUSABLE_WORKFLOW_PATHS)
MISSING_REPOSITORY_ASSETS = [path for path in REPOSITORY_ASSETS if not path.is_file()]

if IS_REPOSITORY_CHECKOUT and MISSING_REPOSITORY_ASSETS:
    missing = ", ".join(
        str(path.relative_to(ROOT)) for path in MISSING_REPOSITORY_ASSETS
    )
    raise RuntimeError("repository release-verification assets are missing: " + missing)

RELEASE_ASSETS_AVAILABLE = all(path.is_file() for path in REPOSITORY_ASSETS)

if HELPER_PATH.is_file():
    SPEC = importlib.util.spec_from_file_location(
        "verify_release_candidate", HELPER_PATH
    )
    if SPEC is None or SPEC.loader is None:
        raise RuntimeError("could not load the release-verification helper")
    verify_release_candidate = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(verify_release_candidate)
else:
    verify_release_candidate = None


def write_fake_artifacts(directory: Path, version: str):
    metadata = (
        "Metadata-Version: 2.1\nName: Splunk-HEC-AIO\nVersion: {}\n\n".format(version)
    ).encode("utf-8")
    wheel = directory / "Splunk_HEC_AIO-{}-py3-none-any.whl".format(version)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "Splunk_HEC_AIO-{}.dist-info/METADATA".format(version), metadata
        )

    sdist = directory / "Splunk-HEC-AIO-{}.tar.gz".format(version)
    with tarfile.open(sdist, "w:gz") as archive:
        info = tarfile.TarInfo("Splunk-HEC-AIO-{}/PKG-INFO".format(version))
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
    return wheel, sdist


@unittest.skipUnless(
    HELPER_PATH.is_file(), "repository-only release helper is unavailable"
)
class TestReleaseCandidateHelper(unittest.TestCase):
    def test_current_source_is_valid_for_a_nonbreaking_main_candidate(self):
        result = verify_release_candidate.validate_source(
            ROOT,
            "2.1.1",
            "no-observable-behavior-change",
            "refs/heads/main",
        )

        self.assertEqual(result["version"], "2.1.1")

    def test_source_validation_rejects_wrong_ref_version_and_classification(self):
        cases = (
            ("2.1.1", "no-observable-behavior-change", "refs/heads/topic"),
            ("2.1.2", "no-observable-behavior-change", "refs/heads/main"),
            ("2.1.1", "breaking-change", "refs/heads/main"),
        )
        for version, classification, ref in cases:
            with self.subTest(version=version, classification=classification, ref=ref):
                with self.assertRaises(SystemExit):
                    verify_release_candidate.validate_source(
                        ROOT, version, classification, ref
                    )

    def test_manifest_records_exact_artifact_hashes_and_candidate_identity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            artifacts = write_fake_artifacts(temporary_path, "2.1.1")
            output = temporary_path / "candidate"

            verify_release_candidate.write_candidate_files(
                artifacts,
                "2.1.1",
                "no-observable-behavior-change",
                "refs/heads/main",
                "a" * 40,
                output,
            )

            manifest = json.loads(
                (output / "release-candidate.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["version"], "2.1.1")
            self.assertEqual(manifest["commit"], "a" * 40)
            self.assertEqual(
                manifest["classification"], "no-observable-behavior-change"
            )
            recorded_hashes = {
                artifact["filename"]: artifact["sha256"]
                for artifact in manifest["artifacts"]
            }
            expected_hashes = {
                artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest()
                for artifact in artifacts
            }
            self.assertEqual(recorded_hashes, expected_hashes)
            checksums = (output / "SHA256SUMS").read_text(encoding="utf-8")
            for filename, digest in expected_hashes.items():
                self.assertIn("{}  {}\n".format(digest, filename), checksums)

    def test_manifest_rejects_artifact_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = write_fake_artifacts(Path(temporary_directory), "2.1.0")
            with self.assertRaisesRegex(SystemExit, "does not match"):
                verify_release_candidate.describe_artifacts(artifacts, "2.1.1")


@unittest.skipUnless(
    RELEASE_ASSETS_AVAILABLE,
    "repository-only release-verification policy assets are unavailable",
)
class TestReleaseWorkflowPolicy(unittest.TestCase):
    def test_release_workflow_is_manual_read_only_and_nonpublishing(self):
        workflow = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertNotIn("gh release create", workflow)
        self.assertNotIn("pypa/gh-action-pypi-publish", workflow)
        self.assertNotIn("environment:", workflow)
        self.assertNotIn('--version "${{ inputs.version }}"', workflow)
        self.assertIn("CANDIDATE_VERSION: ${{ inputs.version }}", workflow)

    def test_release_workflow_reuses_every_protected_secret_free_gate(self):
        workflow = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")

        for name in ("compatibility", "quality", "packaging"):
            with self.subTest(workflow=name):
                self.assertIn("uses: ./.github/workflows/{}.yml".format(name), workflow)
        self.assertIn(
            "needs:\n      - compatibility\n      - packaging\n      - quality",
            workflow,
        )
        for path in REUSABLE_WORKFLOW_PATHS:
            with self.subTest(workflow=path.name):
                self.assertIn("  workflow_call:", path.read_text(encoding="utf-8"))

    def test_release_workflow_verifies_exact_artifacts_and_uploads_evidence(self):
        workflow = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("verify_artifacts.py dist/*", workflow)
        self.assertIn("verify_installed_distribution.py", workflow)
        self.assertIn("verify_release_candidate.py manifest", workflow)
        self.assertIn("sha256sum --check --strict SHA256SUMS", workflow)
        self.assertIn(
            "release-candidate.json", (HELPER_PATH).read_text(encoding="utf-8")
        )
        self.assertIn("retention-days: 7", workflow)
        self.assertIn("persist-credentials: false", workflow)
        for line in workflow.splitlines():
            if "uses: actions/" in line:
                reference = line.split("@", 1)[1].split()[0]
                self.assertRegex(reference, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
