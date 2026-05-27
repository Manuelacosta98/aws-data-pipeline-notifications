"""Handler-level tests for the formatter Lambda.

We mock the SNS client with ``unittest.mock.patch.object`` and assert on
the exact Chatbot payload the handler publishes, branch by branch. This
catches regressions the CDK assertions can't see — wrong emoji, wrong
severity keyword, broken console link, dropped error message.
"""

import json
import os
from unittest.mock import patch

import pytest

# conftest.py at repo root puts ``lambda/`` on sys.path so these imports work.
import lambda_formatter  # noqa: E402  (after sys.path manipulation)
from event_formatter import EventFormatter  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:111111111111:Test")


@pytest.fixture
def mock_sns():
    with patch.object(lambda_formatter, "_sns") as m:
        yield m


def _published_message(mock_sns) -> dict:
    mock_sns.publish.assert_called_once()
    kwargs = mock_sns.publish.call_args.kwargs
    return json.loads(kwargs["Message"])


def test_glue_failure_publishes_error_severity_and_job_link(mock_sns):
    event = {
        "source": "aws.glue",
        "detail-type": "Glue Job State Change",
        "detail": {
            "jobName": "customer_etl_daily",
            "state": "FAILED",
            "message": "Index error",
        },
    }
    lambda_formatter.lambda_handler(event, None)

    msg = _published_message(mock_sns)
    assert msg["content"]["title"].startswith("🚨")
    assert "Glue Job Failed" in msg["content"]["title"]
    assert "customer_etl_daily" in msg["content"]["description"]
    assert "Index error" in msg["content"]["description"]
    assert "error" in msg["content"]["keywords"]
    assert "aws.glue" in msg["content"]["keywords"]
    assert "gluestudio" in msg["content"]["description"]


def test_step_functions_success_publishes_success_severity(mock_sns):
    event = {
        "source": "aws.states",
        "detail-type": "Step Functions Execution Status Change",
        "detail": {
            "name": "DailyRun",
            "status": "SUCCEEDED",
            "stateMachineArn": "arn:aws:states:us-east-1:123:stateMachine:DataPipeline",
            "executionArn": "arn:aws:states:us-east-1:123:execution:DataPipeline:abc",
        },
    }
    lambda_formatter.lambda_handler(event, None)

    msg = _published_message(mock_sns)
    assert msg["content"]["title"].startswith("✅")
    assert msg["content"]["title"].endswith("Succeeded")
    assert "success" in msg["content"]["keywords"]
    assert "DailyRun" in msg["content"]["description"]


def test_step_functions_failure_publishes_error_severity(mock_sns):
    event = {
        "source": "aws.states",
        "detail-type": "Step Functions Execution Status Change",
        "detail": {
            "name": "DailyRun",
            "status": "FAILED",
            "stateMachineArn": "arn:aws:states:us-east-1:123:stateMachine:DataPipeline",
            "executionArn": "arn:aws:states:us-east-1:123:execution:DataPipeline:abc",
        },
    }
    lambda_formatter.lambda_handler(event, None)

    msg = _published_message(mock_sns)
    assert msg["content"]["title"].startswith("🚨")
    assert msg["content"]["title"].endswith("Failed")
    assert "error" in msg["content"]["keywords"]


def test_dms_table_completed_with_issues_is_warning_not_error(mock_sns):
    event = {
        "source": "aws.dms",
        "detail-type": "DMS Table State Change",
        "detail": {
            "task-id": "task-123",
            "table-name": "policies",
            "state": "Table completed with issues",
        },
    }
    lambda_formatter.lambda_handler(event, None)

    msg = _published_message(mock_sns)
    assert msg["content"]["title"].startswith("⚠️")
    assert "warning" in msg["content"]["keywords"]
    assert "policies" in msg["content"]["description"]
    assert "task-123" in msg["content"]["description"]


def test_dms_table_hard_error_stays_error_severity(mock_sns):
    event = {
        "source": "aws.dms",
        "detail-type": "DMS Table State Change",
        "detail": {
            "task-id": "task-456",
            "table-name": "claims",
            "state": "Table error",
        },
    }
    lambda_formatter.lambda_handler(event, None)

    msg = _published_message(mock_sns)
    assert msg["content"]["title"].startswith("🚨")
    assert "error" in msg["content"]["keywords"]


def test_dms_replication_task_failed_publishes_error_severity(mock_sns):
    event = {
        "source": "aws.dms",
        "detail-type": "DMS Replication Task State Change",
        "detail": {"task-id": "task-789", "state": "failed"},
    }
    lambda_formatter.lambda_handler(event, None)

    msg = _published_message(mock_sns)
    assert msg["content"]["title"].startswith("🚨")
    assert "DMS Replication Task Failed" in msg["content"]["title"]
    assert "task-789" in msg["content"]["description"]


def test_unknown_source_falls_through_to_info(mock_sns):
    event = {
        "source": "aws.lambda",
        "detail-type": "Lambda Function Error",
        "detail": {"foo": "bar"},
    }
    lambda_formatter.lambda_handler(event, None)

    msg = _published_message(mock_sns)
    assert msg["content"]["title"].startswith("ℹ️")
    assert "info" in msg["content"]["keywords"]


