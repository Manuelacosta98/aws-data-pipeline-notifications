from aws_cdk import (
    Stack,
    aws_chatbot as chatbot,
    aws_sns as sns,
    aws_iam as iam,
)
from constructs import Construct


class ChatBotStack(Stack):
    """AWS Chatbot Slack integration subscribed to the pipeline-failures SNS topic.

    The Chatbot role uses an explicit least-privilege inline policy with only
    the CloudWatch / Logs / SNS read actions Chatbot actually needs to render
    alert context in Slack. We intentionally do not attach the broader
    AWS-managed ``CloudWatchReadOnlyAccess`` policy.

    Optionally, the role can also be granted ``lambda:InvokeFunction`` on
    named Lambda ARNs, which lets users invoke them via Chatbot's native
    ``@aws lambda invoke --function-name <name>`` command from Slack. This
    is the simpler invocation path that complements the richer slash-command
    flow in ``SlackActionsStack`` — see ADR-008 for the trade-off.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        sns_topic: sns.Topic,
        slack_workspace_id: str,
        slack_channel_id: str,
        invokable_function_names: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        chatbot_role = iam.Role(
            self,
            "ChatBotRole",
            assumed_by=iam.ServicePrincipal("chatbot.amazonaws.com"),
            description=(
                "Role used by AWS Chatbot to read CloudWatch / Logs context "
                "and (optionally) invoke proactive monitor Lambdas from Slack."
            ),
        )

        chatbot_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudwatch:Describe*",
                    "cloudwatch:Get*",
                    "cloudwatch:List*",
                    "logs:GetLogEvents",
                    "logs:FilterLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:DescribeMetricFilters",
                    "logs:DescribeSubscriptionFilters",
                    "logs:StartQuery",
                    "logs:StopQuery",
                    "logs:GetQueryResults",
                    "sns:Get*",
                    "sns:List*",
                ],
                resources=["*"],
            )
        )

        # Optional: allow Chatbot users to invoke specific monitor Lambdas
        # via `@aws lambda invoke --function-name <name>` from Slack. Scoped
        # to the named ARNs only — not `*`.
        if invokable_function_names:
            chatbot_role.add_to_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["lambda:InvokeFunction"],
                    resources=[
                        f"arn:aws:lambda:{self.region}:{self.account}:function:{name}"
                        for name in invokable_function_names
                    ],
                )
            )

        chatbot.SlackChannelConfiguration(
            self,
            "SlackNotifications",
            slack_channel_configuration_name="DataPipelineNotifications",
            slack_workspace_id=slack_workspace_id,
            slack_channel_id=slack_channel_id,
            notification_topics=[sns_topic],
            role=chatbot_role,
        )
