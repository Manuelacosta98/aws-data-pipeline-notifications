# ADR-001: Event-driven over polling for AWS state changes

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** Initial design

## Context

The project's job is to surface AWS pipeline failures into Slack with near-real-time latency. There are two obvious shapes for the system:

1. **Poll** — a scheduled Lambda or EC2 process queries Glue, DMS, and Step Functions APIs every N seconds, diffs the result against the previous poll, and emits alerts for new failures.
2. **Push** — register EventBridge rules that match the native state-change events these services already emit on the default bus.

Latency, cost, and reliability all matter. Polling at 30-second intervals adds tail latency and a steady background of API calls; longer intervals make alerts less useful.

## Decision

We use EventBridge rules. Each AWS service we monitor (Glue, DMS, Step Functions) already publishes native state-change events to the default EventBridge bus, with no configuration on our side. We declare CDK `events.Rule(...)` resources that filter by `source` and `detail-type`, with a `detail` pattern matching the failure states we care about, and target the formatter Lambda.

## Consequences

### Positive

- **Sub-second latency** from AWS event to Slack message (typically under 5 seconds end-to-end, mostly Chatbot's render pipeline).
- **No infrastructure to schedule.** No EventBridge cron, no CloudWatch scheduled rule for a poller, no Lambda warm-up problem.
- **No diffing logic.** EventBridge only fires when the state changes, so the formatter Lambda doesn't need to track "what was the last status of this job?" in DynamoDB or anywhere else.
- **Cost is essentially zero.** EventBridge charges per million events; at our volume that's a rounding error.
- **AWS handles retries.** If the target Lambda is throttled, EventBridge retries with exponential backoff per service contract.

### Negative

- **We're coupled to AWS's event schema.** If AWS renames `Step Functions Execution Status Change` (they have, in the past), our filter breaks until the rule is updated.
- **Some services don't emit events for all failure modes.** Glue, for example, emits `Glue Job State Change` for run-level failures but not for some script-level errors. We're at the mercy of what the service publishes.
- **Replay is harder.** If something downstream of EventBridge fails (e.g. the Lambda throws), getting the original event back to replay requires CloudWatch Logs archaeology rather than rerunning a query against the source.

### Mitigations for the negatives

- A test in `tests/unit/test_eventbridge_stack.py` pins the exact `source` + `detail-type` + `detail` for each rule. If AWS changes a schema, the test catches it on the next dependency bump.
- The formatter Lambda has an `_format_unknown` branch that gracefully handles any event we don't recognize — so a new event from an existing source produces an `ℹ️ Pipeline Alert` instead of an exception.

## Alternatives considered

- **Polling with state in DynamoDB.** Rejected — adds a database, adds latency, adds cost, adds bug surface (the diff logic).
- **Subscribing to CloudWatch Logs and parsing for error patterns.** Rejected — fragile, latency depends on log buffering, and AWS services already give us structured events.
- **Using AWS Health events as the signal.** Considered — but Health is account-wide AWS service events, not per-resource state changes. Wrong layer of abstraction.

## Related

- [outbound-alerts.md](../outbound-alerts.md) — the EventBridge rules and the formatter Lambda.
