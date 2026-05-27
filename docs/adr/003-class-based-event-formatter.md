# ADR-003: Class-based EventFormatter with dispatch table

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** Mid-iteration refactor

## Context

The original `lambda_formatter.py` was a single procedural handler with an `if source == "aws.states": ... elif source == "aws.dms": ... elif source == "aws.glue": ...` chain that built the title, description, deep-link, and Chatbot payload all in one ~70-line block.

The chain had three problems:

1. **Adding a new AWS source required editing the I/O glue.** The `sns.publish(...)` call lived in the same file as the per-source string-building, so a change to "I want to add ECS support" forced a diff that touched both.
2. **Testing required mocking SNS.** Even a test of "does the title for a Glue failure start with 🚨?" had to set up a `boto3.client('sns')` mock, build a fake event, invoke the handler, capture the SNS publish call, parse JSON. That's a lot of ceremony for a string-format assertion.
3. **Severity classification couldn't be added cleanly.** When we added warning / success / info tiers, the procedural chain doubled in length because each branch needed both classification and string-building.

## Decision

Split the handler into two files:

- **`lambda/lambda_formatter.py`** (13 lines): module-level boto3 SNS client, module-level `EventFormatter` instance, `lambda_handler` that calls `_formatter.format(event)` and publishes the result.
- **`lambda/event_formatter.py`**: an `EventFormatter` class with one method per AWS source (`_format_step_functions`, `_format_glue`, `_format_dms_task`, `_format_dms_table`, `_format_unknown`), a `Severity` enum, and a `_dispatch(source, detail_type)` method that returns the appropriate formatter as a callable.

The dispatch table is a five-line `if/elif` returning method references, not strings, not results.

## Consequences

### Positive

- **Adding a new source is one method + one dispatch line.** Roughly 30 lines including the test.
- **Tests don't need to mock SNS for format-shape assertions.** Construct an `EventFormatter(region="us-east-1")` directly, call `.format(event)`, assert on the returned dict. This is why `tests/unit/test_lambda_formatter.py` has 12 cases that run in milliseconds.
- **Severity classification is per-source and obvious.** Each `_format_<source>` returns `(title, description, log_url, severity)`. Step Functions returns `SUCCESS` for `status == "SUCCEEDED"`, `ERROR` otherwise; DMS Table classifies `"completed with issues"` as `WARNING`. The classification logic lives next to the source-specific knowledge that produces it.
- **Re-run hints became a one-method feature.** The `_rerun_hint(kind, name)` helper is called from `_format_glue` and `_format_step_functions` (only on error severity). Adding the hint to a new source means one line in the source's method.

### Negative

- **Two files instead of one.** New contributors have to understand the split.
- **The dispatch table is hand-maintained.** A decorator-based registry (`@register("aws.states")`) would scale further, but at four sources the explicit `if/elif` is more readable.
- **`EventFormatter` is instantiated at module import time.** Tests that need a different `region` or `rerun_hints_enabled` configuration have to construct their own instance — they can't reuse `lambda_formatter._formatter`. This is documented in the formatter tests.

## Alternatives considered

- **Registry-decorator pattern.** Use `@register("aws.states", "Step Functions Execution Status Change")` to populate a dispatch dict. Rejected at four sources — overkill. Worth revisiting if we ever get past ten.
- **One class per source.** `StepFunctionsFormatter`, `GlueFormatter`, etc., each implementing a `Formattable` protocol. Rejected — at this size, methods on one class are easier to read than five classes in five files.
- **Keep the procedural chain, just clean it up.** Rejected — doesn't solve the testing-ceremony problem and doesn't help severity classification.

## Where this pattern came from

The class-based shape is borrowed from DataForge's `DMSServerlessManager` in `lambda/dms-serverless/start_dms_serverless.py`. That codebase encapsulates the boto3 client and the workflow on top of it as a class, exactly for the testability reason.

## Related

- [outbound-alerts.md § Formatter Lambda](../outbound-alerts.md#formatter-lambda).
- [severity-classification.md § The dispatch pattern](../severity-classification.md#the-dispatch-pattern).
