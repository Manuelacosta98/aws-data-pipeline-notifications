#!/usr/bin/env python3
import os

import aws_cdk as cdk

from infra.aws_data_pipeline_notifications_stack import AwsDataPipelineNotificationsStack
from infra.eventbridge_stack import EventBridgeStack
from infra.chatbot_stack import ChatBotStack

env=cdk.Environment(
    account=os.getenv('CDK_DEFAULT_ACCOUNT'),
    region=os.getenv('CDK_DEFAULT_REGION')
)

app = cdk.App()


event_bridge = EventBridgeStack(
    app,
    "EventBridgeStack", 
    env=env,
    description="EventBridge Stack for Data Pipeline Notifications"
)


ChatBotStack(
    app,
    "ChatBotStack",
    env=env,
    description="Chatbot Stack for Data Pipeline Notifications",
    sns_topic=event_bridge.sns_topic,
    slack_workspace_id=os.getenv('SLACK_WORKSPACE_ID'),
    slack_channel_id=os.getenv('SLACK_CHANNEL_ID')
)

app.synth()