def test_sns_subject_is_truncated_to_100_chars(mock_sns):
    event = {
        "source": "aws.dms",
        "detail-type": "x" * 200,
        "detail": {"task-id": "t", "state": "failed"},
    }
    lambda_formatter.lambda_handler(event, None)

    subject = mock_sns.publish.call_args.kwargs["Subject"]
    assert len(subject) <= 100


# ---------------------------------------------------------------------
# Re-run hints (bidirectional Slack → AWS flow)
#
# These exercise the EventFormatter directly because the handler caches a
# formatter at module-import time, so we can't flip RERUN_HINTS_ENABLED
# inside a test without reloading the module.
# ---------------------------------------------------------------------


def test_rerun_hint_added_to_glue_failure_when_enabled():
    formatter = EventFormatter(region="us-east-1", rerun_hints_enabled=True)
    payload = formatter.format(
        {
            "source": "aws.glue",
            "detail-type": "Glue Job State Change",
            "detail": {
                "jobName": "customer_etl_daily",
                "state": "FAILED",
                "message": "Boom",
            },
        }
    )
    assert "🔁" in payload["content"]["description"]
    assert "/pipeline rerun glue customer_etl_daily" in payload["content"]["description"]


def test_rerun_hint_added_to_step_functions_failure_when_enabled():
    formatter = EventFormatter(region="us-east-1", rerun_hints_enabled=True)
    payload = formatter.format(
        {
            "source": "aws.states",
            "detail-type": "Step Functions Execution Status Change",
            "detail": {
                "name": "DailyRun",
                "status": "FAILED",
                "stateMachineArn": "arn:aws:states:us-east-1:123:stateMachine:DataPipeline",
                "executionArn": "arn:aws:states:us-east-1:123:execution:DataPipeline:abc",
            },
        }
    )
    assert "/pipeline rerun sfn DataPipeline" in payload["content"]["description"]


def test_rerun_hint_not_added_to_step_functions_success():
    """Success notifications must not carry a re-run hint — the run just succeeded."""
    formatter = EventFormatter(region="us-east-1", rerun_hints_enabled=True)
    payload = formatter.format(
        {
            "source": "aws.states",
            "detail-type": "Step Functions Execution Status Change",
            "detail": {
                "name": "DailyRun",
                "status": "SUCCEEDED",
                "stateMachineArn": "arn:aws:states:us-east-1:123:stateMachine:DataPipeline",
                "executionArn": "arn:aws:states:us-east-1:123:execution:DataPipeline:abc",
            },
        }
    )
    assert "/pipeline rerun" not in payload["content"]["description"]


def test_rerun_hint_absent_when_disabled():
    formatter = EventFormatter(region="us-east-1", rerun_hints_enabled=False)
    payload = formatter.format(
        {
            "source": "aws.glue",
            "detail-type": "Glue Job State Change",
            "detail": {
                "jobName": "customer_etl_daily",
                "state": "FAILED",
                "message": "Boom",
            },
        }
    )
    assert "🔁" not in payload["content"]["description"]
    assert "/pipeline rerun" not in payload["content"]["description"]


# ---------------------------------------------------------------------
# QuickSight + active enrichment
# ---------------------------------------------------------------------


def _quicksight_event(status: str = "FAILED") -> dict:
    return {
        "source": "aws.quicksight",
        "detail-type": "QuickSight Dataset SPICE Ingestion Completed",
        "account": "111111111111",
        "time": "2026-05-26T14:02:00Z",
        "detail": {
            "dataSetId": "abc-def-123",
            "ingestionId": "ing-456",
            "ingestionStatus": status,
            "errorInfo": {
                "type": "DATA_TOLERANCE_EXCEEDED",
                "message": "fallback message from event",
            },
        },
    }


def test_quicksight_failure_uses_enriched_dataset_name_and_error():
    formatter = EventFormatter(region="us-east-1")
    formatter._enrich_quicksight = lambda **kwargs: (
        "Customer Daily Refresh",
        "Row count exceeds SPICE capacity by 12,431 rows",
        "DATA_TOLERANCE_EXCEEDED",
    )
    payload = formatter.format(_quicksight_event())

    assert "🚨" in payload["content"]["title"]
    assert "Customer Daily Refresh" in payload["content"]["title"]
    assert "Row count exceeds SPICE capacity by 12,431 rows" in payload["content"]["description"]
    assert "DATA_TOLERANCE_EXCEEDED" in payload["content"]["description"]
    assert "error" in payload["content"]["keywords"]
    assert "aws.quicksight" in payload["content"]["keywords"]


