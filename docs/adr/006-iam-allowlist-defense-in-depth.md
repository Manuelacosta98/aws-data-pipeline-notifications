# ADR-006: IAM and env-var allowlists, defense in depth

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** When the inbound flow was implemented

## Context

The slash-command Lambda has the power to start arbitrary Glue jobs and Step Functions executions. We need to constrain *which* jobs and which state machines a Slack user can trigger.

There are two layers where the constraint can live:

1. **At the application layer**, as an env-var allowlist read by the Lambda handler. Easy to enforce in code, easy to update, gives a friendly Slack error message to the user when they hit a not-allowed target.
2. **At the IAM layer**, by listing specific resource ARNs in the Lambda role's policy. Enforced by AWS itself; doesn't depend on the application code being correct.

Either layer alone would work for the happy path. The question is whether to do both.

## Decision

We enforce the allowlist in **both** layers — application and IAM — and they are sourced from the same set of CDK context inputs (`allowedGlueJobs`, `allowedStateMachines`).

## Consequences

### Positive

- **Single-layer regression doesn't open a hole.** If a future code change accidentally drops the env-var check in `slack_command_handler.py`, the IAM policy still denies the call with `AccessDenied`. If the IAM policy is widened by mistake — for example, someone changes `Resource: [<specific-arns>]` to `Resource: "*"` — the env-var check still rejects the request and the user sees a Slack message saying so.
- **Good Slack UX.** The env-var check happens before the boto3 call, so a denied target gets a friendly `:no_entry: Job X is not in the allowlist` message instead of a stack trace from `botocore.exceptions.AccessDeniedException`.
- **AWS-enforced upper bound.** Even if Slack were compromised and the env-var check were somehow bypassed, the IAM policy is the boundary AWS actually enforces. A privilege escalation requires compromising both layers simultaneously.
- **Allowlists are the same input.** Both layers read from the same CDK context values, so they cannot drift. The IAM policy bakes the ARNs into the `Resource` array at synth time; the Lambda env var packs the same names as a comma-separated string. Adding a new job updates both simultaneously.

### Negative

- **Two layers means two places to look during incident response.** "Why was this rejected?" — could be the env var, could be IAM. The Slack error message hints at the env-var layer; CloudWatch logs would show the IAM denial.
- **Each new allowlist entry means a redeploy.** The IAM policy is part of the CloudFormation template, so widening the allowlist requires `cdk deploy SlackActionsStack`. This is not a downside in practice — re-runs aren't an emergency operation, and deploys are 30 seconds with CI.
- **Slightly more code.** Both layers need to read and parse the same allowlist input. The duplication is mostly in the CDK stack, where the same `allowed_glue_jobs` list is splatted into both the env var and the IAM `Resource` array.

### Trade-off summary

We accept marginal code duplication and the requirement of a redeploy to widen the allowlist in exchange for an authorization model that survives single-point regression in either the application or the IAM. For a system whose primary safety property is "Slack users can only re-run jobs the operator pre-approved," this is the right cost.

## Alternatives considered

- **Env-var only, IAM wildcards.** Rejected — the env var is now the only thing standing between a code regression and arbitrary `glue:StartJobRun` access.
- **IAM only, no env-var check.** Rejected — the user-facing error would be a botocore exception bubbling into a Slack message, which is bad UX and leaks AWS internals.
- **Use AWS Organizations Service Control Policies to constrain Glue jobs across the account.** Considered, but at a different layer — SCPs are account-wide and would block legitimate non-Slack invocations of the same jobs. The right tool for "this Lambda can only call these jobs," not "this account can only run these jobs."
- **Use ABAC tags.** Tag the allowlisted Glue jobs and state machines with a custom tag, then write an IAM condition that requires the tag to match. Considered — would work — but it adds complexity (tag management) without solving a problem we have today. The ARN-list pattern is simpler.

## Verification

Two tests, one per layer:

- **Env-var layer:** `tests/unit/test_slack_command_handler.py:test_rerun_glue_rejects_unlisted_job`.
- **IAM layer:** `tests/unit/test_slack_actions_stack.py:test_iam_policy_scoped_to_named_glue_jobs`.

If either test breaks, the authorization model is degraded.

## Related

- [security.md § Allowlists, enforced twice](../security.md#3-allowlists-enforced-twice-defense-in-depth).
- [inbound-actions.md](../inbound-actions.md).
