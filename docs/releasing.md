# Release verification and publication

Releases are built from the same source and compatibility contract used by
normal CI. The current automated workflow is deliberately a dry run: it proves
a candidate and retains the evidence for seven days, but it cannot create a
tag, GitHub release, or PyPI upload.

## Distribution policy

The final planned v2 release, v2.1.2, will use GitHub Releases only. Existing
releases and tags remain available and must never be deleted, overwritten,
force-moved, or retagged. PyPI is not an established distribution channel for
the v2 line, so the dry run has no package-index credentials or publishing
permission.

Publication remains a separate, approval-gated step tracked by issues
[#20](https://github.com/georgestarcher/splunk_hec_aio/issues/20) and
[#30](https://github.com/georgestarcher/splunk_hec_aio/issues/30). A successful
dry run is evidence for that decision; it is not itself a release.

## Run the protected dry run

1. Merge the intended candidate commit to `main`. The workflow rejects any
   other ref.
2. Confirm that the runtime `__version__`, the `setup.cfg` authoritative-version
   reference, and the dated `CHANGELOG.md` section describe the same stable
   `X.Y.Z` version.
3. In GitHub Actions, select **Release verification**, choose **Run workflow**
   on `main`, enter the candidate version, and select one allowed v2
   compatibility classification:
   - `no-observable-behavior-change`;
   - `backward-compatible-bug-fix`; or
   - `opt-in-addition`.
4. Wait for the complete compatibility, quality, and packaging workflows plus
   the exact-candidate job. A breaking classification is intentionally not an
   available v2 option.
5. Download the temporary `release-candidate-...` workflow artifact and retain
   its workflow-run URL for the release record.

The bundle contains exactly one wheel, one source distribution,
`SHA256SUMS`, and `release-candidate.json`. The manifest records the full Git
commit, branch ref, version, compatibility classification, filenames, and
SHA-256 digests. The workflow checks both distributions with Twine and the
repository allowlist, installs both exact artifacts outside the checkout, runs
the public API snapshot, and verifies the checksums after staging the bundle.

The workflow has read-only repository permission, uses no environment or
secret, and has no tag or publication trigger. Its candidate artifact expires
after seven days and must not be presented as an official release asset.

## Reproduce artifact checks locally

From a clean checkout with the development extra installed:

```shell
rm -rf build dist *.egg-info release-candidate
python -m unittest discover -s tests -v
python -m build
python -m twine check dist/*
python tests/packaging/verify_artifacts.py dist/*
python .github/scripts/verify_release_candidate.py validate \
  --version 2.1.1 \
  --classification no-observable-behavior-change \
  --ref refs/heads/main
python .github/scripts/verify_release_candidate.py manifest \
  --version 2.1.1 \
  --classification no-observable-behavior-change \
  --ref refs/heads/main \
  --commit "$(git rev-parse HEAD)" \
  --output release-candidate \
  dist/*
```

Use the actual candidate version in place of `2.1.1`. Local output is only
diagnostic evidence; the GitHub-hosted dry run remains the release gate.

## Final v2.1.2 publication gate

Before v2.1.2 is published, maintainers must also:

- review the complete diff from v2.1.1 and confirm there is no unapproved
  installed or wire-visible behavior change;
- run the protected **Live Splunk integration** workflow against the exact
  candidate commit and retain its successful run URL;
- obtain approval for the final release commit, changelog, compatibility
  classification, and generated notes;
- create a new verified `v2.1.2` tag without changing any existing tag; and
- attach the already verified wheel, source distribution, checksums, and
  compatibility notes to the GitHub release.

Automated publication is not implemented by the dry-run workflow. Adding it
requires a separately reviewed job with a protected GitHub environment,
least-privilege write permission limited to that job, exact-tag validation,
and a no-overwrite check.

## Recovery

Never replace an artifact or move a published tag. If a release is defective,
stop recommending it, document the impact, and publish a new corrective
version after the normal gates. A GitHub release may be marked as a pre-release
or otherwise withdrawn from recommendation while its immutable evidence and
the prior releases remain available.

Because v2 is not published on PyPI, there is no v2 package-index yank step. If
a future major release adopts PyPI, it must use Trusted Publishing with a
protected environment and document index-specific yank and recovery steps
before that channel is enabled.
