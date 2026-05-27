"""Unit tests for the EventBridge stack.

We synthesize the stack and assert against the resulting CloudFormation
template. These tests guard the behavioral contract of the alerting
pipeline: which AWS sources we listen to, which failure states we route,
and what we publish them to.
"""

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from infra.eventbridge_stack import EventBridgeStack


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App()
    stack = EventBridgeStack(app, "TestEventBridgeStack")
    return assertions.Template.from_stack(stack)


def test_sns_topic_for_pipeline_failures_is_created(template):
    template.has_resource_properties(
        "AWS::SNS::Topic",
        {
            "DisplayName": "Data Pipeline Failures",
            "TopicName": "DataPipelineFailures",
        },
    )


def test_formatter_lambda_is_python_and_wired_to_handler(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "lambda_formatter.lambda_handler",
            "Runtime": "python3.11",
        },
    )


def test_one_eventbridge_rule_per_monitored_source(template):
    # Step Functions, DMS task, DMS table, Glue, QuickSight, custom.redshift,
    # custom.dms = 7 rules in the default (no opt-in) configuration.
    template.resource_count_is("AWS::Events::Rule", 7)


def test_quicksight_ingestion_failure_rule_exists(template):
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aws.quicksight"],
                "detail-type": ["QuickSight Dataset SPICE Ingestion Completed"],
                "detail": {"ingestionStatus": ["FAILED", "CANCELLED"]},
            }
        },
    )


def test_custom_redshift_rule_exists(template):
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["custom.redshift"],
                "detail-type": ["Redshift Load Failure", "Redshift Load Success"],
            }
        },
    )


def test_custom_dms_rule_exists(template):
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["custom.dms"],
                "detail-type": ["DMS Log Errors", "DMS Log Success"],
            }
        },
    )


def test_formatter_lambda_has_quicksight_describe_permissions(template):
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
                                        "Effect": "Allow",
                                        "Action": assertions.Match.array_with(
                                            [
                                                "quicksight:DescribeDataSet",
                                                "quicksight:DescribeIngestion",
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


def test_step_functions_failure_rule_filters_terminal_states(template):
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aws.states"],
                "detail-type": ["Step Functions Execution Status Change"],
                "detail": {"status": ["FAILED", "TIMED_OUT", "ABORTED"]},
            }
        },
    )


def test_glue_failure_rule_filters_terminal_states(template):
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aws.glue"],
                "detail-type": ["Glue Job State Change"],
                "detail": {"state": ["FAILED", "STOPPED", "ERROR"]},
            }
        },
    )


def test_dms_replication_task_rule_filters_failed_states(template):
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aws.dms"],
                "detail-type": ["DMS Replication Task State Change"],
                "detail": {"state": ["stopped", "failed"]},
            }
        },
    )
