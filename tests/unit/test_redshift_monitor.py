"""Handler-level tests for the Redshift monitor Lambda.

We mock boto3's redshift-data and events clients and assert on the
EventBridge payload the handler emits.
"""

import json
from unittest.mock import patch

import pytest

# conftest.py at repo root puts ``lambda/`` on sys.path.
import redshift_monitor  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("REDSHIFT_CLUSTER_ID", "redshiftcluster-abc")
    monkeypatch.setenv("REDSHIFT_DATABASE", "analytics")
    monkeypatch.setenv("REDSHIFT_DB_USER", "reporter")


@pytest.fixture
def mock_data():
    with patch.object(redshift_monitor, "_redshift_data") as m:
        yield m


@pytest.fixture
def mock_events():
    with patch.object(redshift_monitor, "_events") as m:
        yield m


def _setup_query_lifecycle(mock_data, records: list):
    """Simulate execute_statement → describe_statement → get_statement_result."""
    mock_data.execute_statement.return_value = {"Id": "q-1"}
    mock_data.describe_statement.return_value = {"Status": "FINISHED"}
    mock_data.get_statement_result.return_value = {"Records": records}


def test_success_path_emits_no_errors_event(mock_data, mock_events):
    _setup_query_lifecycle(mock_data, records=[])
    redshift_monitor.lambda_handler({}, None)

    mock_events.put_events.assert_called_once()
    entry = mock_events.put_events.call_args.kwargs["Entries"][0]
    assert entry["Source"] == "custom.redshift"
    assert entry["DetailType"] == "Redshift Load Success"

    detail = json.loads(entry["Detail"])
    assert detail["status"] == "success"
    assert detail["error_count"] == 0
    assert detail["error_details"] == []


def test_failure_path_emits_itemized_errors(mock_data, mock_events):
    records = [
        [
            {"stringValue": "2026-05-26 14:02:11"},
            {"stringValue": "claims.csv"},
            {"stringValue": "String length exceeds DDL length"},
            {"stringValue": "policy_holder_name"},
        ],
        [
            {"stringValue": "2026-05-26 14:02:12"},
            {"stringValue": "claims.csv"},
            {"stringValue": "Invalid date format"},
            {"stringValue": "claim_date"},
        ],
    ]
    _setup_query_lifecycle(mock_data, records=records)
    redshift_monitor.lambda_handler({}, None)

    entry = mock_events.put_events.call_args.kwargs["Entries"][0]
    assert entry["DetailType"] == "Redshift Load Failure"
    detail = json.loads(entry["Detail"])
    assert detail["status"] == "failure"
    assert detail["error_count"] == 2
    assert detail["error_details"][0]["err_reason"] == "String length exceeds DDL length"
    assert detail["error_details"][1]["colname"] == "claim_date"


def test_pagination_args_pass_through_to_sql(mock_data, mock_events):
    _setup_query_lifecycle(mock_data, records=[])
    redshift_monitor.lambda_handler({"limit": 50, "offset": 100}, None)

    sql = mock_data.execute_statement.call_args.kwargs["Sql"]
    assert "LIMIT 50" in sql
    assert "OFFSET 100" in sql


def test_query_failure_returns_500(mock_data, mock_events):
    mock_data.execute_statement.return_value = {"Id": "q-1"}
    mock_data.describe_statement.return_value = {
        "Status": "FAILED",
        "Error": "permission denied",
    }
    result = redshift_monitor.lambda_handler({}, None)
    assert result["statusCode"] == 500
    mock_events.put_events.assert_not_called()
