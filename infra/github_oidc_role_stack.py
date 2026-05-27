"""GitHub Actions OIDC deploy role.

This stack provisions an IAM role that GitHub Actions can assume via OIDC,
scoped to a single repository. Deploy it once (locally or by an admin),
record the role ARN in the CfnOutput, and set it as the
``AWS_DEPLOY_ROLE_ARN`` GitHub Actions secret. After that, CI can call
``aws-actions/configure-aws-credentials`` without any long-lived access keys
stored in the repository.

The trust policy uses ``StringLike`` on ``sub`` so any branch / tag / PR
inside the named repo can assume the role. Tighten this to a single branch
(``repo:org/repo:ref:refs/heads/main``) if you want only main to be able
to deploy.

The OIDC provider for ``token.actions.githubusercontent.com`` is global per
AWS account — if your account already has one, set the existing ARN via the
``existingOidcProviderArn`` CDK context flag instead of letting this stack
create a new one.
"""

from aws_cdk import (
    Stack,
    CfnOutput,
    aws_iam as iam,
)
from constructs import Construct


class GithubOIDCRoleStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        github_org: str,
        github_repo: str,
        existing_oidc_provider_arn: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not github_org or not github_repo:
            raise ValueError(
                "github_org and github_repo are required. Pass them via the "
                "GITHUB_ORG / GITHUB_REPO env vars, or githubOrg / githubRepo "
                "CDK context."
            )

        if existing_oidc_provider_arn:
            oidc_provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
                self, "GitHubOIDCProvider", existing_oidc_provider_arn
            )
        else:
            oidc_provider = iam.OpenIdConnectProvider(
                self,
                "GitHubOIDCProvider",
                url="https://token.actions.githubusercontent.com",
                client_ids=["sts.amazonaws.com"],
            )

        role = iam.Role(
            self,
            "GitHubActionsRole",
            assumed_by=iam.WebIdentityPrincipal(
                oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_org}/{github_repo}:*"
                        ),
                    },
                },
            ),
            description=(
                f"GitHub Actions deploy role for {github_org}/{github_repo}. "
                "Trusts only this repository via OIDC; no long-lived access "
                "keys are required in CI."
            ),
        )

        # Read the CDK bootstrap version parameter so `cdk deploy` knows
        # which bootstrap stack is in place.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/cdk-bootstrap/hnb659fds/version"
                ],
            )
        )

        # CDK assets bucket (template + Lambda code uploads).
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                resources=[
                    "arn:aws:s3:::cdk-hnb659fds-assets-*",
                    "arn:aws:s3:::cdk-hnb659fds-assets-*/*",
                ],
            )
        )

        # Assume the standard CDK bootstrap roles to drive change-sets.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-deploy-role-{self.account}-{self.region}",
                    f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-cfn-exec-role-{self.account}-{self.region}",
                    f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-file-publishing-role-{self.account}-{self.region}",
                    f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-lookup-role-{self.account}-{self.region}",
                ],
            )
        )

        # CloudFormation change-set operations.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:ListStacks",
                    "cloudformation:GetTemplate",
                    "cloudformation:CreateStack",
                    "cloudformation:UpdateStack",
                    "cloudformation:CreateChangeSet",
                    "cloudformation:ExecuteChangeSet",
                    "cloudformation:DescribeChangeSet",
                    "cloudformation:ListChangeSets",
                    "cloudformation:DeleteChangeSet",
                    "cloudformation:DescribeStackEvents",
                ],
                resources=["*"],
            )
        )

        self.role_arn = role.role_arn
        CfnOutput(
            self,
            "GitHubActionsRoleArn",
            value=role.role_arn,
            description=(
                "Set this as the AWS_DEPLOY_ROLE_ARN secret in the GitHub "
                "repository so CI can assume the role via OIDC."
            ),
        )
