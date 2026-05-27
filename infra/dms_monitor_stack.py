"""Proactive DMS load-error monitor.

DMS Serverless does emit some EventBridge events (replication-task state
changes), but it doesn't expose per-table load error counts or
field-level ``]E:`` log entries that way. This stack provisions a Lambda
that combines two data sources:

1. ``DescribeReplicationTableStatistics`` — table-level row counts and
   error counts per table in the replication config.
2. ``CloudWatch Logs FilterLogEvents`` — field-level error lines (the
   ``]E:`` prefix that DMS uses for individual row failures).

It then emits a ``custom.dms`` EventBridge event that the
``EventBridgeStack`` formatter Lambda picks up via its ``DmsLogCheckRule``
and renders into a Slack alert.

Invokable on-demand from Slack via the Chatbot integration:
``@aws lambda invoke --function-name CheckDMSErrors``.
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
)
from constructs import Construct


class DmsMonitorStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        dms_task_arn: str,
        dms_log_group: str,
        dms_log_hours_back: str = "24",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not (dms_task_arn and dms_log_group):
            raise ValueError(
                "dms_task_arn and dms_log_group are required. Set "
                "DMS_TASK_ARN / DMS_LOG_GROUP env vars, or the matching "
                "CDK context."
            )

        # function_name is fixed so the Chatbot stack's IAM policy can grant
        # `lambda:InvokeFunction` on a predictable ARN.
        self.monitor = _lambda.Function(
            self,
            "DmsLogErrorMonitor",
            function_name="CheckDMSErrors",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="dms_monitor.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.minutes(5),
            memory_size=256,
            description=(
                "Proactively combines DMS table statistics + CloudWatch ]E: "
                "log scan and emits a custom.dms EventBridge event."
            ),
            environment={
                "DMS_TASK_ARN": dms_task_arn,
                "DMS_LOG_GROUP": dms_log_group,
                "DMS_LOG_HOURS_BACK": dms_log_hours_back,
            },
        )

        # DMS Serverless table statistics — scoped to the named replication
        # config ARN, not `*`.
        self.monitor.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["dms:DescribeReplicationTableStatistics"],
                resources=[dms_task_arn],
            )
        )

        # CloudWatch Logs read for the specific DMS log group, not `*`.
        self.monitor.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:FilterLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:{dms_log_group}",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:{dms_log_group}:*",
                ],
            )
        )

        # Emit custom events to the default EventBridge bus.
        self.monitor.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["events:PutEvents"],
                resources=[
                    f"arn:aws:events:{self.region}:{self.account}:event-bus/default"
                ],
            )
        )
