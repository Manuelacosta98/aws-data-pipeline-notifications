"""Slack slash-command handler for re-running failed pipeline jobs.

Supported commands (sent via the ``/pipeline`` slash command in Slack):

    /pipeline rerun glue <job_name>
    /pipeline rerun sfn  <state_machine_name_or_arn>
    /pipeline help

Security:
    * Every request must include a valid ``X-Slack-Signature`` HMAC computed
      over ``v0:<timestamp>:<raw_body>`` using the Slack signing secret.
    * Requests with a timestamp more than 5 minutes old are rejected
      (Slack's recommended replay window).
    * Glue job names and state machine names must appear in the comma-separated
      ``ALLOWED_GLUE_JOBS`` / ``ALLOWED_STATE_MACHINES`` env vars (the CDK stack
      also bakes these into the IAM policy's ``resources`` for defense in
      depth).
    * The Slack ``user_id`` is logged for every invocation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
from typing import Any

import boto3

# Module-level clients reused across warm invocations.
_secrets = boto3.client("secretsmanager")
_glue = boto3.client("glue")
_sfn = boto3.client("stepfunctions")

# In-memory cache for the signing secret. Refreshed every 5 minutes so a
# rotation in Secrets Manager propagates quickly without a redeploy.
_SECRET_TTL_SECONDS = 300
_REPLAY_WINDOW_SECONDS = 300
_cached_secret: dict[str, Any] = {"value": None, "fetched_at": 0.0}


# --------------------------------------------------------------------- helpers


def _get_signing_secret() -> str:
    now = time.time()
    cached = _cached_secret["value"]
    if cached and (now - _cached_secret["fetched_at"]) < _SECRET_TTL_SECONDS:
        return cached
    resp = _secrets.get_secret_value(SecretId=os.environ["SLACK_SIGNING_SECRET_ARN"])
    _cached_secret["value"] = resp["SecretString"]
    _cached_secret["fetched_at"] = now
    return _cached_secret["value"]


def _verify_signature(body: str, timestamp: str, signature: str, secret: str) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > _REPLAY_WINDOW_SECONDS:
            return False
    except (TypeError, ValueError):
        return False
    base = f"v0:{timestamp}:{body}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def _allowlist(env_var: str) -> list[str]:
    return [n.strip() for n in os.environ.get(env_var, "").split(",") if n.strip()]


def _allowed(name: str, env_var: str) -> bool:
    allow = _allowlist(env_var)
    return not allow or name in allow


def _slack_response(text: str, ephemeral: bool = True) -> dict[str, Any]:
    """Build a Slack-compatible HTTP response.

    ``ephemeral`` controls visibility: ephemeral messages are only seen by
    the user who triggered the command, while ``in_channel`` is visible to
    the whole channel — we use the latter for successful re-runs so the team
    has a shared audit trail.
    """
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "response_type": "ephemeral" if ephemeral else "in_channel",
                "text": text,
            }
        ),
    }


def _help_text() -> str:
    return (
        "*Pipeline commands*\n"
        "• `/pipeline rerun glue <job_name>` — start a new run of a Glue job\n"
        "• `/pipeline rerun sfn <state_machine_name>` — start a new Step Functions execution\n"
        "• `/pipeline help` — show this message"
    )


# --------------------------------------------------------------------- handler


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    body = event.get("body") or ""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")

    secret = _get_signing_secret()
    if not _verify_signature(body, timestamp, signature, secret):
        return {"statusCode": 401, "body": "invalid signature"}

    params = urllib.parse.parse_qs(body)
    text = params.get("text", [""])[0].strip()
    user_id = params.get("user_id", ["unknown"])[0]
    print(f"Slack command from user_id={user_id}: {text!r}")

    parts = text.split()
    if not parts or parts[0] == "help":
        return _slack_response(_help_text())

    if parts[0] != "rerun" or len(parts) < 3:
        return _slack_response(":warning: Unrecognized command. Try `/pipeline help`.")

    kind, name = parts[1], parts[2]

    if kind == "glue":
        if not _allowed(name, "ALLOWED_GLUE_JOBS"):
            return _slack_response(
                f":no_entry: Glue job `{name}` is not in the allowlist. "
                "Ask the platform team to add it to `ALLOWED_GLUE_JOBS`."
            )
        run = _glue.start_job_run(JobName=name)
        return _slack_response(
            f":arrows_counterclockwise: Restarted Glue job `{name}` — "
            f"run id `{run['JobRunId']}` (triggered by <@{user_id}>).",
            ephemeral=False,
        )

    if kind == "sfn":
        # Allowlist lookups use the bare name; users may pass either a name or
        # a full ARN, so we peel the bare name off the ARN before checking.
        bare_name = name.split(":")[-1] if name.startswith("arn:") else name
        if not _allowed(bare_name, "ALLOWED_STATE_MACHINES"):
            return _slack_response(
                f":no_entry: State machine `{bare_name}` is not in the allowlist. "
                "Ask the platform team to add it to `ALLOWED_STATE_MACHINES`."
            )
        arn = _resolve_state_machine_arn(name, context)
        exec_resp = _sfn.start_execution(stateMachineArn=arn, input="{}")
        execution_name = exec_resp["executionArn"].split(":")[-1]
        return _slack_response(
            f":arrows_counterclockwise: Restarted state machine `{name}` — "
            f"execution `{execution_name}` (triggered by <@{user_id}>).",
            ephemeral=False,
        )

    return _slack_response(
        f":warning: Unknown target `{kind}`. Try `glue` or `sfn`."
    )


def _resolve_state_machine_arn(name: str, context: Any) -> str:
    """Accept either a bare name or a full ARN.

    When a bare name comes in we synthesize the ARN from the executing
    Lambda's own ARN, which encodes both the region and account.
    """
    if name.startswith("arn:"):
        return name
    region = os.environ["AWS_REGION"]
    # invoked_function_arn:  arn:aws:lambda:<region>:<account>:function:<name>
    account = context.invoked_function_arn.split(":")[4]
    return f"arn:aws:states:{region}:{account}:stateMachine:{name}"
