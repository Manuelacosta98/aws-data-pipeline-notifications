# Documentation

This folder is the long-form documentation for the project. The top-level [`README`](../README.md) covers value proposition and quick-start; everything below is meant to be read by someone modifying or operating the system.

## Reading order

If you're new to this codebase, read in this order:

1. **[Architecture](architecture.md)** — what the four stacks are and how they relate.
2. **[Outbound alerts](outbound-alerts.md)** — the AWS event → Slack flow, end to end.
3. **[Inbound actions](inbound-actions.md)** — the Slack `/pipeline rerun` flow.
4. **[Security](security.md)** — every guardrail, including the threat model.
5. **[CI/CD](cicd.md)** — how the OIDC deploy works.

For operators (deploying, rotating credentials, on-call):

- **[Operations](operations.md)** — runbook with concrete procedures.

For reviewers or interviewers:

- **[Patterns and practices](patterns-and-practices.md)** — catalog of architecture patterns and engineering practices used here.
- **[ADRs](adr/README.md)** — six decision records covering the major design choices.

For contributors:

- **[Testing strategy](testing-strategy.md)** — why tests are split between CDK synthesis and handler logic, with mocking patterns.

## All docs

| File                                                          | Purpose                                                                 |
|---------------------------------------------------------------|-------------------------------------------------------------------------|
| [architecture.md](architecture.md)                            | System overview, stacks, cross-stack contracts, deployment topology     |
| [outbound-alerts.md](outbound-alerts.md)                      | EventBridge → Lambda → SNS → Chatbot → Slack flow, end-to-end           |
| [inbound-actions.md](inbound-actions.md)                      | `/pipeline` slash-command setup and runtime semantics                   |
| [proactive-monitors.md](proactive-monitors.md)                | Hybrid push+pull pattern; Redshift + DMS pollers; QuickSight enrichment |
| [severity-classification.md](severity-classification.md)      | The four severity tiers and the dispatch pattern                        |
| [security.md](security.md)                                    | Threat model, HMAC, replay, IAM, allowlists, OIDC, secret rotation      |
| [cicd.md](cicd.md)                                            | GitHub OIDC role + CI workflow + deploy story                           |
| [testing-strategy.md](testing-strategy.md)                    | Test layering, mocking patterns, what each test guards                  |
| [operations.md](operations.md)                                | Runbook: deploy order, rotation, allowlist changes, debugging           |
| [patterns-and-practices.md](patterns-and-practices.md)        | Architecture patterns + good practices catalog                          |
| [adr/](adr/README.md)                                         | Architecture Decision Records (9 ADRs)                                  |

## Conventions

- **Diagrams** use Mermaid. They render natively on GitHub.
- **Code references** use the `path:line` convention (e.g. `infra/eventbridge_stack.py:42`) so they stay accurate even as files grow.
- **ADRs** follow [Michael Nygard's template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions): Context, Decision, Consequences. They are append-only — never edit a past decision; supersede it with a new ADR that references the old one.
- **English** throughout. The team is bilingual but this is a public portfolio repo.
