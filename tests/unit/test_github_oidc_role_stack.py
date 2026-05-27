"""Unit tests for the GitHub Actions OIDC deploy stack.

Guards the trust boundary: the role must be assumable only by the named
GitHub repository, via the official ``token.actions.githubusercontent.com``
audience, and the role's ARN must be exported as a CfnOutput for use as
the ``AWS_DEPLOY_ROLE_ARN`` GitHub Actions secret.
"""

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from infra.github_oidc_role_stack import GithubOIDCRoleStack


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App()
    stack = GithubOIDCRoleStack(
        app,
        "TestOIDC",
        github_org="Manuelacosta98",
        github_repo="aws-data-pipeline-notifications",
        env=cdk.Environment(account="111111111111", region="us-east-1"),
    )
    return assertions.Template.from_stack(stack)


def test_role_trusts_only_the_named_github_repository(template):
    template.has_resource_properties(
        "AWS::IAM::Role",
        assertions.Match.object_like(
            {
                "AssumeRolePolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Action": "sts:AssumeRoleWithWebIdentity",
                                        "Effect": "Allow",
                                        "Condition": assertions.Match.object_like(
                                            {
                                                "StringEquals": {
                                                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                                },
                                                "StringLike": {
                                                    "token.actions.githubusercontent.com:sub": "repo:Manuelacosta98/aws-data-pipeline-notifications:*",
                                                },
                                            }
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                )
            }
        ),
    )


def test_role_arn_is_exported_as_cfn_output(template):
    template.has_output("GitHubActionsRoleArn", {})


def test_role_can_assume_cdk_bootstrap_roles(template):
    """The role must be able to assume the standard CDK bootstrap roles."""
    template.has_resource_properties(
        "AWS::IAM::Policy",
        assertions.Match.object_like(
            {
                "PolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Action": "sts:AssumeRole",
                                        "Effect": "Allow",
                                    }
                                )
                            ]
                        )
                    }
                )
            }
        ),
    )


def test_missing_repo_raises():
    app = cdk.App()
    with pytest.raises(ValueError):
        GithubOIDCRoleStack(
            app,
            "BadOIDC",
            github_org="",
            github_repo="",
            env=cdk.Environment(account="111111111111", region="us-east-1"),
        )
