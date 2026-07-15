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
from typing import NoReturn

STABLE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ALLOWED_CLASSIFICATIONS = {
    "no-observable-behavior-change",
    "backward-compatible-bug-fix",
    "opt-in-addition",
}
VERSION_ATTRIBUTE = "splunk_hec_aio.splunk_hec_aio.__version__"


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
    if not STABLE_VERSION.fullmatch(version):
        fail("version must be a stable semantic version in X.Y.Z form")
    if classification not in ALLOWED_CLASSIFICATIONS:
        fail("classification is not eligible for a v2 release")
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


def describe_artifacts(paths, version: str):
    artifacts = [Path(path) for path in paths]
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(artifacts) != 2 or len(wheels) != 1 or len(sdists) != 1:
        fail("expected exactly one wheel and one .tar.gz source distribution")

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
    return described


def write_candidate_files(
    paths, version: str, classification: str, ref: str, commit: str, output: Path
):
    validate_candidate_identity(version, classification, ref)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("commit must be a full lowercase Git object ID")
    artifacts = describe_artifacts(paths, version)
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
    manifest.add_argument("artifacts", nargs="+")
    return parser.parse_args(arguments)


def main(arguments=None):
    options = parse_arguments(arguments)
    if options.command == "validate":
        validated = validate_source(
            options.root, options.version, options.classification, options.ref
        )
        print("Validated {version} from {ref} as {classification}.".format(**validated))
        return
    write_candidate_files(
        options.artifacts,
        options.version,
        options.classification,
        options.ref,
        options.commit,
        options.output,
    )
    print("Wrote verified release-candidate manifest and SHA-256 checksums.")


if __name__ == "__main__":
    main()
