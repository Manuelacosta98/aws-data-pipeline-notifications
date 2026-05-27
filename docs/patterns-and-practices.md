# Patterns and practices

A catalog of the architecture patterns and engineering practices this project follows, with concrete pointers to where each one shows up in the code. Useful for code review, for interviewers, and for someone porting these patterns into another project.

---

## Architecture patterns

### 1. Event-driven over polling

AWS services emit native state-change events to the default EventBridge bus. We listen to those events rather than polling each service for status. Push beats poll on latency, cost, and reliability.

**Where:** `infra/eventbridge_stack.py` — every `events.Rule(...)` declaration.

**ADR:** [ADR-001](adr/001-event-driven-over-polling.md).

---

### 2. Producer–consumer decoupling via SNS

The formatter Lambda doesn't talk to Slack directly. It publishes to an SNS topic, and AWS Chatbot subscribes. Adding email or PagerDuty as additional consumers is one subscription per channel — no change to the producer.

**Where:** `infra/eventbridge_stack.py` (publisher) and `infra/chatbot_stack.py` (one of potentially many subscribers).

---

### 3. Single Responsibility Stacks

Four stacks, four concerns. Outbound, Chat binding, Inbound, and CI/CD bootstrap are each independently deployable. A failure of the bidirectional feature can't break alerting. A churn on the OIDC role doesn't redeploy the Lambda.

**Where:** `app.py` — each stack instantiation.

**ADR:** [ADR-004](adr/004-separate-stack-for-bidirectional-flow.md).

---

### 4. Strategy / dispatch over branching glue code

The formatter Lambda doesn't have a 50-line `if source == "aws.glue": elif source == "aws.dms": ...` chain. It has a `_dispatch(source, detail_type)` method that returns *which formatter method to call*, and the formatter methods are independent. New AWS sources are one method + one dispatch line.

**Where:** `lambda/event_formatter.py:EventFormatter._dispatch`.

**ADR:** [ADR-003](adr/003-class-based-event-formatter.md).

---

### 5. Bidirectional flow that closes the loop

The outbound alert contains the exact command needed to re-run the failed job. The inbound endpoint receives that command. The user never has to leave Slack.

**Where:**
- `lambda/event_formatter.py:_rerun_hint` builds the hint.
- `infra/eventbridge_stack.py` passes `RERUN_HINTS_ENABLED` so the hint only shows when the inbound endpoint exists.
- `lambda/slack_command_handler.py` consumes the hint.

---

### 6. Defense in depth on authorization

