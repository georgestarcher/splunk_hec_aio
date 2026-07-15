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
PUBLICATION_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-publication.yml"
RELEASE_DOCUMENTATION_PATH = ROOT / "docs" / "releasing.md"
REUSABLE_WORKFLOW_PATHS = (
    ROOT / ".github" / "workflows" / "compatibility.yml",
    ROOT / ".github" / "workflows" / "quality.yml",
    ROOT / ".github" / "workflows" / "packaging.yml",
)
IS_REPOSITORY_CHECKOUT = (ROOT / ".git").exists()
REPOSITORY_ASSETS = (
    HELPER_PATH,
    RELEASE_WORKFLOW_PATH,
    PUBLICATION_WORKFLOW_PATH,
    *REUSABLE_WORKFLOW_PATHS,
)
MISSING_REPOSITORY_ASSETS = [path for path in REPOSITORY_ASSETS if not path.is_file()]

if IS_REPOSITORY_CHECKOUT and MISSING_REPOSITORY_ASSETS:
    missing = ", ".join(
        str(path.relative_to(ROOT)) for path in MISSING_REPOSITORY_ASSETS
    )
    raise RuntimeError("repository release-verification assets are missing: " + missing)

RELEASE_ASSETS_AVAILABLE = all(path.is_file() for path in REPOSITORY_ASSETS)
FAKE_RUNTIME_FILES = {
    Path("splunk_hec_aio/__init__.py"): b"from .splunk_hec_aio import SplunkHecAio\n",
    Path("splunk_hec_aio/splunk_hec_aio.py"): b'__version__ = "2.1.1"\n',
}

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


def write_fake_source(directory: Path):
    for relative_path, contents in FAKE_RUNTIME_FILES.items():
        path = directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    return directory


def write_fake_artifacts(directory: Path, version: str):
    metadata = (
        "Metadata-Version: 2.1\nName: Splunk-HEC-AIO\nVersion: {}\n\n".format(version)
    ).encode("utf-8")
    wheel = directory / "splunk_hec_aio-{}-py3-none-any.whl".format(version)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "splunk_hec_aio-{}.dist-info/METADATA".format(version), metadata
        )
        for relative_path, contents in FAKE_RUNTIME_FILES.items():
            archive.writestr(relative_path.as_posix(), contents)

    sdist = directory / "splunk_hec_aio-{}.tar.gz".format(version)
    with tarfile.open(sdist, "w:gz") as archive:
        info = tarfile.TarInfo("splunk_hec_aio-{}/PKG-INFO".format(version))
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
        for relative_path, contents in FAKE_RUNTIME_FILES.items():
            info = tarfile.TarInfo(
                "splunk_hec_aio-{}/{}".format(version, relative_path.as_posix())
            )
            info.size = len(contents)
            archive.addfile(info, io.BytesIO(contents))
    return wheel, sdist


