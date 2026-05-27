# Severity classification

Every alert is classified into one of four severity tiers. Severity drives the emoji prefix in the Slack title and a `keywords` tag in the Chatbot payload (which Slack indexes for search and Workflow Builder filters).

## The four tiers

| Severity   | Emoji | Slack `keywords` | When it fires                                                                              |
|------------|-------|------------------|--------------------------------------------------------------------------------------------|
| `error`    | 🚨    | `error`          | Hard failure of a managed resource. Action required.                                       |
| `warning`  | ⚠️    | `warning`        | Recoverable issue — the pipeline completed but with data quality concerns.                 |
| `success`  | ✅    | `success`        | Pipeline completed end-to-end. Opt-in.                                                      |
| `info`     | ℹ️    | `info`           | Unknown source — graceful fallback when an EventBridge rule routes something we don't know how to format. |

## Classification rules per source

The rules live in `lambda/event_formatter.py` as one method per source.

The formatter handles seven sources today:

| Source                  | Type            | Origin                                                |
|-------------------------|-----------------|-------------------------------------------------------|
| `aws.states`            | Push (native)   | Step Functions execution status changes               |
| `aws.glue`              | Push (native)   | Glue job state changes                                |
| `aws.dms`               | Push (native)   | DMS replication-task + table state changes            |
| `aws.quicksight`        | Push (native)   | QuickSight SPICE ingestion completions                |
| `custom.redshift`       | Pull (monitor)  | Emitted by `redshift_monitor.py` (see [proactive-monitors.md](proactive-monitors.md)) |
| `custom.dms`            | Pull (monitor)  | Emitted by `dms_monitor.py`                           |
| (anything else)         | Push (fallback) | Unknown source → `_format_unknown` produces `info` severity |

### Step Functions (`_format_step_functions`)

| `status`     | Severity   |
|--------------|------------|
| `SUCCEEDED`  | `success`  |
| anything else | `error`    |

We only register an EventBridge rule for `SUCCEEDED` if `notifyOnPipelineSuccess=true` is set, so the success branch is reached only when the operator opted in.

### AWS Glue (`_format_glue`)

| `state`             | Severity   |
|---------------------|------------|
| any of FAILED, STOPPED, ERROR | `error` |

Glue doesn't have a "completed with warnings" state that makes it past our EventBridge filter, so there's no warning branch.

### DMS Replication Task (`_format_dms_task`)

| `state`     | Severity   |
|-------------|------------|
| any of `stopped`, `failed` | `error` |

### DMS Table (`_format_dms_table`)

| `state`                          | Severity   |
|----------------------------------|------------|
| contains `"issue"` (case-insensitive) | `warning` |
| anything else (`Table error`)    | `error`    |

This is the one place where a single EventBridge rule produces alerts of different severities. The classification is done in the formatter, not in EventBridge, so we don't have to maintain two near-identical rules.

### QuickSight (`_format_quicksight`)

Always `error` severity (the EventBridge rule only fires on `FAILED` or `CANCELLED` ingestion statuses). The formatter calls the QuickSight API to actively enrich the event — see [ADR-009](adr/009-active-enrichment-via-boto3.md). The resulting title uses the *human-readable* dataset name resolved via `describe_data_set`, and the description uses the *detailed* error message from `describe_ingestion` rather than the generic message in the EventBridge payload.

### `custom.redshift` (`_format_custom_redshift`)

Emitted by the proactive Redshift monitor (see [proactive-monitors.md](proactive-monitors.md)).

| `status`   | Severity   |
|------------|------------|
| `success`  | `success`  |
| anything else | `error` |

On failure, the formatter renders up to 10 itemized errors with `starttime`, `filename`, `err_reason`, `colname`. The verbose structured output is what makes a Redshift load-failure alert actually actionable.

### `custom.dms` (`_format_custom_dms`)

Emitted by the proactive DMS monitor.

| `status`   | Severity   |
|------------|------------|
| `success`  | `success`  |
| anything else | `error` |

On failure, renders table-level statistics (`error_rows / total_rows` per table) plus up to 10 cleaned field-level log entries. The `clean_dms_log_message` helper strips DMS log noise so the messages are readable in Slack.

### Unknown source (`_format_unknown`)

`info` severity. Returns the raw event detail JSON-dumped into the description. The graceful-fallback path that ensures a misconfigured EventBridge rule never crashes the Lambda.

## The dispatch pattern

`EventFormatter._dispatch` is a small function that returns *the method to call*, not a result. This keeps the dispatch logic separate from the formatting logic:

```python
def _dispatch(self, source, detail_type):
    if source == "aws.states":
        return self._format_step_functions
    if source == "aws.glue":
        return self._format_glue
    if source == "aws.dms":
        if detail_type == "DMS Table State Change":
            return self._format_dms_table
        return self._format_dms_task
    return self._format_unknown
```

The benefits of this shape:

- The `if/elif` chain that selects a formatter is short and trivially readable.
- Adding a new AWS source is one new condition + one new method.
- Tests can call `_dispatch` directly to assert the right method is chosen — no SNS mocking required.

This pattern is borrowed from how DataForge structures `DMSServerlessManager` — see [ADR-003](adr/003-class-based-event-formatter.md).

## Conveying severity to Slack

AWS Chatbot's custom message format does **not** support colored attachment bars (the way a raw Slack webhook would). So we convey severity through two channels Chatbot does respect:

1. **An emoji prefix on the title.** Eye-catching, instantly recognizable in a busy channel.
2. **A `keywords` array on the payload.** Slack indexes these. A user can `keyword:error` in Slack search and get every error alert.

If colored bars become a requirement, the path is to bypass Chatbot for those alerts and post directly to a Slack webhook from the formatter Lambda. The Chatbot path stays for non-actionable alerts. See [ADR-002](adr/002-aws-chatbot-for-outbound.md) for the analysis.

## Opt-in success notifications

The `notifyOnPipelineSuccess` CDK context flag controls whether the `StepFunctionSuccesses` EventBridge rule is created. Off by default.

```bash
uv run cdk synth -c notifyOnPipelineSuccess=true
# or:
# add "notifyOnPipelineSuccess": true to context block in cdk.json
```

The reasoning is volume. A busy AWS account can run hundreds of Step Functions executions a day. Each successful execution would mean a `✅` message in Slack. That's noise that drowns out the failure signal.

When the flag is on, the formatter classifies `SUCCEEDED` as `success`; when it's off, the EventBridge rule that would deliver those events doesn't exist, so the classification branch is unreachable from production.

## Re-run hints and severity

For `error`-severity Glue and Step Functions alerts (the two cases where a re-run is possible), the formatter appends a `🔁 To re-run: /pipeline rerun ...` line to the description — but only if `RERUN_HINTS_ENABLED=true` is set in the Lambda's environment. That env var is set by `EventBridgeStack` when the operator enabled `enableSlackActions`.

Warning- and success-severity alerts never get a re-run hint: a success doesn't need one, and a DMS "completed with issues" warning is recoverable, not failed. The test that guards this is `tests/unit/test_lambda_formatter.py:test_rerun_hint_not_added_to_step_functions_success`.

## Extending the classification

To add a new severity tier:

1. Add a member to `class Severity(str, Enum)` in `lambda/event_formatter.py`.
2. Add an entry to `_SEVERITY_EMOJI`.
3. Return the new severity from whichever `_format_<source>` method should produce it.
4. Update the table at the top of this document.
5. Add a test that asserts the new emoji + keyword pair on a sample event.
