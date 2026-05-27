# ADR-004: Separate stack for the bidirectional flow

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** When the inbound flow was added

## Context

When we added the inbound flow — `/pipeline rerun glue <job>` — we had two structural options:

1. **Single stack.** Add the API Gateway, the slash-command Lambda, the Secrets Manager entry, and the new IAM scopes to `EventBridgeStack`. One stack, one deploy.
2. **Separate stack.** Put the new resources in a new `SlackActionsStack` that depends on nothing in the alerting flow. Deploy independently.

The single-stack option is fewer files. The separate-stack option is more surface area but cleaner isolation.

## Decision

We use a separate `SlackActionsStack`. It's opt-in via the `enableSlackActions` CDK context flag, with the existing `EventBridgeStack` and `ChatBotStack` continuing to deploy independently.

## Consequences

### Positive

- **Failure of the inbound flow can't break alerting.** If a Slack-app misconfiguration or a CDK-side bug breaks `SlackActionsStack`, the outbound EventBridge → Chatbot → Slack flow keeps working. The two systems share no runtime dependency.
- **Independent deployment cadence.** Iterating on slash-command handler logic doesn't trigger a redeploy of the formatter Lambda or the SNS topic. CDK's no-op detection means most diffs touch only the stack you're working on.
- **Opt-in is honest.** A user who only wants alerts can `cdk deploy EventBridgeStack ChatBotStack` and never provision the API Gateway. The opt-in flag is at the CDK app level (`enableSlackActions`), so the operator doesn't even need to know the inbound stack exists.
- **Independent IAM blast radius.** The slash-command Lambda needs `glue:StartJobRun` and `states:StartExecution` — both of which are *write* permissions. Keeping that role in its own stack means a misconfiguration of the alerting IAM can't accidentally grant Chatbot the ability to start jobs.
- **Independent CI deploy.** The CI workflow only adds `SlackActionsStack` to the deploy list when `vars.ENABLE_SLACK_ACTIONS=true` is set on the repo. Users who clone the repo without the bidirectional flow get a deploy that doesn't try to provision an API Gateway.

### Negative

- **More files, more stacks.** The project grew from two CDK stacks (`EventBridgeStack`, `ChatBotStack`) to four. There's more to navigate.
- **The re-run hint coupling crosses stack boundaries.** The hint is rendered by the formatter Lambda in `EventBridgeStack`, but the slash command it points to is implemented in `SlackActionsStack`. We control the coupling with the `RERUN_HINTS_ENABLED` env var that `EventBridgeStack` sets only when `enableSlackActions` is true — but it does mean enabling the bidirectional flow touches *two* stacks.
- **Slightly more boilerplate.** Each stack has its own constructor signature, its own test file, its own IAM policies. A single-stack design would amortize some of that.

### Trade-off summary

We accept more files and slightly more coupling in exchange for an independent blast radius and an honest opt-in surface. For a system whose value comes from being reliable, isolation is worth more than concision.

## Alternatives considered

- **Cram everything into `EventBridgeStack`.** Rejected — the IAM widening alone made this uncomfortable, and the test file would grow to cover both inbound HMAC logic and outbound formatting.
- **Three stacks: alerting, chat-binding, actions.** This is what we have. The OIDC role stack is a fourth, but it's bootstrap infra, not part of the runtime topology.
- **One stack but with feature flags inside each construct.** Rejected — the resulting code would be a maze of `if rerun_hints_enabled: ... else: ...`, and a partial deploy could leave half-configured resources around.

## Related

- [architecture.md § Four stacks, four concerns](../architecture.md#four-stacks-four-concerns).
- [inbound-actions.md](../inbound-actions.md).
