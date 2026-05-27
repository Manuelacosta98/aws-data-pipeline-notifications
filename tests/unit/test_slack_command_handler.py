"""Tests for the inbound Slack slash-command handler.

Covers the security boundary (HMAC verification, replay rejection,
allowlist enforcement) and the happy path for rerun glue / rerun sfn.
"""

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

# conftest.py at repo root adds ``lambda/`` to sys.path.
import slack_command_handler  # noqa: E402

SIGNING_SECRET = "8f742231b10e8888abcd99yyyzz77def"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv(
        "SLACK_SIGNING_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:111111111111:secret:test",
    )
    monkeypatch.setenv(
        "ALLOWED_GLUE_JOBS", "customer_etl_daily,inventory_sync"
    )
    monkeypatch.setenv("ALLOWED_STATE_MACHINES", "DataPipeline")


@pytest.fixture(autouse=True)
def _patch_secret_lookup():
    # Skip the Secrets Manager API call by short-circuiting the cache helper.
    with patch.object(slack_command_handler, "_get_signing_secret", return_value=SIGNING_SECRET):
        yield


@pytest.fixture
def mock_glue():
    with patch.object(slack_command_handler, "_glue") as m:
        yield m


@pytest.fixture
def mock_sfn():
    with patch.object(slack_command_handler, "_sfn") as m:
        yield m


@pytest.fixture
def fake_context():
    ctx = MagicMock()
    ctx.invoked_function_arn = (
        "arn:aws:lambda:us-east-1:111111111111:function:SlackCommandHandler"
    )
    return ctx


def _signed_event(body: str, ts: int | None = None) -> dict:
    ts = ts or int(time.time())
    base = f"v0:{ts}:{body}".encode("utf-8")
    digest = hmac.new(
        SIGNING_SECRET.encode("utf-8"), base, hashlib.sha256
    ).hexdigest()
    return {
        "body": body,
        "headers": {
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": f"v0={digest}",
        },
    }


# -------------------------------------------------------------------- security


def test_invalid_signature_returns_401(fake_context):
    event = {
        "body": "text=help",
        "headers": {
            "X-Slack-Request-Timestamp": str(int(time.time())),
            "X-Slack-Signature": "v0=wrong",
        },
    }
    resp = slack_command_handler.lambda_handler(event, fake_context)
    assert resp["statusCode"] == 401


def test_old_timestamp_is_rejected_as_replay(fake_context):
    event = _signed_event("text=help", ts=int(time.time()) - 600)
    resp = slack_command_handler.lambda_handler(event, fake_context)
    assert resp["statusCode"] == 401


def test_malformed_timestamp_is_rejected(fake_context):
    event = {
        "body": "text=help",
        "headers": {
            "X-Slack-Request-Timestamp": "not-a-number",
            "X-Slack-Signature": "v0=whatever",
        },
    }
    resp = slack_command_handler.lambda_handler(event, fake_context)
    assert resp["statusCode"] == 401


# ---------------------------------------------------------------- happy paths


def test_help_returns_command_listing(fake_context):
    event = _signed_event("text=help&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)
    body = json.loads(resp["body"])
    assert "Pipeline commands" in body["text"]
    assert body["response_type"] == "ephemeral"


def test_empty_text_returns_help(fake_context):
    event = _signed_event("text=&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)
    body = json.loads(resp["body"])
    assert "Pipeline commands" in body["text"]


def test_rerun_glue_happy_path(mock_glue, fake_context):
    mock_glue.start_job_run.return_value = {"JobRunId": "jr_abc123"}
    event = _signed_event("text=rerun+glue+customer_etl_daily&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)

    mock_glue.start_job_run.assert_called_once_with(JobName="customer_etl_daily")
    body = json.loads(resp["body"])
    assert "Restarted Glue job" in body["text"]
    assert "customer_etl_daily" in body["text"]
    assert "jr_abc123" in body["text"]
    assert "<@U1>" in body["text"]  # auditable user mention
    assert body["response_type"] == "in_channel"


def test_rerun_sfn_with_bare_name_resolves_arn(mock_sfn, fake_context):
    mock_sfn.start_execution.return_value = {
        "executionArn": (
            "arn:aws:states:us-east-1:111111111111:execution:DataPipeline:exec_xyz"
        ),
    }
    event = _signed_event("text=rerun+sfn+DataPipeline&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)

    expected_arn = "arn:aws:states:us-east-1:111111111111:stateMachine:DataPipeline"
    mock_sfn.start_execution.assert_called_once_with(
        stateMachineArn=expected_arn, input="{}"
    )
    body = json.loads(resp["body"])
    assert "Restarted state machine" in body["text"]
    assert "exec_xyz" in body["text"]


def test_rerun_sfn_accepts_full_arn(mock_sfn, fake_context):
    arn = "arn:aws:states:us-east-1:111111111111:stateMachine:DataPipeline"
    mock_sfn.start_execution.return_value = {"executionArn": f"{arn}:my_exec"}
    event = _signed_event(f"text=rerun+sfn+{arn}&user_id=U1")
    slack_command_handler.lambda_handler(event, fake_context)
    mock_sfn.start_execution.assert_called_once_with(
        stateMachineArn=arn, input="{}"
    )


# ----------------------------------------------------------------- guardrails


def test_rerun_glue_rejects_unlisted_job(mock_glue, fake_context):
    event = _signed_event("text=rerun+glue+naughty_job&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)

    mock_glue.start_job_run.assert_not_called()
    body = json.loads(resp["body"])
    assert "not in the allowlist" in body["text"]


def test_rerun_sfn_rejects_unlisted_state_machine(mock_sfn, fake_context):
    event = _signed_event("text=rerun+sfn+DangerousMachine&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)

    mock_sfn.start_execution.assert_not_called()
    body = json.loads(resp["body"])
    assert "not in the allowlist" in body["text"]


def test_unknown_command_returns_warning(fake_context):
    event = _signed_event("text=destroy+everything&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)
    body = json.loads(resp["body"])
    assert "Unrecognized" in body["text"]


def test_unknown_target_returns_warning(fake_context):
    event = _signed_event("text=rerun+kinesis+stream1&user_id=U1")
    resp = slack_command_handler.lambda_handler(event, fake_context)
    body = json.loads(resp["body"])
    assert "Unknown target" in body["text"]
