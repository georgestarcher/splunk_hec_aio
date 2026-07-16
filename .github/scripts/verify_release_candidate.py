"""Validate release inputs and describe verified release-candidate artifacts."""

import argparse
import ast
import configparser
import hashlib
import json
import re
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import NoReturn, Optional

STABLE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ALLOWED_CLASSIFICATIONS = {
    "no-observable-behavior-change",
    "backward-compatible-bug-fix",
    "opt-in-addition",
    "breaking-major-release",
}
VERSION_ATTRIBUTE = "splunk_hec_aio.splunk_hec_aio.__version__"
RUNTIME_FILES = (
    Path("splunk_hec_aio/__init__.py"),
    Path("splunk_hec_aio/splunk_hec_aio.py"),
)


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def read_source_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    versions = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            versions.append(node.value.value)
    if len(versions) != 1:
        fail("runtime module must define exactly one literal __version__")
    return versions[0]


def validate_candidate_identity(version: str, classification: str, ref: str):
    match = STABLE_VERSION.fullmatch(version)
    if match is None:
        fail("version must be a stable semantic version in X.Y.Z form")
    if classification not in ALLOWED_CLASSIFICATIONS:
        fail("classification is not eligible for release verification")
    major, minor, patch = (int(component) for component in match.groups())
    is_major_boundary = major >= 1 and minor == 0 and patch == 0
    if classification == "breaking-major-release" and not is_major_boundary:
        fail("breaking-major-release requires an X.0.0 version")
    if major >= 3 and is_major_boundary and classification != "breaking-major-release":
        fail("an X.0.0 major release must use breaking-major-release")
    if ref != "refs/heads/main":
        fail("release verification must run from refs/heads/main")


def validate_source(root: Path, version: str, classification: str, ref: str) -> dict:
    validate_candidate_identity(version, classification, ref)

    module_version = read_source_version(root / "splunk_hec_aio/splunk_hec_aio.py")
    if module_version != version:
        fail(
            "requested version {!r} does not match runtime version {!r}".format(
                version, module_version
            )
        )

    configuration = configparser.ConfigParser()
    configuration.read(root / "setup.cfg", encoding="utf-8")
    configured_version = configuration.get("metadata", "version")
    if configured_version != "attr: " + VERSION_ATTRIBUTE:
        fail("setup.cfg must obtain the distribution version from " + VERSION_ATTRIBUTE)

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if (
        re.search(r"^## \[{}\](?: -|$)".format(re.escape(version)), changelog, re.M)
        is None
    ):
        fail("CHANGELOG.md has no release section for " + version)

    return {
        "classification": classification,
        "ref": ref,
        "version": version,
    }