Slash command targets are checked **twice**: once at the application layer (env var allowlist in the Lambda) and once at the IAM layer (the role's `Resource` array). Either layer alone would suffice in the happy case; both together survive single-point regression.

**Where:**
- `lambda/slack_command_handler.py:_allowed` — application-layer check.
- `infra/slack_actions_stack.py` — IAM-layer check baked into `add_to_role_policy`.

**ADR:** [ADR-006](adr/006-iam-allowlist-defense-in-depth.md).

---

### 7. Signed, replay-protected webhook

Every inbound request is HMAC-SHA256 verified against a Slack signing secret, with a 5-minute timestamp window. Constant-time comparison via `hmac.compare_digest`. No request goes anywhere near boto3 unless the signature checks out.

**Where:** `lambda/slack_command_handler.py:_verify_signature`.

---

### 8. Secrets in Secrets Manager, lazy-loaded and cached

The Slack signing secret lives in Secrets Manager. The Lambda reads it lazily on first request, caches it for 5 minutes, and refreshes — so a rotation in Secrets Manager propagates automatically without a redeploy.

**Where:** `lambda/slack_command_handler.py:_get_signing_secret`.

---

### 9. Passwordless CI via GitHub OIDC

No long-lived AWS access keys in GitHub secrets. CI mints a short-lived OIDC JWT, exchanges it for AWS credentials via `sts:AssumeRoleWithWebIdentity`, and the IAM role's trust policy restricts the exchange to this exact repo.

**Where:** `infra/github_oidc_role_stack.py` and `.github/workflows/ci.yml`.

**ADR:** [ADR-005](adr/005-github-oidc-for-ci-deploys.md).

---

### 10. Opt-in feature flags via CDK context

The two costly features — success notifications and the bidirectional flow — are gated on CDK context flags (`notifyOnPipelineSuccess`, `enableSlackActions`), not hardcoded. The default install is the minimum useful surface; you opt in with `cdk synth -c flag=true`.

**Where:** `infra/eventbridge_stack.py` and `app.py`.

---

## Engineering practices

### 11. Least-privilege IAM, never `*ReadOnlyAccess`

The Chatbot role uses an inline policy listing the exact CloudWatch + Logs + SNS actions it needs. The AWS-managed `CloudWatchReadOnlyAccess` policy is explicitly **not** attached, with a regression test guarding it.

**Where:** `infra/chatbot_stack.py` and `tests/unit/test_chatbot_stack.py:test_chatbot_role_does_not_attach_managed_cloudwatch_readonly`.

---

### 12. Two-layer test pyramid: synth + handler

CDK synth tests catch infrastructure misconfigurations. Handler tests catch application bugs. Neither layer can substitute for the other. We run both in 4 seconds.

**Where:** `tests/unit/test_*_stack.py` vs. `tests/unit/test_*_handler.py` / `test_lambda_formatter.py`.

**Doc:** [testing-strategy.md](testing-strategy.md).

---

### 13. `uv` with frozen lockfile in CI

CI runs `uv sync --frozen --dev`. The build fails if `pyproject.toml` and `uv.lock` are out of sync. Reproducible builds with cold-cache cost under 4 seconds.

**Where:** `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`.

---

### 14. Tests that synthesize a stack, then assert on the template

The pattern `assertions.Template.from_stack(stack)` lets us assert that resources exist with specific properties, without deploying anything. We use `Match.object_like` and `Match.array_with` to be tolerant of CDK-generated noise around the assertions we care about.

**Where:** any `tests/unit/test_*_stack.py`.

---

### 15. Lambda handlers split from business logic

`lambda/lambda_formatter.py` is 13 lines: load environment, instantiate `EventFormatter`, publish to SNS. `lambda/event_formatter.py` is 130 lines of testable formatting logic with no I/O. Same split on the inbound side: `slack_command_handler.lambda_handler` is the entry point; the formatting and dispatch live alongside it but are testable in isolation.

This is a port of DataForge's `DMSServerlessManager` pattern.

---

### 16. ADRs for every non-obvious decision

Six ADRs in `docs/adr/`, each following Michael Nygard's Context/Decision/Consequences template. They explain *why* we chose Chatbot over a direct Slack webhook, *why* the bidirectional flow is a separate stack, *why* IAM and env-var allowlists both exist.

**Where:** [docs/adr/](adr/README.md).

---

### 17. Audit logging with the actor

Every slash command logs to CloudWatch with `user_id=<slack-user>`, and successful re-runs post in-channel with `<@user_id>` so the team has both an Ops audit trail (CloudWatch) and a social audit trail (Slack).

**Where:** `lambda/slack_command_handler.py:lambda_handler`.

---

### 18. The pipeline alerts on its own deploys

When CI deploys, it posts a Slack notification announcing success or failure of the deploy. The alerting system observes itself.

**Where:** `.github/workflows/ci.yml` — the `Slack notification — deploy succeeded/failed` steps.

---

### 19. Module-level boto3 clients for warm-reuse

`_sns = boto3.client("sns")` at module scope means every warm Lambda invocation reuses the same client and its underlying connection pool. Cold starts pay the construction cost once. This is the AWS Lambda boto3 idiom that beginners miss.

**Where:** `lambda/lambda_formatter.py` and `lambda/slack_command_handler.py`.

---

### 20. `conftest.py` mirrors the Lambda runtime

The repo-root `conftest.py` puts `lambda/` on `sys.path` and sets `AWS_REGION` defaults — exactly what the AWS Lambda runtime does. Tests exercise the same import surface as production.

**Where:** `conftest.py`.

---

## Anti-patterns we explicitly avoid

| Anti-pattern                                              | What we do instead                                                |
|-----------------------------------------------------------|-------------------------------------------------------------------|
| Long-lived AWS access keys in GitHub secrets              | GitHub OIDC + short-lived `sts:AssumeRoleWithWebIdentity` creds.  |
| AWS-managed `*ReadOnlyAccess` policies on service roles   | Inline policies listing only the actions needed.                  |
| `IAM Resource: "*"` because allowlisting is annoying      | Explicit ARN list scoped to allowlisted job/state-machine names.  |
| Procedural `if/elif source ==` chain in a Lambda handler  | Class-based dispatch with one method per source.                  |
| Polling AWS services for state                            | EventBridge rules listening to native state-change events.        |
| Secrets in CDK parameters or env files                    | Secrets Manager with `secretsmanager:GetSecretValue` IAM.         |
| One giant CDK stack with every resource                   | Four single-responsibility stacks, three of which are opt-in.     |
| Tests that only exercise one of (CDK synth, Lambda code)  | Two-layer test pyramid: both are first-class.                     |
| Hardcoded magic numbers and ARN templates                 | CDK context flags + env var injection.                            |
| `subprocess.run("aws ...")` from Lambda                   | `boto3` clients reused across warm invocations.                   |

## Where to look first when reviewing this project

For someone reviewing this for a portfolio: read the [ADRs](adr/README.md), then [security.md](security.md), then skim [architecture.md](architecture.md). That's about 20 minutes of reading and covers 90% of the engineering judgment.
