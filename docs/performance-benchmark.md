# Protected HEC performance benchmark

The **Protected HEC performance benchmark** workflow measures bounded synthetic
event delivery from a GitHub-hosted runner to the configured non-production
Splunk Cloud Platform HEC target. It then uses querysplunk to prove that every
sequence-numbered event became a separate searchable row.

This is a maintainer validation tool. It is not ordinary pull-request CI, a
scheduled load generator, a Splunk Cloud capacity test, or a throughput
guarantee for the released module.

## Safety boundary

The workflow:

- runs only through `workflow_dispatch` in the protected
  `SPLUNK_INTEGRATION` environment;
- uses the existing separate ingest-only and search-only credentials;
- requires verified TLS and an explicitly selected allowlisted event count,
  batch threshold, and concurrency value;
- sends fixed-shape synthetic events containing a unique run marker and an
  integer sequence from `0` through `event_count - 1`;
- never calls the HEC health endpoint, because a deployment may allow event
  ingestion while blocking that separate endpoint;
- writes only sanitized aggregate metrics to the GitHub step summary; and
- retains only a bounded status file after failure, never the rendered search,
  querysplunk event stream, raw Splunk results, endpoints, tokens, or payloads.

The existing `SPLUNK_INTEGRATION` environment configuration documented in
[`CONTRIBUTING.md`](../CONTRIBUTING.md) is reused. No additional secret is
required.

## Run stages in order

Run one explicitly selected stage at a time and stop after any delivery,
timeout, search, count, or sequence failure:

1. `100` events as the warm-up;
2. `1000` events as the baseline;
3. `5000` events as the larger run; and
4. optionally `10000` events as the hard-capped run.

Start with the default `512000` maximum batch bytes and concurrency `10`.
Alternative allowlisted values exist for deliberate comparisons, but change
only one control at a time and label results by all selected controls. Selecting
`10000` at dispatch is the explicit opt-in for the largest stage; the helper
rejects any larger or unlisted value.

From GitHub, choose **Actions**, **Protected HEC performance benchmark**, and
**Run workflow** on `main`. The equivalent GitHub CLI command for the warm-up
is:

```shell
gh workflow run hec-performance.yml \
  --ref main \
  -f event_count=100 \
  -f max_batch_bytes=512000 \
  -f concurrency=10
```

Environment protection may pause the job for approval before GitHub releases
the live credentials.

## What the result means

The sender uses the public `post_data_strict_async()` and
`flush_strict_async()` methods. The step summary records:

- requested and accepted event counts;
- approximate uncompressed event bytes;
- maximum batch bytes and concurrency;
- queueing time, including any automatic strict delivery;
- final flush and total sender durations;
- observed sender events per second and accepted HEC batch count;
- peak process memory on the Linux runner when available;
- time from completed send until exact search verification; and
- searchable row count, distinct sequence count, minimum sequence, and maximum
  sequence.

Success requires the searched row count and distinct sequence count to equal
the selected event count, the minimum sequence to be `0`, the maximum sequence
to be `event_count - 1`, and the embedded expected count to agree. Missing rows,
duplicates, out-of-range sequences, partial HEC delivery, or results that do
not become searchable within three minutes fail the run.

The query is time-bounded, index-specific, sourcetype-specific, marker-specific,
read-only, and aggregate-only. Querysplunk validates the rendered YAML before
the send begins.

## Interpret results conservatively

Each result is an environment-specific observation of the selected event
shape, module settings, GitHub runner, network path, Splunk Cloud tenant, and
concurrent workload at that time. It does not establish a Splunk Cloud service
limit, exactly-once delivery, or a general performance promise. Compare runs
only when their inputs and relevant environment are equivalent.
