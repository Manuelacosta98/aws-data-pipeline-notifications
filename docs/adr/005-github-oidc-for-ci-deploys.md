# ADR-005: GitHub OIDC for CI deploys, no long-lived keys

- **Status:** Accepted
- **Deciders:** Manuel Acosta
- **Context date:** CI setup phase

## Context

The default tutorial path for "deploy CDK from GitHub Actions" is to store `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as GitHub repository secrets, then have the workflow load them into the environment. This works, but:

- The credentials are **long-lived**. They have no automatic expiry; rotating them is a manual operation an engineer has to remember.
- A leak via a stolen developer laptop, a misconfigured log, a malicious dependency, or a misclick in GitHub UI exposes them.
- They are **scoped per-IAM-user**, not per-context. A compromise gives the attacker the full power of whatever IAM policy is attached to that user, with no way to differentiate "deploys from main" from "deploys from a malicious fork."

GitHub Actions has native OIDC support: every workflow run can mint a short-lived JSON Web Token with a `sub` claim that encodes the repository, branch, and workflow context. AWS can be configured to trust GitHub's OIDC provider via an IAM role with `sts:AssumeRoleWithWebIdentity` and a trust policy that constrains *who* can assume the role.

## Decision

We use GitHub OIDC. The repo provisions a `GithubOIDCRoleStack` (CDK) that creates the OIDC provider in AWS IAM and a deploy role whose trust policy is scoped to this exact repo. CI uses `aws-actions/configure-aws-credentials@v4` to exchange the OIDC token for short-lived AWS credentials. No long-lived AWS keys are stored anywhere in GitHub.

## Consequences

### Positive

- **No long-lived secrets in GitHub.** The only thing in GitHub Actions secrets is the *role ARN* to assume, which is not itself sensitive (knowing the ARN doesn't grant the ability to assume it; the trust policy on the AWS side is the boundary).
- **Per-run credentials.** Each workflow run gets a fresh credential set, scoped to that run, valid for an hour. A leak gives the attacker at most a one-hour window.
- **Repo-scoped trust.** The trust policy uses `StringLike` on the `sub` claim to constrain "only this repo can assume this role." A workflow in a different repo cannot assume the role, even with the same OIDC provider.
- **Branch-scoped trust if desired.** Tightening the `sub` constraint from `repo:org/repo:*` to `repo:org/repo:ref:refs/heads/main` restricts deploys to the `main` branch only.
- **Operational simplicity.** No IAM user lifecycle to manage. No rotation calendar. No "did someone leave the team and we need to rotate keys?" question.

### Negative

- **One-time bootstrap is manual.** The OIDC role stack itself can't be deployed by CI (circular dependency — CI would need the role to deploy the role). The operator deploys it once from a workstation.
- **Slightly more complex IAM mental model.** Engineers used to "GitHub secret → AWS credential" need to learn the OIDC handshake. The model is worth the cost but it's a learning curve.
- **OIDC provider is account-global.** If the AWS account already has a GitHub OIDC provider (e.g. from another project), CDK can't create a second one. The `GithubOIDCRoleStack` accepts an `existing_oidc_provider_arn` context flag to reuse the existing provider, which adds a minor branch in the stack code.

### Trade-off summary

We accept a one-time manual bootstrap and a slightly less familiar IAM pattern in exchange for never having long-lived AWS keys in GitHub. For a public portfolio project, this is an unambiguous win — it's also the modern industry-default pattern, not an exotic optimization.

## Alternatives considered

- **Long-lived IAM user credentials.** The default tutorial path. Rejected because of the rotation overhead and the leak risk.
- **SAML federation via GitHub Enterprise.** Available, but requires GitHub Enterprise, which we don't have.
- **A self-hosted runner inside the AWS account.** Avoids the OIDC handshake but introduces a runner to manage. Rejected for a portfolio project.

## Verification

`tests/unit/test_github_oidc_role_stack.py` pins the trust policy. Four tests:

- `test_role_trusts_only_the_named_github_repository`
- `test_role_arn_is_exported_as_cfn_output`
- `test_role_can_assume_cdk_bootstrap_roles`
- `test_missing_repo_raises`

## Related

- [cicd.md](../cicd.md).
- [security.md § OIDC for CI deploys](../security.md#6-oidc-for-ci-deploys-no-long-lived-keys).
