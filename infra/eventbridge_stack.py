from aws_cdk import (
    Stack,
    aws_events as events,
    aws_events_targets as targets,
    aws_sns as sns,
    aws_lambda as _lambda,
    aws_iam as iam,
    Duration,
)
from constructs import Construct

class EventBridgeStack(Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        rerun_hints_enabled: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # SNS Topic for notifications with CloudWatch tracking
        topic = sns.Topic(self, "DataPipelineFailures",
            display_name="Data Pipeline Failures",
            topic_name="DataPipelineFailures",
            tracing_config= sns.TracingConfig.ACTIVE
        )
        
        # Lambda function to format messages.
        # Code is loaded from the dedicated `lambda/` folder so the deployment
        # bundle only contains the handler, not the CDK source.
        formatter = _lambda.Function(self, "MessageFormatter",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_formatter.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(30),
            environment={
                'SNS_TOPIC_ARN': topic.topic_arn,
                'RERUN_HINTS_ENABLED': "true" if rerun_hints_enabled else "false",
            }
        )
        
        # Grant Lambda permission to publish to SNS
        topic.grant_publish(formatter)

        # Allow the formatter to actively enrich QuickSight events via the
        # QuickSight API: resolve dataset IDs to human-readable names and
        # fetch the detailed ingestion error (which is more specific than
        # the EventBridge payload's generic error message).
        formatter.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "quicksight:DescribeDataSet",
                    "quicksight:DescribeIngestion",
                    "quicksight:DescribeDataSetRefreshProperties",
                ],
                resources=["*"],
            )
        )

        # Step Functions failure events
        events.Rule(self, "StepFunctionFailures",
            event_pattern=events.EventPattern(
                source=["aws.states"],
                detail_type=["Step Functions Execution Status Change"],
                detail={"status": ["FAILED", "TIMED_OUT", "ABORTED"]}
            ),
            targets=[targets.LambdaFunction(formatter)]
        )

        # DMS failure events
        events.Rule(self, "DMSFailures",
            event_pattern=events.EventPattern(
                source=["aws.dms"],
                detail_type=["DMS Replication Task State Change"],
                detail={"state": ["stopped", "failed"]}
            ),
            targets=[targets.LambdaFunction(formatter)]
        )

        # DMS table failure events
        events.Rule(self, "DMSTableFailures",
            event_pattern=events.EventPattern(
                source=["aws.dms"],
                detail_type=["DMS Table State Change"],
                detail={"state": ["Table error", "Table completed with issues"]}
            ),
            targets=[targets.LambdaFunction(formatter)]
        )

        # Glue job failure events
        events.Rule(self, "GlueFailures",
            event_pattern=events.EventPattern(
                source=["aws.glue"],
                detail_type=["Glue Job State Change"],
                detail={"state": ["FAILED", "STOPPED", "ERROR"]}
            ),
            targets=[targets.LambdaFunction(formatter)]
        )

        # QuickSight SPICE ingestion failures.
        # Failed and cancelled refreshes both produce an alert because cancellation
        # is rarely intentional in scheduled refresh contexts.
        events.Rule(self, "QuickSightIngestionFailures",
            event_pattern=events.EventPattern(
                source=["aws.quicksight"],
                detail_type=["QuickSight Dataset SPICE Ingestion Completed"],
                detail={"ingestionStatus": ["FAILED", "CANCELLED"]}
            ),
            targets=[targets.LambdaFunction(formatter)]
        )

        # Custom events emitted by the proactive Redshift/DMS monitor Lambdas
        # (Hybrid push+pull architecture — these monitors poll Redshift /
        # CloudWatch Logs because AWS does not natively emit events for the
        # load failures we care about, then put structured events here.)
        events.Rule(self, "RedshiftLoadCheckRule",
            event_pattern=events.EventPattern(
                source=["custom.redshift"],
                detail_type=["Redshift Load Failure", "Redshift Load Success"]
            ),
            targets=[targets.LambdaFunction(formatter)]
        )

        events.Rule(self, "DmsLogCheckRule",
            event_pattern=events.EventPattern(
                source=["custom.dms"],
                detail_type=["DMS Log Errors", "DMS Log Success"]
            ),
            targets=[targets.LambdaFunction(formatter)]
        )

        # Opt-in: Step Functions SUCCESS notifications.
        # Off by default because state-machine success events can be noisy
        # in busy accounts. Turn on with:
        #   cdk synth -c notifyOnPipelineSuccess=true
        # or by setting "notifyOnPipelineSuccess": true in cdk.json context.
        if self.node.try_get_context("notifyOnPipelineSuccess"):
            events.Rule(self, "StepFunctionSuccesses",
                event_pattern=events.EventPattern(
                    source=["aws.states"],
                    detail_type=["Step Functions Execution Status Change"],
                    detail={"status": ["SUCCEEDED"]}
                ),
                targets=[targets.LambdaFunction(formatter)]
            )

        self.sns_topic = topic
