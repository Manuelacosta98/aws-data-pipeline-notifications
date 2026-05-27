"""Unit tests for the Chatbot stack.

The Chatbot stack consumes an SNS topic from the EventBridge stack and
publishes alerts into a Slack channel via AWS Chatbot. These tests assert
the Slack channel configuration, the IAM trust policy, and the inline
least-privilege policy on the Chatbot role.
"""

import json

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from infra.eventbridge_stack import EventBridgeStack
from infra.chatbot_stack import ChatBotStack

# `cdk` is imported above; alias for the new fixture using a fresh stack pair.


@pytest.fixture(scope="module")
def chatbot_template() -> assertions.Template:
    app = cdk.App()
    eb = EventBridgeStack(app, "TestEventBridgeStack")
    cb = ChatBotStack(
        app,
        "TestChatBotStack",
        sns_topic=eb.sns_topic,
        slack_workspace_id="T00000000",
        slack_channel_id="C00000000",
    )
    return assertions.Template.from_stack(cb)


def test_chatbot_slack_channel_configuration_is_created(chatbot_template):
    chatbot_template.has_resource_properties(
        "AWS::Chatbot::SlackChannelConfiguration",
        {
            "ConfigurationName": "DataPipelineNotifications",
            "SlackWorkspaceId": "T00000000",
            "SlackChannelId": "C00000000",
        },
    )


def test_chatbot_iam_role_assumed_by_chatbot_service(chatbot_template):
    chatbot_template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Statement": [
                    {
                        "Action": "sts:AssumeRole",
                        "Effect": "Allow",
                        "Principal": {"Service": "chatbot.amazonaws.com"},
                    }
                ],
                "Version": "2012-10-17",
            },
        },
    )


def test_chatbot_role_uses_inline_least_privilege_policy(chatbot_template):
    """The role should carry an explicit inline policy with scoped read actions."""
    chatbot_template.has_resource_properties(
        "AWS::IAM::Policy",
        assertions.Match.object_like(
            {
                "PolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Effect": "Allow",
                                        "Action": assertions.Match.array_with(
                                            [
                                                "logs:GetLogEvents",
                                                "logs:FilterLogEvents",
                                                "logs:DescribeLogGroups",
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


def test_chatbot_role_does_not_attach_managed_cloudwatch_readonly(chatbot_template):
    """Regression guard: the broad managed policy should not come back."""
    template_dict = chatbot_template.to_json()
    roles = [
        r
        for r in template_dict.get("Resources", {}).values()
        if r["Type"] == "AWS::IAM::Role"
    ]
    for role in roles:
        managed_arns = role.get("Properties", {}).get("ManagedPolicyArns", [])
        # arn entries may be plain strings or CloudFormation Fn::Join intrinsics.
        flat = json.dumps(managed_arns)
        assert "CloudWatchReadOnlyAccess" not in flat, (
            "ChatBot role should not attach the broad AWS-managed "
            "CloudWatchReadOnlyAccess policy."
        )


# ---------------------------------------------------------------------
# Optional `lambda:InvokeFunction` grant — Chatbot @aws-invocation path.
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def chatbot_template_with_invocation() -> assertions.Template:
    """Stack built with invokable_function_names populated."""
    app = cdk.App()
    eb = EventBridgeStack(app, "TestEB2")
    cb = ChatBotStack(
        app,
        "TestCB2",
        sns_topic=eb.sns_topic,
        slack_workspace_id="T00000000",
        slack_channel_id="C00000000",
        invokable_function_names=["CheckRedshiftErrors", "CheckDMSErrors"],
        env=cdk.Environment(account="111111111111", region="us-east-1"),
    )
    return assertions.Template.from_stack(cb)


def test_chatbot_role_grants_lambda_invoke_when_function_names_provided(
    chatbot_template_with_invocation,
):
    chatbot_template_with_invocation.has_resource_properties(
        "AWS::IAM::Policy",
        assertions.Match.object_like(
            {
                "PolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Effect": "Allow",
                                        "Action": "lambda:InvokeFunction",
                                        "Resource": assertions.Match.array_with(
                                            [
                                                "arn:aws:lambda:us-east-1:111111111111:function:CheckRedshiftErrors",
                                                "arn:aws:lambda:us-east-1:111111111111:function:CheckDMSErrors",
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


def test_chatbot_role_does_not_grant_lambda_invoke_by_default(chatbot_template):
    """Without invokable_function_names, no lambda:InvokeFunction statement should exist."""
    template_dict = chatbot_template.to_json()
    for resource in template_dict.get("Resources", {}).values():
        if resource["Type"] != "AWS::IAM::Policy":
            continue
        statements = (
            resource.get("Properties", {})
            .get("PolicyDocument", {})
            .get("Statement", [])
        )
        for stmt in statements:
            action = stmt.get("Action")
            # Action may be a string or a list
            actions = [action] if isinstance(action, str) else (action or [])
            assert "lambda:InvokeFunction" not in actions, (
                "Default ChatBot policy must not grant lambda:InvokeFunction; "
                "it should only appear when invokable_function_names is set."
            )
