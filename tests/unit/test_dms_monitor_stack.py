"""CDK synth-level tests for the DmsMonitorStack."""

import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from infra.dms_monitor_stack import DmsMonitorStack


_TASK_ARN = "arn:aws:dms:us-east-1:111111111111:replication-config:test-config"
_LOG_GROUP = "/aws/dms/serverless-replication/test-config"


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App()
    stack = DmsMonitorStack(
        app,
        "TestDmsMonitor",
        dms_task_arn=_TASK_ARN,
        dms_log_group=_LOG_GROUP,
        env=cdk.Environment(account="111111111111", region="us-east-1"),
    )
    return assertions.Template.from_stack(stack)


def test_monitor_lambda_has_fixed_function_name_for_chatbot_invocation(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "FunctionName": "CheckDMSErrors",
                "Handler": "dms_monitor.lambda_handler",
                "Runtime": "python3.11",
            }
        ),
    )


def test_monitor_lambda_has_dms_env_vars(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "Environment": assertions.Match.object_like(
                    {
                        "Variables": assertions.Match.object_like(
                            {
                                "DMS_TASK_ARN": _TASK_ARN,
                                "DMS_LOG_GROUP": _LOG_GROUP,
                                "DMS_LOG_HOURS_BACK": "24",
                            }
                        )
                    }
                )
            }
        ),
    )


def test_dms_describe_scoped_to_specific_replication_config(template):
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
                                        "Action": "dms:DescribeReplicationTableStatistics",
                                        "Resource": _TASK_ARN,
                                    }
                                )
                            ]
                        )
                    }
                )
            }
        ),
    )


def test_log_read_scoped_to_specific_log_group(template):
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
                                            ["logs:FilterLogEvents"]
                                        ),
                                        "Resource": assertions.Match.array_with(
                                            [
                                                f"arn:aws:logs:us-east-1:111111111111:log-group:{_LOG_GROUP}",
                                                f"arn:aws:logs:us-east-1:111111111111:log-group:{_LOG_GROUP}:*",
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


def test_missing_required_kwargs_raises():
    app = cdk.App()
    with pytest.raises(ValueError):
        DmsMonitorStack(
            app,
            "BadDms",
            dms_task_arn="",
            dms_log_group="",
            env=cdk.Environment(account="111111111111", region="us-east-1"),
        )
