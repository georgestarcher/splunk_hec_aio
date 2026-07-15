# Release verification and publication

Releases are built from the same source and compatibility contract used by
normal CI. The **Release verification** workflow is deliberately a dry run: it
proves a candidate and retains the evidence for seven days, but it cannot
create a tag, GitHub release, or PyPI upload. The separate **Publish verified
GitHub release** workflow can consume that exact evidence only after a verified
signed tag and explicit approval through the protected `GITHUB_RELEASE`
environment.

## Distribution policy

The final planned v2 release, v2.1.2, will use GitHub Releases only. Existing
releases and tags remain available and must never be deleted, overwritten,
force-moved, or retagged. PyPI is not an established distribution channel for
the v2 line, so the dry run has no package-index credentials or publishing
permission.

Publication remains a separate, approval-gated step tracked by issues
[#20](https://github.com/georgestarcher/splunk_hec_aio/issues/20) and
[#30](https://github.com/georgestarcher/splunk_hec_aio/issues/30). A successful
dry run is evidence for that decision; it is not itself a release and cannot
publish without a maintainer-created signed tag.

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
the public API snapshot, requires canonical distribution filenames, compares
the packaged runtime files byte-for-byte with the signed checkout, and verifies
the checksums after staging the bundle.

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
  --source-root . \
  dist/*
```

Use the actual candidate version in place of `2.1.1`. Local output is only
diagnostic evidence; the GitHub-hosted dry run remains the release gate.

## Publish an approved v2.1.2 candidate

Before creating the tag, confirm that the candidate commit is still the tip of
`main`, record the successful Release verification and protected Live Splunk
integration run URLs, and review the complete diff from v2.1.1. The final
release commit must contain version `2.1.2`, the dated changelog section, and
the approved compatibility classification without an unapproved runtime or
wire-visible behavior change.

Create and locally verify an annotated signed tag at the exact candidate
commit, then push only that new tag:

```shell
git fetch --prune origin
git switch main
git pull --ff-only
git tag -s v2.1.2 "$(git rev-parse HEAD)" \
  -m "splunk_hec_aio v2.1.2 - final planned legacy-compatible v2 release"
git tag -v v2.1.2
git push origin refs/tags/v2.1.2
```

Never use `--force`, move an existing tag, or let the release workflow create a
tag implicitly. Confirm GitHub marks the annotated tag signature as verified.
If verification is absent, stop and correct the signing configuration rather
than weakening the workflow.

In GitHub Actions, run **Publish verified GitHub release** from `main` with:

- version `2.1.2`;
- the exact compatibility classification used by Release verification; and
- the numeric run ID from that successful Release verification URL.

The workflow first proves, under read-only permissions, that:

- the dispatched workflow revision and signed annotated tag both point to the
  current `main` commit;
- GitHub verified the tag signature;
- the referenced Release verification run completed successfully on that same
  commit from `main`;
- the run retains exactly one expected, unexpired candidate bundle;
- its version, compatibility class, commit, canonical filenames, manifest,
  artifact metadata, packaged runtime bytes, signed source, and SHA-256 digests
  all agree; and
- neither a release for the tag nor an unexpected bundle file exists.

Only the final job has `contents: write`, and it pauses at the protected
`GITHUB_RELEASE` environment. Review the tag, commit, verification run, and
candidate evidence before approving the deployment. After approval, the job
rechecks the tag, current `main` tip, and bundle, creates the release with
`--verify-tag` and `--fail-on-no-commits`, attaches exactly the wheel, source
distribution, `SHA256SUMS`, and `release-candidate.json`, prepends the
compatibility evidence to generated notes, and verifies the published state,
asset names, immutable release attestation, and each local asset against that
attestation. Repository release immutability must remain enabled so the
published tag and assets cannot be moved, replaced, or deleted and GitHub
generates the release provenance.

After publication, maintainers must also:

- download all four v2.1.2 assets and independently recheck `SHA256SUMS`;
- run `gh release verify v2.1.2` and `gh release verify-asset v2.1.2 FILE`
  for each downloaded asset;
- confirm the historical v2.1.1 release and source downloads remain available,
  and all four v2.1.2 assets are downloadable;
- verify the release is neither a draft nor a pre-release and is marked latest;
  and
- record the release and workflow URLs on issue #30 before closing the release
  work.

## Recovery

Never replace an artifact or move a published tag. If a release is defective,
stop recommending it, document the impact, and publish a new corrective
version after the normal gates. A GitHub release may be marked as a pre-release
or otherwise withdrawn from recommendation while its immutable evidence and
the prior releases remain available.

If publication fails before the draft becomes public, inspect the draft and
workflow logs. Because immutability begins only when publication completes, an
administrator may delete that unpublished draft after confirming that no public
release exists, then rerun the full validation and approval path. Never apply
this cleanup procedure to a published release.

Because v2 is not published on PyPI, there is no v2 package-index yank step. If
a future major release adopts PyPI, it must use Trusted Publishing with a
protected environment and document index-specific yank and recovery steps
before that channel is enabled.
