"""Handler-level tests for the DMS monitor Lambda."""

import json
from unittest.mock import patch

import pytest

# conftest.py at repo root puts ``lambda/`` on sys.path.
import dms_monitor  # noqa: E402


_ARN = "arn:aws:dms:us-east-1:111111111111:replication-config:test"
_LOG_GROUP = "/aws/dms/serverless-replication/test"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DMS_TASK_ARN", _ARN)
    monkeypatch.setenv("DMS_LOG_GROUP", _LOG_GROUP)
    monkeypatch.setenv("DMS_LOG_HOURS_BACK", "24")


@pytest.fixture
def mock_dms():
    with patch.object(dms_monitor, "_dms") as m:
        yield m


@pytest.fixture
def mock_logs():
    with patch.object(dms_monitor, "_logs") as m:
        yield m


@pytest.fixture
def mock_events():
    with patch.object(dms_monitor, "_events") as m:
        yield m


def test_success_path_emits_success_event(mock_dms, mock_logs, mock_events):
    mock_dms.describe_replication_table_statistics.return_value = {
        "ReplicationTableStatistics": []
    }
    mock_logs.filter_log_events.return_value = {"events": []}

    dms_monitor.lambda_handler({}, None)

    entry = mock_events.put_events.call_args.kwargs["Entries"][0]
    assert entry["Source"] == "custom.dms"
    assert entry["DetailType"] == "DMS Log Success"
    detail = json.loads(entry["Detail"])
    assert detail["status"] == "success"
    assert detail["total_table_errors"] == 0
    assert detail["total_field_errors"] == 0


def test_table_errors_detected_emit_failure_event(mock_dms, mock_logs, mock_events):
    mock_dms.describe_replication_table_statistics.return_value = {
        "ReplicationTableStatistics": [
            {
                "SchemaName": "public",
                "TableName": "policies",
                "TableState": "Table error",
                "FullLoadRows": 1000,
                "FullLoadErrorRows": 12,
            }
        ]
    }
    mock_logs.filter_log_events.return_value = {"events": []}

    dms_monitor.lambda_handler({}, None)

    entry = mock_events.put_events.call_args.kwargs["Entries"][0]
    assert entry["DetailType"] == "DMS Log Errors"
    detail = json.loads(entry["Detail"])
    assert detail["status"] == "failure"
    assert detail["total_table_errors"] == 1
    assert detail["error_tables"][0]["table"] == "policies"
    assert detail["error_tables"][0]["full_load_error_rows"] == 12


def test_log_field_errors_get_truncated_and_attached(mock_dms, mock_logs, mock_events):
    mock_dms.describe_replication_table_statistics.return_value = {
        "ReplicationTableStatistics": []
    }
    # 15 events; handler should attach at most 10 to the payload.
    mock_logs.filter_log_events.return_value = {
        "events": [
            {"timestamp": 1716732131000, "message": f"]E: error #{i}"} for i in range(15)
        ]
    }

    dms_monitor.lambda_handler({}, None)
    detail = json.loads(mock_events.put_events.call_args.kwargs["Entries"][0]["Detail"])
    assert detail["status"] == "failure"
    assert detail["total_field_errors"] == 15  # raw count
    assert len(detail["field_errors"]) == 10    # truncated for the alert


def test_table_paging_collects_all_marker_pages(mock_dms, mock_logs, mock_events):
    """The handler must follow DMS table-stats pagination."""
    mock_dms.describe_replication_table_statistics.side_effect = [
        {
            "ReplicationTableStatistics": [
                {
                    "SchemaName": "s",
                    "TableName": "t1",
                    "TableState": "Table error",
                    "FullLoadRows": 100,
                    "FullLoadErrorRows": 5,
                }
            ],
            "Marker": "page-2",
        },
        {
            "ReplicationTableStatistics": [
                {
                    "SchemaName": "s",
                    "TableName": "t2",
                    "TableState": "Table error",
                    "FullLoadRows": 100,
                    "FullLoadErrorRows": 7,
                }
            ],
        },
    ]
    mock_logs.filter_log_events.return_value = {"events": []}

    dms_monitor.lambda_handler({}, None)
    detail = json.loads(mock_events.put_events.call_args.kwargs["Entries"][0]["Detail"])
    assert detail["total_table_errors"] == 2
    tables = {t["table"] for t in detail["error_tables"]}
    assert tables == {"t1", "t2"}


def test_log_group_not_found_does_not_crash(mock_dms, mock_logs, mock_events):
    """A missing log group should be logged but not raised — table stats still flow."""
    mock_dms.describe_replication_table_statistics.return_value = {
        "ReplicationTableStatistics": []
    }
    # Simulate the ResourceNotFoundException raised by the boto3 client.
    class _NotFound(Exception):
        pass

    mock_logs.exceptions.ResourceNotFoundException = _NotFound
    mock_logs.filter_log_events.side_effect = _NotFound()

    result = dms_monitor.lambda_handler({}, None)
    assert result["statusCode"] == 200
    mock_events.put_events.assert_called_once()