def artifact_metadata(path: Path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            metadata_names = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                fail("{} must contain exactly one wheel METADATA file".format(path))
            return BytesParser().parsebytes(archive.read(metadata_names[0]))
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            metadata_names = [
                name
                for name in archive.getnames()
                if len(Path(name).parts) == 2 and name.endswith("/PKG-INFO")
            ]
            if len(metadata_names) != 1:
                fail("{} must contain exactly one sdist PKG-INFO file".format(path))
            metadata_file = archive.extractfile(metadata_names[0])
            if metadata_file is None:
                fail("{} sdist metadata could not be read".format(path))
            return BytesParser().parsebytes(metadata_file.read())
    fail("unsupported release artifact: {}".format(path))


def canonical_artifact_names(version: str):
    return {
        "splunk_hec_aio-{}-py3-none-any.whl".format(version),
        "splunk_hec_aio-{}.tar.gz".format(version),
    }


def artifact_runtime_bytes(path: Path, version: str, relative_path: Path) -> bytes:
    member = relative_path.as_posix()
    if path.suffix == ".whl":
        try:
            with zipfile.ZipFile(path) as archive:
                return archive.read(member)
        except KeyError:
            fail("{} is missing packaged runtime file {}".format(path, member))
    if path.name.endswith(".tar.gz"):
        member = "splunk_hec_aio-{}/{}".format(version, member)
        with tarfile.open(path, "r:gz") as archive:
            try:
                archive_member = archive.getmember(member)
            except KeyError:
                fail("{} is missing packaged runtime file {}".format(path, member))
            if not archive_member.isfile():
                fail("{} packaged runtime member {} is not a file".format(path, member))
            extracted = archive.extractfile(archive_member)
            if extracted is None:
                fail(
                    "{} packaged runtime file {} could not be read".format(path, member)
                )
            return extracted.read()
    fail("unsupported release artifact: {}".format(path))


def verify_source_equivalence(paths, version: str, source_root: Path):
    for relative_path in RUNTIME_FILES:
        source_path = source_root / relative_path
        if not source_path.is_file() or source_path.is_symlink():
            fail(
                "signed source is missing regular runtime file {}".format(relative_path)
            )
        source_bytes = source_path.read_bytes()
        for artifact in paths:
            if artifact_runtime_bytes(artifact, version, relative_path) != source_bytes:
                fail(
                    "{} runtime file {} does not match the signed source".format(
                        artifact, relative_path
                    )
                )


def describe_artifacts(paths, version: str, source_root: Optional[Path] = None):
    artifacts = [Path(path) for path in paths]
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(artifacts) != 2 or len(wheels) != 1 or len(sdists) != 1:
        fail("expected exactly one wheel and one .tar.gz source distribution")
    if {path.name for path in artifacts} != canonical_artifact_names(version):
        fail("release artifacts do not use the exact canonical filenames")

    described = []
    for path in sorted(artifacts, key=lambda item: item.name):
        metadata = artifact_metadata(path)
        if metadata.get("Name") != "Splunk-HEC-AIO":
            fail("{} has unexpected distribution name".format(path))
        if metadata.get("Version") != version:
            fail(
                "{} version {!r} does not match requested version {!r}".format(
                    path, metadata.get("Version"), version
                )
            )
        described.append(
            {
                "filename": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if source_root is not None:
        verify_source_equivalence(artifacts, version, source_root)
    return described


def write_candidate_files(
    paths,
    version: str,
    classification: str,
    ref: str,
    commit: str,
    output: Path,
    source_root: Path,
):
    validate_candidate_identity(version, classification, ref)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("commit must be a full lowercase Git object ID")
    artifacts = describe_artifacts(paths, version, source_root)
    output.mkdir(parents=True, exist_ok=True)
    checksums = "".join(
        "{}  {}\n".format(artifact["sha256"], artifact["filename"])
        for artifact in artifacts
    )
    (output / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    manifest = {
        "artifacts": artifacts,
        "classification": classification,
        "commit": commit,
        "ref": ref,
        "schema_version": 1,
        "version": version,
    }
    (output / "release-candidate.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify_candidate_bundle(
    directory: Path,
    version: str,
    classification: str,
    ref: str,
    commit: str,
    source_root: Path,
) -> dict:
    """Verify a downloaded candidate before it is eligible for publication."""
    validate_candidate_identity(version, classification, ref)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("commit must be a full lowercase Git object ID")
    if not directory.is_dir():
        fail("release-candidate bundle directory does not exist")

    entries = sorted(directory.iterdir(), key=lambda item: item.name)
    if any(not entry.is_file() or entry.is_symlink() for entry in entries):
        fail("release-candidate bundle may contain only regular files")

    manifest_path = directory / "release-candidate.json"
    checksums_path = directory / "SHA256SUMS"
    if not manifest_path.is_file() or not checksums_path.is_file():
        fail("release-candidate bundle is missing its manifest or checksums")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        fail("release-candidate manifest is not valid UTF-8 JSON: {}".format(error))

    expected_manifest_keys = {
        "artifacts",
        "classification",
        "commit",
        "ref",
        "schema_version",
        "version",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_manifest_keys:
        fail("release-candidate manifest has an unexpected schema")
    expected_identity = {
        "classification": classification,
        "commit": commit,
        "ref": ref,
        "schema_version": 1,
        "version": version,
    }
    for key, expected in expected_identity.items():
        if manifest.get(key) != expected:
            fail("release-candidate manifest has an unexpected {}".format(key))

    recorded_artifacts = manifest.get("artifacts")
    if not isinstance(recorded_artifacts, list):
        fail("release-candidate manifest artifacts must be a list")
    artifact_names = []
    for artifact in recorded_artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"filename", "sha256"}:
            fail("release-candidate manifest has an invalid artifact entry")
        filename = artifact.get("filename")
        digest = artifact.get("sha256")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            fail("release-candidate manifest has an invalid artifact identity")
        artifact_names.append(filename)

    expected_names = sorted(artifact_names + ["SHA256SUMS", "release-candidate.json"])
    if [entry.name for entry in entries] != expected_names:
        fail("release-candidate bundle contains unexpected or missing files")

    artifact_paths = [directory / name for name in artifact_names]
    described_artifacts = describe_artifacts(artifact_paths, version, source_root)
    if recorded_artifacts != described_artifacts:
        fail("release-candidate artifact digests do not match the manifest")

    expected_checksums = "".join(
        "{}  {}\n".format(artifact["sha256"], artifact["filename"])
        for artifact in described_artifacts
    )
    try:
        actual_checksums = checksums_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        fail("SHA256SUMS is not valid UTF-8: {}".format(error))
    if actual_checksums != expected_checksums:
        fail("SHA256SUMS does not match the verified candidate artifacts")
    return manifest


def parse_arguments(arguments=None):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", type=Path, default=Path.cwd())
    validate.add_argument("--version", required=True)
    validate.add_argument("--classification", required=True)
    validate.add_argument("--ref", required=True)

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--classification", required=True)
    manifest.add_argument("--ref", required=True)
    manifest.add_argument("--commit", required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--source-root", type=Path, required=True)
    manifest.add_argument("artifacts", nargs="+")

    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("--directory", type=Path, required=True)
    bundle.add_argument("--version", required=True)
    bundle.add_argument("--classification", required=True)
    bundle.add_argument("--ref", required=True)
    bundle.add_argument("--commit", required=True)
    bundle.add_argument("--source-root", type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments=None):
    options = parse_arguments(arguments)
    if options.command == "validate":
        validated = validate_source(
            options.root, options.version, options.classification, options.ref
        )
        print("Validated {version} from {ref} as {classification}.".format(**validated))
        return
    if options.command == "manifest":
        write_candidate_files(
            options.artifacts,
            options.version,
            options.classification,
            options.ref,
            options.commit,
            options.output,
            options.source_root,
        )
        print("Wrote verified release-candidate manifest and SHA-256 checksums.")
        return
    verified = verify_candidate_bundle(
        options.directory,
        options.version,
        options.classification,
        options.ref,
        options.commit,
        options.source_root,
    )
    print(
        "Verified {version} release-candidate bundle from {commit}.".format(**verified)
    )


if __name__ == "__main__":
    main()
