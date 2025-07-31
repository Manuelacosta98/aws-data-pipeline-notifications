from aws_cdk import (
    Stack,
    aws_events as events,
    aws_events_targets as targets,
    aws_sns as sns,
    aws_lambda as _lambda,
    Duration,
)
from constructs import Construct

class EventBridgeStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # SNS Topic for notifications with CloudWatch tracking
        topic = sns.Topic(self, "DataPipelineFailures",
            display_name="Data Pipeline Failures",
            topic_name="DataPipelineFailures",
            tracing_config= sns.TracingConfig.ACTIVE
        )
        
        # Lambda function to format messages
        formatter = _lambda.Function(self, "MessageFormatter",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_formatter.lambda_handler",
            code=_lambda.Code.from_asset("infra"),
            timeout=Duration.seconds(30),
            environment={
                'SNS_TOPIC_ARN': topic.topic_arn
            }
        )
        
        # Grant Lambda permission to publish to SNS
        topic.grant_publish(formatter)

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

        self.sns_topic = topic
