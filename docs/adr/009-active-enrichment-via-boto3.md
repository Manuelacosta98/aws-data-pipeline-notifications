# ADR-009: Active enrichment via boto3 inside the formatter

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** When QuickSight ingestion alerts were added

## Context

EventBridge events typically give you a minimum-viable payload: identifiers, status codes, timestamps. They usually do *not* give you the human-readable context you'd want in a Slack alert.

The clearest example is QuickSight SPICE ingestion failures. The native event tells you:

```json
{
  "source": "aws.quicksight",
  "detail-type": "QuickSight Dataset SPICE Ingestion Completed",
  "detail": {
    "dataSetId": "12345678-1234-1234-1234-123456789abc",
    "ingestionId": "a7b3c4d5-e6f7-8901-2345-67890abcdef0",
    "ingestionStatus": "FAILED",
    "errorInfo": {
      "type": "DATA_TOLERANCE_EXCEEDED",
      "message": "Data tolerance exceeded"
    }
  }
}
```

The dataset ID is opaque. The error message is generic. A Slack alert built straight from this would say "Dataset `12345678-1234-...` failed: Data tolerance exceeded." That's not actionable — the on-call engineer doesn't know which dataset this is or what specifically went wrong.

The actually-useful information lives in the QuickSight API:

- `describe_data_set` returns the dataset's human-readable `Name` (e.g. `"Customer Daily Refresh"`).
- `describe_ingestion` returns the *detailed* error message from the ingestion record, which is usually a specific SQL error or row-count mismatch — much more specific than the EventBridge payload's `Data tolerance exceeded`.

## Decision

We **actively enrich** EventBridge events inside the formatter Lambda by calling AWS APIs when the event payload is insufficient. The formatter is granted scoped IAM permissions for the enrichment calls; the calls are wrapped in best-effort error handling so a missing permission or transient failure degrades gracefully into a less-informative alert rather than crashing the Lambda.

Specifically:

- `EventFormatter._format_quicksight` calls `describe_data_set` to resolve the dataset ID → name.
- The same method calls `describe_ingestion` to fetch the detailed error message.
- Both calls are wrapped in `try/except Exception` with logging, so they're best-effort: when they fail, the EventBridge payload's values are used as the fallback.
- The enrichment logic lives in a separate method (`_enrich_quicksight`) so unit tests can monkeypatch it without touching the rest of the formatter.

## Consequences

### Positive

- **Alerts contain the information the on-call actually needs.** "Customer Daily Refresh failed: SPICE rejected 12,431 rows over capacity" is actionable. "Dataset abc-def failed: Data tolerance exceeded" is not.
- **The enrichment lives in one place.** The formatter is the only Lambda in the alerting path that knows how to render events for Slack. Putting enrichment there keeps the responsibility where the rendering happens.
- **Best-effort behavior.** A permission failure on `describe_ingestion` doesn't crash the alert — the EventBridge fallback gets used and the alert is sent with less context. Better than dropping the alert entirely.
- **Easy to add new enrichments.** The pattern generalizes: any `_format_<source>` method can call boto3 helpers from a corresponding `_enrich_<source>` method.
- **Tested in isolation.** The `_enrich_quicksight` method is monkeypatched in tests to return canned values; the formatter test then asserts the resulting Slack payload. No need to mock boto3 at the formatter level.

### Negative

- **The formatter is no longer pure.** Previously, `EventFormatter.format()` was a deterministic function of its input. Now it can make network calls (for QuickSight events) and produce slightly different output depending on what the AWS API returns. This is a real complexity bump.
- **Lambda invocation latency increases.** Each QuickSight alert costs an extra two API round trips (~100–200ms). At the volume the system handles, this is negligible, but it's not zero.
- **IAM widens.** The formatter Lambda's role now has `quicksight:DescribeDataSet`, `quicksight:DescribeIngestion`, `quicksight:DescribeDataSetRefreshProperties`. Scoped to `Resource: "*"` because the QuickSight API doesn't accept resource-level constraints on these actions.
- **Cross-account QuickSight could fail.** If the dataset lives in an account other than the one the Lambda runs in, the `AwsAccountId` from the event might be wrong. We rely on the event's `account` field, which is correct for in-account datasets. Cross-account is not currently a supported use case.

### Trade-off summary

We accept slightly more complex and slightly slower alert delivery in exchange for alerts that are genuinely actionable. For a system whose job is to surface failures in a way the on-call can act on, this is the right cost — a non-actionable alert is barely better than no alert at all.

## Alternatives considered

- **Skip QuickSight entirely.** Don't subscribe to its EventBridge events. Rejected — QuickSight failures matter (they break dashboards stakeholders rely on), and the alert is achievable.
- **Render the alert with the raw IDs from EventBridge.** Rejected — alert quality matters more than formatter purity. Once you've seen the difference between `Dataset abc-def failed` and `"Customer Daily Refresh" failed: row count exceeds SPICE capacity by 12,431`, you don't want to ship the former.
- **Enrich in a separate Lambda (split formatting into "enricher" and "renderer").** Considered — would keep the formatter pure, with enrichment happening in a pre-step. Rejected as over-engineering at this size; the formatter is already a single class with one method per source, and the enrichment helper is colocated with the source-specific method that uses it.
- **Enrich at event time inside the source service (Glue script, etc.).** Not applicable for QuickSight (we don't control its event emission) and would couple our alerting to every individual source's runtime.

## Verification

- **Enrichment is monkeypatchable for tests:** `tests/unit/test_lambda_formatter.py:test_quicksight_failure_uses_enriched_dataset_name_and_error`.
- **Fallback path works:** `test_quicksight_enrichment_falls_back_to_event_payload_on_api_error`.
- **IAM grant exists in the synthesized template:** `tests/unit/test_eventbridge_stack.py:test_formatter_lambda_has_quicksight_describe_permissions`.

## Related

- [outbound-alerts.md § QuickSight](../outbound-alerts.md) — operational view.
- [ADR-003](003-class-based-event-formatter.md) — the class-based formatter structure that makes this clean.
