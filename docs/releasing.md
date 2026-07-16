# Release verification and publication

Releases are built from the same source and compatibility contract used by
normal CI. **Release verification** is deliberately a dry run: it proves an
exact candidate and retains the evidence for seven days, but cannot create a
tag, GitHub release, or package-index upload. **Publish verified GitHub
release** can consume that evidence only after a GitHub-verified signed tag and
explicit approval through the protected `GITHUB_RELEASE` environment.

The runtime module, distribution metadata, changelog, signed tag, wheel, source
distribution, checksums, candidate manifest, and release notes must all identify
the same stable `X.Y.Z` version and commit.

## Distribution and immutability policy

This project distributes releases through GitHub Releases rather than PyPI.
Existing releases and tags remain available and must never be deleted,
overwritten, force-moved, or retagged. In particular, v2.1.2 remains the
immutable final legacy-compatible v2 release while v3 is the modern line.

Release verification and publication are manual workflows. Neither is
triggered by a push, and neither creates a tag. Only the publication job has
`contents: write`, and that job pauses at the protected `GITHUB_RELEASE`
environment before creating the release.

## V3.0.0 release checklist

Issue [#44](https://github.com/georgestarcher/splunk_hec_aio/issues/44) is the
release record. Do not create the tag or publish until every item below is
complete on one unchanged `main` commit.

### Prepare the candidate

1. Confirm the runtime `__version__` is `3.0.0`, `setup.cfg` obtains the
   distribution version from that attribute, the package status is stable, and
   `CHANGELOG.md` contains a dated `3.0.0` section.
2. Review the complete `v2.1.2...main` diff and the
   [v3 migration guide](migrating-to-v3.md). Every observable change must be
   traceable to its focused issue and test coverage.
3. Confirm README installation instructions pin `v3.0.0`, explain the retained
   v2.1.2 option, and do not recommend an untagged branch.
4. Merge the reviewed candidate commit to `main`. Both release workflows reject
   any other ref.

### Prove the unchanged `main` commit

1. Confirm the normal compatibility, quality, and packaging checks passed for
   the merged commit.
2. Manually run **Live Splunk integration** from `main`. It must send one
   standalone event and one three-event batch and use querysplunk to prove that
   all four individual event rows are searchable. Record the workflow URL and
   its exact commit on issue #44.
3. Manually run **Release verification** from the same `main` commit with:

   - version `3.0.0`;
   - classification `breaking-major-release`.

4. Wait for the reused compatibility, quality, and packaging workflows and the
   exact-candidate job. Record the successful workflow URL and candidate commit
   on issue #44.
5. Download the temporary `release-candidate-...` artifact. Independently run
   `sha256sum --check --strict SHA256SUMS` and inspect
   `release-candidate.json`. Do not treat this expiring workflow artifact as a
   published release.

If `main` changes after either protected run, restart both runs on the new
candidate commit. Evidence from different commits is not a release candidate.

### Sign and publish the verified candidate

After both protected runs pass on the unchanged current `main` tip, create and
locally verify an annotated signed tag, then push only that tag:

```shell
git fetch --prune origin
git switch main
git pull --ff-only
git tag -s v3.0.0 "$(git rev-parse HEAD)" \
  -m "splunk_hec_aio v3.0.0"
git tag -v v3.0.0
git push origin refs/tags/v3.0.0
```

Never use `--force`, move an existing tag, or let a workflow create the tag.
Confirm GitHub marks the annotated tag signature as verified. If verification
is absent, stop and correct the signing configuration rather than weakening the
workflow.

Run **Publish verified GitHub release** from `main` with:

- version `3.0.0`;
- classification `breaking-major-release`;
- the numeric run ID from the successful Release verification URL.

The validation and preparation jobs prove that the workflow revision, current
`main`, signed annotated tag, successful verification run, candidate manifest,
artifact metadata, packaged runtime bytes, filenames, and SHA-256 digests all
agree. They also reject an expired or unexpected bundle and refuse to overwrite
an existing release.

Review that evidence at the `GITHUB_RELEASE` environment approval. After
approval, the publication job rechecks the tag and current `main`, creates the
release with `--verify-tag` and `--fail-on-no-commits`, attaches exactly the
wheel, source distribution, `SHA256SUMS`, and `release-candidate.json`, and
verifies the published release and each asset against GitHub's immutable
release attestation.

### Post-publication audit

After the workflow succeeds:

1. Confirm v3.0.0 is neither a draft nor a pre-release and is marked latest.
2. Download all four assets and independently recheck `SHA256SUMS`.
3. Run `gh release verify v3.0.0` and
   `gh release verify-asset v3.0.0 FILE` for every downloaded asset.
4. Install both the wheel and source distribution in clean Python 3.9 and 3.13
   environments outside the source checkout and run the installed public-API
   checks.
5. Confirm v2.1.2 and its source downloads remain available.
6. Record the release URL, tag, commit, verification run, live Splunk run, and
   post-publication results on issue #44 before closing it.

## What Release verification proves

The candidate bundle contains exactly one wheel, one source distribution,
`SHA256SUMS`, and `release-candidate.json`. Its manifest records the full Git
commit, branch ref, version, compatibility classification, canonical filenames,
and SHA-256 digests.

The workflow checks both distributions with Twine and the repository allowlist,
installs both artifacts outside the checkout, runs the public API snapshot,
compares packaged runtime files byte-for-byte with the checked-out source, and
verifies the staged checksums. It has read-only repository permission, no
environment, no secret, no publication permission, and no tag or publication
trigger.

The allowed evidence classifications are:

- `no-observable-behavior-change`;
- `backward-compatible-bug-fix`;
- `opt-in-addition`;
- `breaking-major-release`, which is accepted only for an `X.0.0` release and
  is required at major-version boundaries beginning with v3.

## Reproduce historical v2.1.2 checks locally

These commands apply only to the exact source at the signed `v2.1.2` tag, not
to the v3 branch. Use a disposable detached worktree so the historical source,
metadata, and v2-only release helper remain together:

```shell
git fetch --tags origin
git tag -v v2.1.2
git worktree add --detach ../splunk-hec-aio-v2.1.2 v2.1.2
cd ../splunk-hec-aio-v2.1.2
python3.9 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
rm -rf build dist *.egg-info release-candidate
python -m unittest discover -s tests -v
python -m build
python -m twine check dist/*
python tests/packaging/verify_artifacts.py dist/*
python .github/scripts/verify_release_candidate.py validate \
  --version 2.1.2 \
  --classification no-observable-behavior-change \
  --ref refs/heads/main
python .github/scripts/verify_release_candidate.py manifest \
  --version 2.1.2 \
  --classification no-observable-behavior-change \
  --ref refs/heads/main \
  --commit "$(git rev-parse HEAD)" \
  --output release-candidate \
  --source-root . \
  dist/*
```

Local output is diagnostic evidence only; the completed historical GitHub run
and immutable v2.1.2 release remain the release record. Remove the worktree
with `git worktree remove <path>` from the original checkout when finished. Do
not rerun publication, move the v2.1.2 tag, or replace any v2.1.2 asset.

## Recovery

Never replace an artifact or move a published tag. If a release is defective,
stop recommending it, document the impact, and publish a new corrective version
after the normal gates. A release may be marked as a pre-release or otherwise
withdrawn from recommendation while its immutable evidence and prior releases
remain available.

If publication fails before a draft becomes public, inspect the draft and
workflow logs. Because immutability begins only when publication completes, an
administrator may delete that unpublished draft after confirming no public
release exists, then rerun the full validation and approval path. Never apply
this cleanup procedure to a published release.

If a future release adopts PyPI, it must use Trusted Publishing with a protected
environment and document index-specific verification, yank, and recovery steps
before that channel is enabled.
