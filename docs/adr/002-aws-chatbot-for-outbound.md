# ADR-002: AWS Chatbot for outbound Slack delivery

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** Initial design

## Context

We need to get an SNS message into a Slack channel. There are two well-supported paths:

1. **AWS Chatbot.** AWS subscribes Chatbot to an SNS topic, the operator authorizes the Slack workspace once in the AWS console, and Chatbot handles the OAuth flow + message rendering.
2. **Direct Slack Incoming Webhook.** The Lambda formats a Block Kit payload and POSTs to a per-channel webhook URL, no AWS Chatbot involved.

Both work. They differ on operational ergonomics, feature support, and what's available in the resulting Slack message.

## Decision

We use AWS Chatbot for the outbound flow, and accept the limitations of its custom-format payload.

## Consequences

### Positive

- **Zero secrets in code.** Chatbot handles the Slack OAuth and stores the workspace token itself. We don't need to provision or rotate a webhook URL.
- **First-class CDK support.** `chatbot.SlackChannelConfiguration` is an L2 construct; subscribing it to an SNS topic is one line.
- **Built-in channel guardrails.** Chatbot supports per-channel IAM policies that constrain what AWS commands can be invoked from the channel; we don't use this today but it's available without changing architecture.
- **Multiple channels for free.** Adding a second Slack channel is a new `SlackChannelConfiguration` subscribed to the same SNS topic — no formatter changes.

### Negative

- **No colored attachment bars.** Chatbot's custom format does not expose Slack's color attribute. We convey severity through an emoji prefix on the title and a `keywords` tag, but a glance at a busy channel doesn't show a row of red/yellow/green bars the way a direct webhook would.
- **No interactive buttons.** Chatbot supports URL-link buttons (which open a tab to a console URL), but not interactive Block Kit components that POST back to an endpoint. This is the main reason the bidirectional flow uses a separate slash-command path rather than buttons on the alert itself.
- **Limited control over the rendered message.** Chatbot transforms the SNS message through its own rendering pipeline; we don't get pixel-perfect control over how the Slack message looks.
- **One-time manual setup.** Authorizing Chatbot for a Slack workspace requires an operator to do an OAuth flow in the AWS console, which can't be fully automated in CDK.

### Trade-off summary

We trade interactive UI and color bars for zero secret management and CDK-native deployment. For a project whose primary signal is "this job failed, click here to see logs," that trade is the right one. If interactive alerts become a requirement later — e.g. an inline "Re-run" button on the alert — the path is to add a *parallel* direct-webhook publisher in the formatter Lambda for the actionable messages, while keeping Chatbot for the rest.

## Alternatives considered

- **Direct Slack Incoming Webhook only.** Would give us colored attachment bars and interactive buttons. Rejected for the outbound flow because the secrets-management overhead (one webhook per channel, rotated manually) outweighed the visual benefit. We *do* use a direct webhook for the CI self-deploy notifications, where it's appropriate.
- **Microsoft Teams via Chatbot.** Same approach, different channel type. Available if needed.

## Related

- [ADR-004](004-separate-stack-for-bidirectional-flow.md) — explains why the inbound flow is a separate stack rather than a button on the Chatbot alert.
- [outbound-alerts.md § Limitations](../outbound-alerts.md#limitations).
