# ADR-007: Hybrid push + pull architecture for non-native error sources

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** When the Redshift and DMS proactive monitors were added

## Context

The outbound flow as originally designed only handled error sources that AWS exposes natively via EventBridge — Glue job state changes, DMS replication task state changes, Step Functions execution status changes, and (later) QuickSight SPICE ingestion failures.

But two of the most operationally painful error sources in a data pipeline are *not* exposed that way:

1. **Redshift COPY load errors** live in the `stl_load_errors` system table. AWS does not emit an EventBridge event when a COPY fails. The only way to know is to query the table.
2. **DMS field-level errors** live in CloudWatch Logs as lines prefixed with `]E:`. AWS emits task-level state events but nothing at the row level. Without these, you know "the task failed" but not "12 rows in `public.policies` failed because of a `String length exceeds DDL length` error in the `policy_holder_name` column."

Two options:

1. **Skip these sources.** Accept that Redshift and DMS field errors won't show up in Slack alerts, and document it as a known gap.
2. **Poll the data sources and emit custom EventBridge events** that flow through the same formatter as native events.

## Decision

We use **hybrid push + pull**: native EventBridge rules for sources AWS pushes (Glue, native DMS, Step Functions, QuickSight), plus Lambda pollers that pull from Redshift / CloudWatch Logs and emit *custom* EventBridge events (`custom.redshift`, `custom.dms`) into the same default bus.

The formatter Lambda has no idea whether an event came from AWS or from one of our pollers — its dispatch table treats `custom.redshift` exactly the same as `aws.glue`. New sources are additive.

## Consequences

### Positive

- **Operational completeness.** The alert channel now reflects what's actually broken in the pipeline, not just what AWS emits events for. Redshift load errors and DMS field errors — the two highest-impact things a data team needs to know about — are first-class alerts.
- **Architecturally clean.** The formatter is the only place that knows about *display*. The pollers are the only places that know about *querying*. New sources slot in by adding one method to the formatter and one stack for the poller.
- **Same Slack channel.** Operators see all alerts in one place, regardless of whether AWS pushed the event or we pulled it. The severity tiers and emoji vocabulary stay consistent.
- **Slack-invokable on-demand.** The poller Lambdas have predictable function names (`CheckRedshiftErrors`, `CheckDMSErrors`), which the Chatbot stack grants `lambda:InvokeFunction` on. Users can run `@aws lambda invoke --function-name CheckRedshiftErrors` from Slack for on-demand diagnostics — see [ADR-008](008-chatbot-invocation-alongside-slash-commands.md).
- **Opt-in via context.** `enableProactiveMonitors=true` plus the relevant env vars. Operators who only want the outbound alerting can ignore the monitors entirely.
- **Cost is essentially zero.** Each poll is a single boto3 round trip; running both monitors hourly costs under $0.01/month at typical volumes.

### Negative

- **More moving parts.** Each monitor is a new CDK stack, a new Lambda, new IAM policies, new tests, new documentation. We added ~600 lines of code total.
- **Polling latency.** Push events arrive in seconds; pull events arrive on whatever schedule the operator configures. If a Redshift load fails at 2 AM and the cron is hourly, the alert is delayed.
- **Pull failures are silent.** If the Redshift Data API rejects the query (e.g. permissions revoked), no event is emitted and no one gets alerted. Mitigation: add a CloudWatch alarm on the poller Lambda's `Errors` metric (listed in [operations.md § Future improvements](../operations.md#future-improvements)).
- **The poller IAM is wider than the formatter's.** The formatter only publishes to SNS; the pollers need `redshift-data:ExecuteStatement`, `dms:DescribeReplicationTableStatistics`, `logs:FilterLogEvents`, and `events:PutEvents`. We scope each grant to specific ARNs.

### Trade-off summary

We accept more code and a small polling-latency penalty in exchange for operational completeness. For a data-platform alerting system whose job is to keep the team informed, missing the two most painful failure sources because AWS doesn't emit events for them is not a defensible position. Polling fills the gap with a tiny ongoing cost.

## Alternatives considered

- **EventBridge Scheduler.** Considered as the trigger for the pollers — would work fine, but adding a schedule is an operational concern, not an architectural one. Left to operator preference. The pollers are designed to be triggered by *anything*: a schedule, an on-demand `@aws lambda invoke`, or even an SNS notification.
- **DMS subscription events via SNS.** DMS lets you subscribe to event categories via SNS. We do that for task-level state changes. But the field-level `]E:` errors are not part of any event category — they exist only in CloudWatch Logs.
- **Redshift event subscriptions.** Redshift has event subscriptions for cluster-level events (snapshot, configuration changes) but not for load errors.
- **Native CloudWatch Logs metric filters that fire on `]E:` matches.** Would generate a CloudWatch alarm. Considered — but the alarm only tells you *that* an error happened, not *what* errors. We need the structured detail (which tables, which rows, which columns), which requires actually reading the logs and formatting them.

## Verification

- **Handler tests:** `tests/unit/test_redshift_monitor.py`, `tests/unit/test_dms_monitor.py` mock `boto3` and assert on the emitted EventBridge payloads.
- **Stack tests:** `tests/unit/test_redshift_monitor_stack.py`, `tests/unit/test_dms_monitor_stack.py` assert on the synthesized CloudFormation template.
- **Formatter tests:** `test_lambda_formatter.py:test_custom_redshift_*` and `test_custom_dms_*` exercise the formatter's classification of the custom events.

## Related

- [proactive-monitors.md](../proactive-monitors.md) — the operational deep-dive on each monitor.
- [ADR-008](008-chatbot-invocation-alongside-slash-commands.md) — explains why these are invocable via `@aws lambda invoke` in addition to a schedule.
- [ADR-009](009-active-enrichment-via-boto3.md) — the related "formatter actively calls AWS APIs" pattern, used for QuickSight.