@unittest.skipUnless(
    HELPER_PATH.is_file(), "repository-only release helper is unavailable"
)
class TestReleaseCandidateHelper(unittest.TestCase):
    def test_current_development_source_is_not_a_stable_release_candidate(self):
        with self.assertRaisesRegex(SystemExit, "stable semantic version"):
            verify_release_candidate.validate_source(
                ROOT,
                "3.0.0.dev0",
                "no-observable-behavior-change",
                "refs/heads/main",
            )

    def test_source_validation_rejects_wrong_ref_version_and_classification(self):
        cases = (
            ("2.1.2", "no-observable-behavior-change", "refs/heads/topic"),
            ("2.1.1", "no-observable-behavior-change", "refs/heads/main"),
            ("2.1.2", "breaking-change", "refs/heads/main"),
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
            source_root = write_fake_source(temporary_path / "source")
            output = temporary_path / "candidate"

            verify_release_candidate.write_candidate_files(
                artifacts,
                "2.1.1",
                "no-observable-behavior-change",
                "refs/heads/main",
                "a" * 40,
                output,
                source_root,
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
            temporary_path = Path(temporary_directory)
            artifacts = write_fake_artifacts(temporary_path, "2.1.0")
            artifacts = tuple(
                artifact.rename(
                    temporary_path / artifact.name.replace("2.1.0", "2.1.1")
                )
                for artifact in artifacts
            )
            with self.assertRaisesRegex(SystemExit, "does not match"):
                verify_release_candidate.describe_artifacts(artifacts, "2.1.1")

    def test_artifact_description_rejects_noncanonical_filenames(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            wheel, sdist = write_fake_artifacts(temporary_path, "2.1.1")
            wheel = wheel.rename(
                temporary_path / "Splunk_HEC_AIO-2.1.1-py3-none-any.whl"
            )
            sdist = sdist.rename(temporary_path / "Splunk-HEC-AIO-2.1.1.tar.gz")

            with self.assertRaisesRegex(SystemExit, "canonical filenames"):
                verify_release_candidate.describe_artifacts((wheel, sdist), "2.1.1")

    def test_candidate_bundle_round_trip_verifies_exact_identity_and_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            artifacts = write_fake_artifacts(temporary_path, "2.1.1")
            source_root = write_fake_source(temporary_path / "source")
            output = temporary_path / "candidate"
            verify_release_candidate.write_candidate_files(
                artifacts,
                "2.1.1",
                "no-observable-behavior-change",
                "refs/heads/main",
                "a" * 40,
                output,
                source_root,
            )
            for artifact in artifacts:
                artifact.rename(output / artifact.name)

            verified = verify_release_candidate.verify_candidate_bundle(
                output,
                "2.1.1",
                "no-observable-behavior-change",
                "refs/heads/main",
                "a" * 40,
                source_root,
            )

            self.assertEqual(verified["version"], "2.1.1")
            self.assertEqual(verified["commit"], "a" * 40)

    def test_candidate_bundle_rejects_tampering_and_unexpected_files(self):
        for mutation in ("artifact", "extra"):
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary_path = Path(temporary_directory)
                    artifacts = write_fake_artifacts(temporary_path, "2.1.1")
                    source_root = write_fake_source(temporary_path / "source")
                    output = temporary_path / "candidate"
                    verify_release_candidate.write_candidate_files(
                        artifacts,
                        "2.1.1",
                        "no-observable-behavior-change",
                        "refs/heads/main",
                        "a" * 40,
                        output,
                        source_root,
                    )
                    for artifact in artifacts:
                        artifact.rename(output / artifact.name)
                    if mutation == "artifact":
                        wheel = next(output.glob("*.whl"))
                        wheel.write_bytes(wheel.read_bytes() + b"tampered")
                    else:
                        (output / "unexpected.txt").write_text(
                            "not releasable\n", encoding="utf-8"
                        )

                    with self.assertRaises(SystemExit):
                        verify_release_candidate.verify_candidate_bundle(
                            output,
                            "2.1.1",
                            "no-observable-behavior-change",
                            "refs/heads/main",
                            "a" * 40,
                            source_root,
                        )

    def test_candidate_bundle_rejects_runtime_bytes_not_in_signed_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            artifacts = write_fake_artifacts(temporary_path, "2.1.1")
            source_root = write_fake_source(temporary_path / "source")
            output = temporary_path / "candidate"
            verify_release_candidate.write_candidate_files(
                artifacts,
                "2.1.1",
                "no-observable-behavior-change",
                "refs/heads/main",
                "a" * 40,
                output,
                source_root,
            )
            for artifact in artifacts:
                artifact.rename(output / artifact.name)
            (source_root / "splunk_hec_aio/splunk_hec_aio.py").write_bytes(
                b'__version__ = "2.1.1"\n# expected signed source\n'
            )

            with self.assertRaisesRegex(SystemExit, "does not match the signed source"):
                verify_release_candidate.verify_candidate_bundle(
                    output,
                    "2.1.1",
                    "no-observable-behavior-change",
                    "refs/heads/main",
                    "a" * 40,
                    source_root,
                )


@unittest.skipUnless(
    RELEASE_ASSETS_AVAILABLE,
    "repository-only release-verification policy assets are unavailable",
)
class TestReleaseWorkflowPolicy(unittest.TestCase):
    def test_historical_v2_reproduction_uses_the_matching_signed_tag(self):
        documentation = RELEASE_DOCUMENTATION_PATH.read_text(encoding="utf-8")
        section = documentation.split(
            "## Reproduce the historical v2.1.2 artifact checks locally", 1
        )[1].split("## Historical v2.1.2 publication procedure", 1)[0]

        self.assertIn("signed `v2.1.2` tag", section)
        self.assertIn("v3 development branch", section)
        self.assertIn("git tag -v v2.1.2", section)
        self.assertIn(
            "git worktree add --detach ../splunk-hec-aio-v2.1.2 v2.1.2",
            section,
        )

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
        guard = workflow.index("Require the main branch before checkout")
        first_checkout = workflow.index("Check out repository")
        self.assertLess(guard, first_checkout)
        self.assertIn('[[ "$GITHUB_REF" != "refs/heads/main" ]]', workflow)

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

        self.assertIn("verify_artifacts.py", workflow)
        self.assertIn("verify_installed_distribution.py", workflow)
        self.assertEqual(workflow.count('--expected-version "$CANDIDATE_VERSION"'), 2)
        self.assertIn("verify_release_candidate.py manifest", workflow)
        self.assertIn("--source-root .", workflow)
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

    def test_publication_is_manual_main_only_and_approval_gated(self):
        workflow = PUBLICATION_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("permissions:\n  actions: read\n  contents: read", workflow)
        self.assertEqual(workflow.count("contents: write"), 1)
        self.assertNotIn("id-token: write", workflow)
        self.assertIn("environment: GITHUB_RELEASE", workflow)
        self.assertIn("attestations: read", workflow)
        self.assertIn('[[ "$GITHUB_REF" != "refs/heads/main" ]]', workflow)
        guard = workflow.index("Require the main branch before checkout")
        first_checkout = workflow.index("Check out the verified release commit")
        self.assertLess(guard, first_checkout)

    def test_publication_consumes_verified_evidence_without_rebuilding(self):
        workflow = PUBLICATION_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'EXPECTED_RUN_PATH=".github/workflows/release-verification.yml"', workflow
        )
        self.assertIn('"$RUN_PATH" != "$EXPECTED_RUN_PATH"', workflow)
        self.assertIn('"$RUN_PATH" != "${EXPECTED_RUN_PATH}@main"', workflow)
        self.assertIn('"$RUN_CONCLUSION" != "success"', workflow)
        self.assertIn('"$RUN_COMMIT" != "$TAG_COMMIT"', workflow)
        self.assertIn('"$GITHUB_SHA" != "$TAG_COMMIT"', workflow)
        self.assertIn("gh run download", workflow)
        self.assertIn("verify_release_candidate.py bundle", workflow)
        self.assertEqual(workflow.count("--source-root ."), 2)
        self.assertNotIn("python -m build", workflow)
        self.assertNotIn("upload-artifact", workflow)

    def test_publication_requires_a_verified_annotated_tag_and_no_overwrite(self):
        workflow = PUBLICATION_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('"$TAG_REF_TYPE" != "tag"', workflow)
        self.assertIn('"$TAG_VERIFIED" != "true"', workflow)
        self.assertIn('"$TAG_COMMIT" != "$MAIN_COMMIT"', workflow)
        self.assertIn("--verify-tag", workflow)
        self.assertIn("--fail-on-no-commits", workflow)
        self.assertIn("--generate-notes", workflow)
        self.assertIn("Release already exists", workflow)
        self.assertIn("Confirm the signed tag is still unchanged", workflow)
        live_main_check = workflow.rindex("git/ref/heads/main")
        publish = workflow.index('gh release create "$EXPECTED_TAG"')
        self.assertLess(live_main_check, publish)
        self.assertIn('gh release verify "$EXPECTED_TAG"', workflow)
        self.assertIn('gh release verify-asset "$EXPECTED_TAG"', workflow)
        for line in workflow.splitlines():
            if "uses: actions/" in line:
                reference = line.split("@", 1)[1].split()[0]
                self.assertRegex(reference, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
