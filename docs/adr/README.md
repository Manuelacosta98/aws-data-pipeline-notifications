# Architecture Decision Records

This folder holds the project's ADRs. Each one captures a non-obvious decision: the **context** at the time it was made, the **decision** itself, and the **consequences** — including the ones that hurt.

The format is [Michael Nygard's template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions): brief, opinionated, append-only. We never edit a past ADR; if a decision is reversed, a new ADR supersedes it and references the old.

## Index

| #     | Status   | Title                                                            |
|-------|----------|------------------------------------------------------------------|
| [001](001-event-driven-over-polling.md) | Accepted | Event-driven over polling for AWS state changes        |
| [002](002-aws-chatbot-for-outbound.md)  | Accepted | AWS Chatbot for outbound Slack delivery                |
| [003](003-class-based-event-formatter.md) | Accepted | Class-based EventFormatter with dispatch table        |
| [004](004-separate-stack-for-bidirectional-flow.md) | Accepted | Separate stack for the bidirectional flow |
| [005](005-github-oidc-for-ci-deploys.md) | Accepted | GitHub OIDC for CI deploys, no long-lived keys        |
| [006](006-iam-allowlist-defense-in-depth.md) | Accepted | IAM and env-var allowlists, defense in depth      |
| [007](007-hybrid-push-pull-monitoring.md) | Accepted | Hybrid push + pull architecture for non-native error sources |
| [008](008-chatbot-invocation-alongside-slash-commands.md) | Accepted | AWS Chatbot Lambda-invocation alongside slash commands |
| [009](009-active-enrichment-via-boto3.md) | Accepted | Active enrichment via boto3 inside the formatter      |

## When to write an ADR

Write one when:

- You chose between two reasonable technologies (Kafka vs SQS, Chatbot vs raw webhook).
- You introduced a security boundary or an explicit trade-off (e.g. opt-in vs default-on for a noisy feature).
- You made a structural choice that future contributors would otherwise have to reverse-engineer (one stack vs many, class-based vs procedural).

Don't write one for routine implementation choices — variable names, file layout, library upgrades. ADRs are for decisions whose alternatives are reasonable but rejected.
