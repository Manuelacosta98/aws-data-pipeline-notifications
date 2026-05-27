"""CDK synth-level tests for the RedshiftMonitorStack."""

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from infra.redshift_monitor_stack import RedshiftMonitorStack


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App()
    stack = RedshiftMonitorStack(
        app,
        "TestRedshiftMonitor",
        redshift_cluster_id="redshiftcluster-abc",
        redshift_database="analytics",
        redshift_db_user="reporter",
        env=cdk.Environment(account="111111111111", region="us-east-1"),
    )
    return assertions.Template.from_stack(stack)


def test_monitor_lambda_has_fixed_function_name_for_chatbot_invocation(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "FunctionName": "CheckRedshiftErrors",
                "Handler": "redshift_monitor.lambda_handler",
                "Runtime": "python3.11",
            }
        ),
    )


def test_monitor_lambda_has_redshift_env_vars(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "Environment": assertions.Match.object_like(
                    {
                        "Variables": assertions.Match.object_like(
                            {
                                "REDSHIFT_CLUSTER_ID": "redshiftcluster-abc",
                                "REDSHIFT_DATABASE": "analytics",
                                "REDSHIFT_DB_USER": "reporter",
                            }
                        )
                    }
                )
            }
        ),
    )


def test_monitor_has_redshift_data_api_permissions(template):
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
                                                "redshift-data:ExecuteStatement",
                                                "redshift-data:DescribeStatement",
                                                "redshift-data:GetStatementResult",
                                                "redshift:GetClusterCredentials",
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


def test_monitor_can_put_events_to_default_bus(template):
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
                                        "Action": "events:PutEvents",
                                        "Resource": "arn:aws:events:us-east-1:111111111111:event-bus/default",
                                    }
                                )
                            ]
                        )
                    }
                )
            }
        ),
    )


def test_missing_required_kwargs_raises():
    app = cdk.App()
    with pytest.raises(ValueError):
        RedshiftMonitorStack(
            app,
            "BadRedshift",
            redshift_cluster_id="",
            redshift_database="",
            redshift_db_user="",
            env=cdk.Environment(account="111111111111", region="us-east-1"),
        )