def test_quicksight_enrichment_falls_back_to_event_payload_on_api_error():
    formatter = EventFormatter(region="us-east-1")
    # Simulate the API returning the fallbacks as-is (e.g. caller had no perms).
    formatter._enrich_quicksight = lambda **kwargs: (
        kwargs["dataset_id"],
        kwargs["fallback_message"],
        kwargs["fallback_type"],
    )
    payload = formatter.format(_quicksight_event())

    # Title uses the raw ID, description uses the EventBridge fallback message.
    assert "abc-def-123" in payload["content"]["title"]
    assert "fallback message from event" in payload["content"]["description"]


# ---------------------------------------------------------------------
# Proactive monitor formatters (custom.redshift, custom.dms)
# ---------------------------------------------------------------------


def test_custom_redshift_success_renders_clear_status():
    formatter = EventFormatter(region="us-east-1")
    payload = formatter.format(
        {
            "source": "custom.redshift",
            "detail-type": "Redshift Load Success",
            "detail": {
                "cluster": "redshiftcluster-abc",
                "database": "analytics",
                "error_count": 0,
                "status": "success",
                "check_period": "since yesterday",
                "error_details": [],
            },
        }
    )
    assert "✅" in payload["content"]["title"]
    assert "No Errors" in payload["content"]["title"]
    assert "success" in payload["content"]["keywords"]
    assert "redshiftcluster-abc" in payload["content"]["description"]


def test_custom_redshift_failure_renders_itemized_errors():
    formatter = EventFormatter(region="us-east-1")
    payload = formatter.format(
        {
            "source": "custom.redshift",
            "detail-type": "Redshift Load Failure",
            "detail": {
                "cluster": "redshiftcluster-abc",
                "database": "analytics",
                "error_count": 2,
                "status": "failure",
                "check_period": "since yesterday",
                "error_details": [
                    {
                        "starttime": "2026-05-26 14:02:11",
                        "filename": "claims.csv",
                        "err_reason": "String length exceeds DDL length",
                        "colname": "policy_holder_name",
                    },
                    {
                        "starttime": "2026-05-26 14:02:12",
                        "filename": "claims.csv",
                        "err_reason": "Invalid date format",
                        "colname": "claim_date",
                    },
                ],
            },
        }
    )
    desc = payload["content"]["description"]
    assert "🚨" in payload["content"]["title"]
    assert "Total errors: 2" in desc
    assert "claims.csv" in desc
    assert "policy_holder_name" in desc
    assert "Invalid date format" in desc


def test_custom_dms_success_renders_clear_status():
    formatter = EventFormatter(region="us-east-1")
    payload = formatter.format(
        {
            "source": "custom.dms",
            "detail-type": "DMS Log Success",
            "detail": {
                "log_group": "/aws/dms/serverless/abc",
                "hours_back": 24,
                "status": "success",
                "error_tables": [],
                "field_errors": [],
                "total_table_errors": 0,
                "total_field_errors": 0,
            },
        }
    )
    assert "✅" in payload["content"]["title"]
    assert "No Errors" in payload["content"]["title"]


def test_custom_dms_failure_renders_table_stats_and_cleaned_log_lines():
    formatter = EventFormatter(region="us-east-1")
    payload = formatter.format(
        {
            "source": "custom.dms",
            "detail-type": "DMS Log Errors",
            "detail": {
                "log_group": "/aws/dms/serverless/abc",
                "hours_back": 24,
                "status": "failure",
                "error_tables": [
                    {
                        "schema": "public",
                        "table": "policies",
                        "state": "Table error",
                        "full_load_rows": 1000,
                        "full_load_error_rows": 12,
                    }
                ],
                "field_errors": [
                    {
                        "timestamp": "2026-05-26 14:02:11 UTC",
                        # Raw DMS log: timestamp + component prefix + file ref
                        "message": "2026-05-26T14:02:11 [SOURCE_UNLOAD   ]E:  value exceeds length (file_unload.c:628)",
                    }
                ],
                "total_table_errors": 1,
                "total_field_errors": 1,
            },
        }
    )
    desc = payload["content"]["description"]
    assert "🚨" in payload["content"]["title"]
    assert "public.policies" in desc
    assert "Error rows: 12 / 1000" in desc
    # The DMS log noise should be stripped by clean_dms_log_message:
    assert "value exceeds length" in desc
    assert "[SOURCE_UNLOAD" not in desc
    assert "file_unload.c" not in desc


# ---------------------------------------------------------------------
# clean_dms_log_message helper
# ---------------------------------------------------------------------


def test_clean_dms_log_message_strips_all_three_noise_patterns():
    from event_formatter import clean_dms_log_message

    raw = "2026-03-03T17:17:47 [SOURCE_UNLOAD   ]E:  value exceeds length (file_unload.c:628)"
    assert clean_dms_log_message(raw) == "value exceeds length"


def test_clean_dms_log_message_handles_warning_level():
    from event_formatter import clean_dms_log_message

    raw = "2026-03-03T17:17:47 [TASK_MANAGER]W: replication is slow"
    assert clean_dms_log_message(raw) == "replication is slow"


def test_clean_dms_log_message_passthrough_when_no_noise():
    from event_formatter import clean_dms_log_message

    assert clean_dms_log_message("already clean") == "already clean"
