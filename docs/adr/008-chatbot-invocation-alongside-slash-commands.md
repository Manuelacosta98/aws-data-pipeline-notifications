# ADR-008: AWS Chatbot Lambda-invocation alongside slash commands

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** When the proactive monitors were added

## Context

Once the proactive Redshift and DMS monitors existed (see [ADR-007](007-hybrid-push-pull-monitoring.md)), users needed a way to **trigger them on demand from Slack** — "check Redshift right now and tell me what's broken." There were two viable patterns to enable this:

1. **AWS Chatbot's native `@aws lambda invoke` command.** The Chatbot IAM role can be granted `lambda:InvokeFunction` on specific Lambda ARNs. Users in the channel type:

   ```
   @aws lambda invoke --function-name CheckRedshiftErrors
   ```

   No new infrastructure. No new secrets. Standard AWS CLI syntax. Limited to direct AWS API invocation; no friendly grammar.

2. **Extending our slash-command stack** (`SlackActionsStack`) with new verbs:

   ```
   /pipeline check redshift
   /pipeline check dms
   ```

   New handler logic. Reuses the existing HMAC verification and signing-secret infrastructure. Friendlier UX, per-target allowlist, in-channel user mentions. More code to maintain.

A common production pattern in data-platform alerting is to ship **both** invocation paths — `@aws lambda invoke` as the lightweight diagnostic path, and a dedicated slash-command app for action verbs that need allowlists and friendlier UX. They serve different jobs and the cost of running both is small.

## Decision

We add the **Chatbot `lambda:InvokeFunction` pattern** for invoking the proactive monitor Lambdas, in addition to the existing slash-command infrastructure. We do **not** extend the slash-command grammar with `check` verbs at this time.

The `ChatBotStack` constructor accepts an optional `invokable_function_names` list. When non-empty, the Chatbot IAM role gets an inline `lambda:InvokeFunction` policy scoped to those specific function ARNs. The list is populated at app-synthesis time based on which monitor stacks are deployed.

## Consequences

### Positive

- **Zero new infrastructure** for the invocation path. Chatbot is already there for outbound alerts. The Lambdas are already there from the monitor stacks. The only change is ~10 lines of IAM in `chatbot_stack.py`.
- **No new secrets.** The existing Chatbot workspace OAuth is the auth. No signing-secret rotation.
- **Operationally simple.** "Type `@aws lambda invoke --function-name X` and the result arrives via the outbound flow" is one sentence in a runbook.
- **Scoped IAM.** The grant is to specific function ARNs, not `*`. Adding a new invokable Lambda is an explicit decision in `app.py`.
- **Complementary, not competing.** The two patterns serve different jobs. Slash commands stay the action interface (`/pipeline rerun glue X` with allowlist + friendly errors); Chatbot is the diagnostic interface (`@aws lambda invoke` for read-style operations).
- **Audit via CloudTrail.** Every Chatbot-driven Lambda invocation is logged in CloudTrail with the Chatbot identity, complementing CloudWatch Logs from the Lambdas themselves.

### Negative

- **UX gap between paths.** A user who wants to run a check has to remember which syntax goes with which Lambda. The two flavors of "do something from Slack" can be confusing.
- **No friendly grammar for the Chatbot path.** Users must know the actual Lambda function name (`CheckRedshiftErrors`) and use AWS CLI syntax. This is fine for engineers; harder for analysts.
- **Channel-wide authorization.** Anyone in the Slack channel where Chatbot is configured can invoke the named Lambdas. There is no per-user check — only the channel-level role. This is true for `@aws ...` commands in general.
- **No structured response.** Chatbot renders the Lambda's response payload as plain text. The actual alert formatting happens via the outbound flow (the Lambda emits an EventBridge event that flows through the formatter), which can take a few seconds.

### Trade-off summary

For diagnostic Lambdas (read-style, no destructive action), Chatbot's pattern is dramatically simpler and entirely sufficient. For action Lambdas (re-running a job, with allowlist semantics and user attribution), the slash-command pattern is worth its added infrastructure. We accept the slight UX gap of having two invocation paths because each is appropriate for its job, and synthesizing them prematurely would force us to compromise on either security (slash commands) or operational simplicity (Chatbot).

## Alternatives considered

- **Slash commands only.** Replace the Chatbot invocation path with `/pipeline check redshift` etc. Rejected — would add ~60 lines of handler code and 4 tests to invoke a Lambda that AWS Chatbot can already invoke for free with no extra infrastructure.
- **Chatbot for everything.** Replace the slash commands with `@aws ...` syntax for re-runs too: `@aws glue start-job-run --job-name customer_etl_daily`. Rejected — loses the per-job allowlist with friendly Slack errors and the `<@user_id>` mention in successful re-run announcements. The UX downgrade is significant for the action use case.
- **Slack interactive buttons on alerts.** AWS Chatbot supports URL-link buttons but not interactive POST-back buttons; would require bypassing Chatbot and posting Block Kit messages directly to a Slack webhook. Bigger architectural shift; deferred.

## Verification

- **Inline policy granted only when names are provided:** `tests/unit/test_chatbot_stack.py:test_chatbot_role_grants_lambda_invoke_when_function_names_provided`.
- **Regression guard against the default-on case:** `tests/unit/test_chatbot_stack.py:test_chatbot_role_does_not_grant_lambda_invoke_by_default`.

## Related

- [ADR-007](007-hybrid-push-pull-monitoring.md) — the proactive monitors this pattern invokes.
- [inbound-actions.md](../inbound-actions.md) — the slash-command path, for comparison.
- [proactive-monitors.md § Invoke paths](../proactive-monitors.md#invoke-paths).
