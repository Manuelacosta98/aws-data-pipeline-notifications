"""Proactive Redshift load-error monitor.

AWS does not emit EventBridge events for Redshift COPY load errors (which
live in the ``stl_load_errors`` system table). This stack provisions a
Lambda that queries that table via the Redshift Data API and emits a
``custom.redshift`` EventBridge event that flows through the same
``EventBridgeStack`` formatter as native AWS sources.

Two invocation modes:
- Scheduled (cron) — the Lambda runs on a fixed cadence (not configured here;
  add an ``aws_events.Rule`` with a ``Schedule.cron(...)`` source if desired).
- On-demand from Slack — the Chatbot integration grants
  ``lambda:InvokeFunction`` on this Lambda's ARN, so users can run
  ``@aws lambda invoke --function-name CheckRedshiftErrors`` from Slack.

The Redshift Data API is used instead of a psycopg2/SQLAlchemy driver
because it has no Lambda layer requirement, no connection pool to manage,
and natively supports IAM authentication via ``GetClusterCredentials``.
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
)
from constructs import Construct


class RedshiftMonitorStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        redshift_cluster_id: str,
        redshift_database: str,
        redshift_db_user: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not (redshift_cluster_id and redshift_database and redshift_db_user):
            raise ValueError(
                "redshift_cluster_id, redshift_database, and redshift_db_user "
                "are all required. Set REDSHIFT_CLUSTER_ID / REDSHIFT_DATABASE "
                "/ REDSHIFT_DB_USER env vars, or the matching CDK context."
            )

        # function_name is fixed so the Chatbot stack's IAM policy can grant
        # `lambda:InvokeFunction` on a predictable ARN.
        self.monitor = _lambda.Function(
            self,
            "RedshiftLoadErrorMonitor",
            function_name="CheckRedshiftErrors",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="redshift_monitor.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.minutes(5),
            memory_size=256,
            description=(
                "Proactively scans Redshift stl_load_errors and emits a "
                "custom.redshift EventBridge event for the formatter."
            ),
            environment={
                "REDSHIFT_CLUSTER_ID": redshift_cluster_id,
                "REDSHIFT_DATABASE": redshift_database,
                "REDSHIFT_DB_USER": redshift_db_user,
            },
        )

        # Redshift Data API + temporary credential generation.
        self.monitor.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "redshift-data:ExecuteStatement",
                    "redshift-data:DescribeStatement",
                    "redshift-data:GetStatementResult",
                    "redshift:GetClusterCredentials",
                ],
                resources=["*"],
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
