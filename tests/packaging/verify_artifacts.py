"""Verify distribution metadata and file contents without installing it."""

import argparse
import ast
import re
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import NoReturn

EXPECTED_RUNTIME_MODULES = {
    "splunk_hec_aio/__init__.py",
    "splunk_hec_aio/splunk_hec_aio.py",
}
EXPECTED_RUNTIME_REQUIREMENTS = {"aiohttp", "aiohttp-retry"}
EXPECTED_CLASSIFIERS = {
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: System :: Logging",
}
EXPECTED_PROJECT_URLS = {
    "Documentation": "https://github.com/georgestarcher/splunk_hec_aio#readme",
    "Issues": "https://github.com/georgestarcher/splunk_hec_aio/issues",
    "Source": "https://github.com/georgestarcher/splunk_hec_aio",
}
FORBIDDEN_PARTS = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "env",
    "venv",
}
FORBIDDEN_NAMES = {
    ".coverage",
    ".ds_store",
    ".env",
    ".netrc",
    "coverage.xml",
    "credentials",
    "credentials.json",
    "junit.xml",
    "splunkresults.json",
}
FORBIDDEN_SUFFIXES = (".key", ".p12", ".pem", ".pfx", ".pyc", ".pyo")
ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def normalized_requirement(requirement):
    name = re.split(r"[<=>!~; [(]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def read_source_version(root: Path) -> str:
    path = root / "splunk_hec_aio" / "splunk_hec_aio.py"
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


def verify_metadata(metadata, artifact, expected_version):
    expected = {
        "Name": "Splunk-HEC-AIO",
        "Version": expected_version,
        "Summary": (
            "This is a python class file for use with other python scripts to "
            "send events to a Splunk http event collector."
        ),
        "Keywords": "splunk hec aio",
        "Requires-Python": ">=3.9",
        "License": "MIT",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            fail(
                "{}: expected metadata {}={!r}, got {!r}".format(
                    artifact, key, value, metadata.get(key)
                )
            )

    classifiers = set(metadata.get_all("Classifier", []))
    if classifiers != EXPECTED_CLASSIFIERS:
        fail("{}: classifiers changed: {!r}".format(artifact, classifiers))

    runtime_requirements = {
        normalized_requirement(value)
        for value in metadata.get_all("Requires-Dist", [])
        if "extra ==" not in value
    }
    if runtime_requirements != EXPECTED_RUNTIME_REQUIREMENTS:
        fail(
            "{}: runtime requirements changed: {!r}".format(
                artifact, runtime_requirements
            )
        )

    if set(metadata.get_all("Provides-Extra", [])) != {"dev"}:
        fail("{}: expected only the dev dependency extra".format(artifact))
    dev_requirements = {
        normalized_requirement(value)
        for value in metadata.get_all("Requires-Dist", [])
        if "extra ==" in value
    }
    if dev_requirements != {"build", "twine"}:
        fail("{}: development requirements changed".format(artifact))

    project_urls = dict(
        value.split(", ", 1) for value in metadata.get_all("Project-URL", [])
    )
    if project_urls != EXPECTED_PROJECT_URLS:
        fail("{}: project URLs changed: {!r}".format(artifact, project_urls))


def verify_common_contents(names, artifact):
    for name in names:
        path = PurePosixPath(name)
        lower_parts = {part.lower() for part in path.parts}
        if (
            FORBIDDEN_PARTS.intersection(lower_parts)
            or path.name.lower() in FORBIDDEN_NAMES
            or path.name.lower().endswith(FORBIDDEN_SUFFIXES)
        ):
            fail(
                "{}: forbidden local or generated file included: {}".format(
                    artifact, name
                )
            )


def verify_wheel(path, expected_version):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_name = next(
            (name for name in names if name.endswith(".dist-info/METADATA")), None
        )
        if metadata_name is None:
            fail("{}: wheel metadata is missing".format(path))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))

    verify_metadata(metadata, path, expected_version)
    verify_common_contents(names, path)

    runtime_modules = {
        name
        for name in names
        if name.startswith("splunk_hec_aio/") and name.endswith(".py")
    }
    if runtime_modules != EXPECTED_RUNTIME_MODULES:
        fail("{}: unexpected runtime modules: {!r}".format(path, runtime_modules))
    if any(PurePosixPath(name).parts[0] == "tests" for name in names):
        fail("{}: tests must not be installed by the wheel".format(path))
    if any(PurePosixPath(name).parts[0] == "examples" for name in names):
        fail("{}: examples must not be installed by the wheel".format(path))


def verify_sdist(path, expected_version):
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        roots = {PurePosixPath(name).parts[0] for name in names if name}
        if len(roots) != 1:
            fail("{}: sdist must have one top-level directory".format(path))
        root = next(iter(roots))
        metadata_name = "{}/PKG-INFO".format(root)
        try:
            metadata_file = archive.extractfile(metadata_name)
        except KeyError:
            metadata_file = None
        if metadata_file is None:
            fail("{}: sdist metadata is missing".format(path))
        metadata = BytesParser().parsebytes(metadata_file.read())

    verify_metadata(metadata, path, expected_version)
    verify_common_contents(names, path)

    required = {
        "{}/LICENSE".format(root),
        "{}/README.md".format(root),
        "{}/examples/README.md".format(root),
        "{}/examples/example.py".format(root),
        "{}/pyproject.toml".format(root),
        "{}/setup.cfg".format(root),
        "{}/setup.py".format(root),
        "{}/splunk_hec_aio/__init__.py".format(root),
        "{}/splunk_hec_aio/splunk_hec_aio.py".format(root),
        "{}/tests/fixtures/v2_1_1_public_api.json".format(root),
        "{}/tests/test_v2_public_api.py".format(root),
    }
    missing = required.difference(names)
    if missing:
        fail("{}: required sdist files are missing: {!r}".format(path, missing))
    if "{}/splunk_hec_aio/splunk_hec_aio_test.py".format(root) in names:
        fail("{}: legacy tests remain inside the runtime package".format(path))


def parse_arguments(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    parser.add_argument("artifacts", nargs="+")
    return parser.parse_args(arguments)


def main(arguments=None):
    options = parse_arguments(arguments)
    expected_version = options.expected_version or read_source_version(ROOT)
    artifacts = [Path(argument) for argument in options.artifacts]
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(artifacts) != 2:
        fail("expected exactly one wheel and one .tar.gz sdist")

    verify_wheel(wheels[0], expected_version)
    verify_sdist(sdists[0], expected_version)
    print("Verified wheel and sdist metadata and contents.")


if __name__ == "__main__":
    main()
