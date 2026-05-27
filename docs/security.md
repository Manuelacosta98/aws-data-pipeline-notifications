# Security

This document spells out every security guardrail the project relies on, the threat model behind each, and how to verify the guardrail is still in place.

## Threat model

The system has two security boundaries:

1. **Outbound boundary** — between the AWS account and Slack. The threat is data exfiltration via the alert messages (e.g. leaking PII into a Slack channel that's broader than intended). Mitigation is least-privilege IAM on the Chatbot role and careful authoring of alert content.
2. **Inbound boundary** — between Slack and the AWS account. The threats are unauthorized re-runs (someone who shouldn't be running production jobs triggers one) and replay attacks. Mitigations are HMAC signature verification, replay window, allowlists, and IAM scoping.

The project does not assume the Slack workspace itself is fully trusted — anyone who can post in the alert channel can also issue slash commands. Authorization is enforced *server-side* via the allowlist, not by trusting Slack's identity model.

## Guardrails

### 1. HMAC signature verification (inbound)

Every request to `/slack/commands` must include `X-Slack-Request-Timestamp` and `X-Slack-Signature` headers. The Lambda:

```
base       = "v0:" + timestamp + ":" + raw_body
digest     = HMAC-SHA256(signing_secret, base).hexdigest()
expected   = "v0=" + digest
```

The handler compares `expected` to the `X-Slack-Signature` header using `hmac.compare_digest` (constant-time, resistant to timing attacks). Mismatches return HTTP 401.

The signing secret lives in Secrets Manager and is fetched lazily into a 5-minute in-memory cache. A rotation in Secrets Manager is picked up automatically within 5 minutes — no redeploy.

**How to verify:** `tests/unit/test_slack_command_handler.py:test_invalid_signature_returns_401`.

### 2. Replay protection (inbound)

If `|now − timestamp| > 300` seconds, the request is rejected as a replay. Slack's recommended window. This means a captured request cannot be replayed against the endpoint more than 5 minutes after it was issued.

**How to verify:** `tests/unit/test_slack_command_handler.py:test_old_timestamp_is_rejected_as_replay` and `test_malformed_timestamp_is_rejected`.

### 3. Allowlists, enforced twice (defense in depth)

When the operator deploys `SlackActionsStack`, they pass two allowlists via CDK context:

```bash
-c allowedGlueJobs=customer_etl_daily,inventory_sync
-c allowedStateMachines=DataPipeline
```

These are enforced in **two** independent layers:

1. **At runtime in the Lambda handler.** Comma-separated env vars `ALLOWED_GLUE_JOBS` / `ALLOWED_STATE_MACHINES`. A name not in the list returns `:no_entry:` to Slack.
2. **In the IAM policy attached to the Lambda's role.** The `resources` array is hard-coded to the named ARNs:

   ```
   arn:aws:glue:us-east-1:111111111111:job/customer_etl_daily
   arn:aws:glue:us-east-1:111111111111:job/inventory_sync
   arn:aws:states:us-east-1:111111111111:stateMachine:DataPipeline
   ```

If a future code change skips the env-var check, the IAM policy still rejects the call with `AccessDenied`. If the IAM policy is widened by mistake, the env-var check still rejects with a Slack-readable message. **Both have to fail simultaneously** for an unauthorized re-run to succeed.

This is the "belt and suspenders" pattern — see [ADR-006](adr/006-iam-allowlist-defense-in-depth.md).

**How to verify:**
- `tests/unit/test_slack_command_handler.py:test_rerun_glue_rejects_unlisted_job` (env-var layer)
- `tests/unit/test_slack_actions_stack.py:test_iam_policy_scoped_to_named_glue_jobs` (IAM layer)

### 4. Least-privilege IAM on the Chatbot role (outbound)

The Chatbot role does **not** attach the AWS-managed `CloudWatchReadOnlyAccess` policy (which would grant CloudWatch read across the whole account). Instead, an inline policy lists only the actions Chatbot uses to enrich alert messages:

```
cloudwatch:Describe*, Get*, List*
logs:GetLogEvents, FilterLogEvents, DescribeLogGroups, DescribeLogStreams,
     DescribeMetricFilters, DescribeSubscriptionFilters,
     StartQuery, StopQuery, GetQueryResults
sns:Get*, List*
```

**How to verify:**
- `tests/unit/test_chatbot_stack.py:test_chatbot_role_uses_inline_least_privilege_policy`
- `tests/unit/test_chatbot_stack.py:test_chatbot_role_does_not_attach_managed_cloudwatch_readonly` (regression guard)

### 5. Audit logging (inbound)

Every slash command, accepted or rejected, is logged to CloudWatch with the Slack `user_id`. The successful re-run is also posted in-channel (not ephemeral) with a `<@user_id>` mention, so the team has both a CloudWatch trail *and* a Slack trail.

Sample log line:

```
Slack command from user_id=U01ABC23: 'rerun glue customer_etl_daily'
```

### 6. OIDC for CI deploys (no long-lived keys)

CI deploys use a GitHub OIDC role, not stored AWS access keys. The role's trust policy is scoped to a single repository:

```
"StringLike": {
  "token.actions.githubusercontent.com:sub":
    "repo:Manuelacosta98/aws-data-pipeline-notifications:*"
}
```

A workflow in a different repo cannot assume this role. The role's credentials are short-lived (an hour) and minted per-run.

**How to verify:** `tests/unit/test_github_oidc_role_stack.py:test_role_trusts_only_the_named_github_repository`.

To tighten further (e.g. only `main` branch can deploy), change the trust policy to:

```
"repo:Manuelacosta98/aws-data-pipeline-notifications:ref:refs/heads/main"
```

### 7. Secret management

- The Slack signing secret lives in AWS Secrets Manager and is fetched at runtime. It is never:
  - committed to source control,
  - passed as a CDK parameter (which would log it in CloudFormation parameter history),
  - or set as a Lambda environment variable.
- The Lambda's IAM role has `secretsmanager:GetSecretValue` only for that one secret ARN.

**How to rotate:** see [operations.md § Rotate the Slack signing secret](operations.md#rotate-the-slack-signing-secret).

### 8. Resource constraints

- The slash-command Lambda has a `Duration.seconds(10)` timeout. Any pathological input that causes runaway processing is bounded.
- The formatter Lambda has a `Duration.seconds(30)` timeout. Same rationale.
- API Gateway HTTP API has no client API key but enforces a default account-level throttle. For higher-traffic deployments, attach a usage plan.

## What the project does *not* protect against

Being honest about scope:

- **Slack workspace compromise.** If an attacker gains access to the Slack workspace and the alert channel, they can issue slash commands. Mitigation is the allowlist (they can only re-run jobs the operator pre-approved). If you need per-user authorization beyond that, consider Slack's `user_id` allowlist or a separate auth layer.
- **Compromise of the AWS account.** If the deploy role is compromised, an attacker can redeploy with widened allowlists. Mitigation is OIDC + short-lived creds + repo-scoped trust + branch protection on `main`.
- **Race conditions on the rotation cache.** During the 5-minute cache window, the old signing secret still validates. If you need instant rotation, redeploy the Lambda to flush the cache.

## Security review checklist

Before a release, walk through this:

- [ ] All inbound endpoints verify HMAC and reject old timestamps.
- [ ] The Chatbot IAM role uses inline policies, no managed `*ReadOnlyAccess` attached.
- [ ] The slash-command Lambda IAM policy is scoped to specific Glue jobs and state machines, not `*`.
- [ ] CI uses OIDC, not long-lived AWS keys, and the role trusts only the project repo.
- [ ] Secrets live in Secrets Manager; nothing sensitive is in `cdk.json`, env vars, or CFN parameters.
- [ ] All 46 tests pass (`uv run pytest`).
