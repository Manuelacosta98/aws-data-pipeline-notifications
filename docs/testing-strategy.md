# Testing strategy

The project has 46 unit tests organized into two layers. Each layer guards a different class of bug, and neither layer can substitute for the other.

## Two test layers

### Layer 1: CDK synth-level assertions

Files: `test_eventbridge_stack.py`, `test_chatbot_stack.py`, `test_slack_actions_stack.py`, `test_github_oidc_role_stack.py`.

These tests synthesize a CDK stack and assert against the resulting CloudFormation template. They catch:

- Missing resources (a deleted EventBridge rule, a missing API Gateway route).
- Misconfigured properties (wrong Lambda handler name, wrong runtime, wrong event pattern).
- IAM regressions (a previously-removed managed policy coming back, scope widening from named ARN to `*`).
- Cross-stack contract breaks (the SNS topic ARN not flowing into ChatBotStack).

Sample pattern:

```python
@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App()
    stack = EventBridgeStack(app, "TestEventBridgeStack")
    return assertions.Template.from_stack(stack)


def test_step_functions_failure_rule_filters_terminal_states(template):
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aws.states"],
                "detail-type": ["Step Functions Execution Status Change"],
                "detail": {"status": ["FAILED", "TIMED_OUT", "ABORTED"]},
            }
        },
    )
```

Synth-level tests are fast — the whole CDK suite runs in about 4 seconds — but they cannot exercise the Lambda code at all. A `lambda_formatter.py` that returns garbage would still pass synth tests.

### Layer 2: Handler-level tests with mocked boto3

Files: `test_lambda_formatter.py`, `test_slack_command_handler.py`.

These import the Lambda module and invoke `lambda_handler(event, context)` directly. They catch:

- Wrong emoji on a severity tier.
- Wrong deep-link to the AWS console.
- Missing fields in the Chatbot payload.
- Broken HMAC verification.
- Missing replay protection.
- Broken allowlist enforcement.
- Wrong AWS API call (e.g. `start_job_run` invoked with a misformatted argument).

Sample pattern:

```python
@pytest.fixture
def mock_sns():
    with patch.object(lambda_formatter, "_sns") as m:
        yield m


def test_glue_failure_publishes_error_severity_and_job_link(mock_sns):
    event = { ... }
    lambda_formatter.lambda_handler(event, None)
    msg = json.loads(mock_sns.publish.call_args.kwargs["Message"])
    assert msg["content"]["title"].startswith("🚨")
    assert "customer_etl_daily" in msg["content"]["description"]
```

The handler tests run alongside the CDK tests — same `pytest` invocation, same 4-second total — because boto3 mocks don't hit the network.

## Why both layers

A change to `EventFormatter._format_glue` that returns the wrong emoji will pass every CDK test (the synthesized template doesn't depend on Lambda *behavior*). A change to `events.Rule(...)` that drops the `FAILED` filter will pass every handler test (the handler never sees the rule). You need both to have any real coverage on a CDK + Lambda system.

This split came from observing the failure mode of DataForge's testing approach — the existing tests over there are handler-level only, and a CDK change can silently break the pipeline without any test catching it. The lesson: test the infrastructure-as-code as code, and test the application code as code.

## conftest.py

The repo-root `conftest.py` does two things:

1. Adds `lambda/` to `sys.path` so handler modules can be imported as top-level modules — matching the way the AWS Lambda runtime sees them at execution.
2. Sets `AWS_REGION` and `AWS_DEFAULT_REGION` defaults so module-level `boto3.client("sns")` calls don't trip `NoRegionError` at import time.

Tests can still override via `monkeypatch.setenv(...)`.

## Mocking patterns

### Mocking SNS for the formatter

`patch.object(lambda_formatter, "_sns")` replaces the module-level `_sns` boto3 client. After the call, `mock_sns.publish.call_args.kwargs["Message"]` gives the exact JSON payload that would have been published, which the test then JSON-parses and asserts on.

### Mocking Secrets Manager for the slash command handler

We patch `_get_signing_secret` directly rather than the boto3 secretsmanager client. This is because the cached-secret behavior we're not trying to test in handler tests, only in the helper itself. Sample:

```python
@pytest.fixture(autouse=True)
def _patch_secret_lookup():
    with patch.object(slack_command_handler, "_get_signing_secret",
                      return_value=SIGNING_SECRET):
        yield
```

### Signing requests in tests

The tests compute valid HMAC signatures for their bodies so the security path is exercised end-to-end. Helper:

```python
def _signed_event(body: str, ts: int | None = None) -> dict:
    ts = ts or int(time.time())
    base = f"v0:{ts}:{body}".encode("utf-8")
    digest = hmac.new(SIGNING_SECRET.encode("utf-8"),
                      base, hashlib.sha256).hexdigest()
    return {
        "body": body,
        "headers": {
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": f"v0={digest}",
        },
    }
```

Negative tests pass a wrong signature, an old timestamp, or a malformed timestamp to exercise the rejection paths.

## What's NOT tested

- **Real AWS calls.** No `moto` (the boto3 mocking library), no integration tests against a live AWS account. The trade-off is intentional: synth-level tests cover the CDK side and handler-level tests with mocked boto3 cover the application side. An integration test would mostly verify boto3, EventBridge, and Chatbot behave the way AWS documents — which we trust.
- **End-to-end Slack delivery.** There's no test that posts a real message to a Slack channel. To validate this in a real deployment, fail a Glue job intentionally and watch the channel.
- **Lambda cold-start performance.** Not relevant at this throughput.

## Adding tests when you add features

The rule of thumb: **one CDK test + one handler test per new behavior**.

If you add a new EventBridge rule for ECS task failures:

1. CDK test: `tests/unit/test_eventbridge_stack.py` asserts the rule exists with the right event pattern.
2. Handler test: `tests/unit/test_lambda_formatter.py` asserts the published message has the right title, description, severity, and deep-link.

Skipping either layer leaves a gap.

## Coverage

Last run:

```
Name                              Stmts   Miss  Cover
---------------------------------------------------------------
infra/chatbot_stack.py                8      0   100%
infra/eventbridge_stack.py           15      1    93%
infra/github_oidc_role_stack.py      17      1    94%
infra/slack_actions_stack.py         18      0   100%
lambda/event_formatter.py            83      0   100%
lambda/lambda_formatter.py           13      0   100%
lambda/slack_command_handler.py      81      8    90%
---------------------------------------------------------------
TOTAL                               235     10    96%
```

The uncovered lines are the opt-in branches in `eventbridge_stack` (the `notifyOnPipelineSuccess` rule, only reachable when the flag is set), the `existing_oidc_provider_arn` branch in the OIDC stack, and the rarely-hit cache-refresh branch in `_get_signing_secret`.
