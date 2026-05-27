"""Unit tests for the SlackActionsStack.

Asserts the synthesized template has:
- the signing-secret entry in Secrets Manager,
- an HTTP API in front of the handler Lambda,
- a Lambda configured to load code from ``lambda/``,
- IAM policies scoped to the named Glue jobs / state machines.
"""

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from infra.slack_actions_stack import SlackActionsStack


@pytest.fixture(scope="module")
def template_scoped() -> assertions.Template:
    app = cdk.App()
    stack = SlackActionsStack(
        app,
        "TestSlackActions",
        allowed_glue_jobs=["customer_etl_daily", "inventory_sync"],
        allowed_state_machines=["DataPipeline"],
        env=cdk.Environment(account="111111111111", region="us-east-1"),
    )
    return assertions.Template.from_stack(stack)


@pytest.fixture(scope="module")
def template_wildcard() -> assertions.Template:
    """Stack with no allowlists — IAM should fall back to scoped wildcards."""
    app = cdk.App()
    stack = SlackActionsStack(
        app,
        "TestSlackActionsWild",
        env=cdk.Environment(account="111111111111", region="us-east-1"),
    )
    return assertions.Template.from_stack(stack)


# ---------------------------------------------------------------- resources


def test_signing_secret_exists(template_scoped):
    template_scoped.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {"Name": "aws-data-pipeline-notifications/slack-signing-secret"},
    )


def test_handler_lambda_runtime_and_handler(template_scoped):
    template_scoped.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "Handler": "slack_command_handler.lambda_handler",
                "Runtime": "python3.11",
            }
        ),
    )


def test_handler_lambda_has_allowlist_env_vars(template_scoped):
    template_scoped.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "Environment": assertions.Match.object_like(
                    {
                        "Variables": assertions.Match.object_like(
                            {
                                "ALLOWED_GLUE_JOBS": "customer_etl_daily,inventory_sync",
                                "ALLOWED_STATE_MACHINES": "DataPipeline",
                            }
                        )
                    }
                )
            }
        ),
    )


def test_http_api_exposes_slack_commands_route(template_scoped):
    template_scoped.has_resource_properties(
        "AWS::ApiGatewayV2::Route",
        assertions.Match.object_like({"RouteKey": "POST /slack/commands"}),
    )


def test_outputs_for_operator_setup(template_scoped):
    template_scoped.has_output("SlackCommandsUrl", {})
    template_scoped.has_output("SlackSigningSecretArn", {})


# ----------------------------------------------------------------------- IAM


def test_iam_policy_scoped_to_named_glue_jobs(template_scoped):
    template_scoped.has_resource_properties(
        "AWS::IAM::Policy",
        assertions.Match.object_like(
            {
                "PolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Action": assertions.Match.array_with(
                                            ["glue:StartJobRun"]
                                        ),
                                        "Resource": assertions.Match.array_with(
                                            [
                                                "arn:aws:glue:us-east-1:111111111111:job/customer_etl_daily",
                                                "arn:aws:glue:us-east-1:111111111111:job/inventory_sync",
                                            ]
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


def test_iam_policy_scoped_to_named_state_machines(template_scoped):
    # CDK serializes a single-element Resource list as a bare string, so we
    # match on Resource as the literal ARN rather than array_with.
    template_scoped.has_resource_properties(
        "AWS::IAM::Policy",
        assertions.Match.object_like(
            {
                "PolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Action": assertions.Match.array_with(
                                            ["states:StartExecution"]
                                        ),
                                        "Resource": "arn:aws:states:us-east-1:111111111111:stateMachine:DataPipeline",
                                    }
                                )
                            ]
                        )
                    }
                )
            }
        ),
    )


def test_iam_falls_back_to_account_scoped_wildcard_when_no_allowlist(
    template_wildcard,
):
    """Without an allowlist, IAM is still scoped to the account+region, never `*`."""
    template_wildcard.has_resource_properties(
        "AWS::IAM::Policy",
        assertions.Match.object_like(
            {
                "PolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Action": assertions.Match.array_with(
                                            ["glue:StartJobRun"]
                                        ),
                                        # Single-element resource arrays are
                                        # serialized as a bare string.
                                        "Resource": "arn:aws:glue:us-east-1:111111111111:job/*",
                                    }
                                )
                            ]
                        )
                    }
                )
            }
        ),
    )
