import os
from aws_cdk import (
    Stack,
    aws_chatbot as chatbot,
    aws_sns as sns,
    aws_iam as iam,
)
from constructs import Construct

class ChatBotStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, sns_topic: sns.Topic, slack_workspace_id: str, slack_channel_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # IAM role for Chatbot
        chatbot_role = iam.Role(self, "ChatBotRole",
            assumed_by=iam.ServicePrincipal("chatbot.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchReadOnlyAccess")
            ]
        )

        # Slack configuration for AWS Chatbot
        chatbot.SlackChannelConfiguration(self, "SlackNotifications",
            slack_channel_configuration_name="DataPipelineNotifications",
            slack_workspace_id=slack_workspace_id,
            slack_channel_id=slack_channel_id,
            notification_topics=[sns_topic],
            role=chatbot_role
        )
