"""Proactive DMS error scan, emitted as a custom EventBridge event.

Combines two data sources to produce a rich error picture:

1. **DMS Replication Table Statistics** — gives per-table row counts and
   error counts. Pages through all results so a config with hundreds of
   tables still reports correctly.
2. **CloudWatch Logs ``]E:`` filter** — DMS prefixes individual row-level
   errors in its log lines with ``]E:``. We filter for those lines in a
   recent time window and return them as field-level error context.

The result is put onto the default EventBridge bus as
``custom.dms`` so the central formatter Lambda renders it into Slack.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_dms = boto3.client("dms")
_logs = boto3.client("logs")
_events = boto3.client("events")


def _get_error_tables(replication_config_arn: str) -> list[dict]:
    """Page through DMS table statistics, return tables with load errors."""
    error_tables: list[dict] = []
    kwargs = {"ReplicationConfigArn": replication_config_arn}

    while True:
        resp = _dms.describe_replication_table_statistics(**kwargs)
        for t in resp.get("ReplicationTableStatistics", []):
            full_load_errors = t.get("FullLoadErrorRows", 0)
            state = t.get("TableState", "")
            if full_load_errors > 0 or "error" in state.lower():
                error_tables.append(
                    {
                        "schema": t.get("SchemaName", "N/A"),
                        "table": t.get("TableName", "N/A"),
                        "state": state,
                        "full_load_rows": t.get("FullLoadRows", 0),
                        "full_load_error_rows": full_load_errors,
                        "full_load_condtnl_failed_rows": t.get(
                            "FullLoadCondtnlChkFailedRows", 0
                        ),
                    }
                )
        marker = resp.get("Marker")
        if not marker:
            break
        kwargs["Marker"] = marker

    return error_tables


def _get_field_errors(log_group: str, hours_back: int, limit: int) -> list[dict]:
    """Filter CloudWatch Logs for DMS ]E: error entries within the window."""
    start_time_ms = int(
        (datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp() * 1000
    )
    collected: list[dict] = []
    kwargs = {
        "logGroupName": log_group,
        "startTime": start_time_ms,
        "filterPattern": '"]E:"',
        "limit": min(limit, 100),
    }

    try:
        resp = _logs.filter_log_events(**kwargs)
        collected.extend(resp.get("events", []))
        while "nextToken" in resp and len(collected) < limit:
            remaining = limit - len(collected)
            kwargs["nextToken"] = resp["nextToken"]
            kwargs["limit"] = min(remaining, 100)
            resp = _logs.filter_log_events(**kwargs)
            collected.extend(resp.get("events", []))
    except _logs.exceptions.ResourceNotFoundException:
        logger.warning("Log group not found: %s", log_group)
    except Exception:
        logger.exception("Filter log events failed")
        raise

    return collected


def lambda_handler(event, context):
    """Combine DMS table stats + ]E: log scan into a custom.dms event."""
    try:
        replication_arn = os.environ["DMS_TASK_ARN"]
        log_group = os.environ["DMS_LOG_GROUP"]
    except KeyError as missing:
        logger.error("Missing required env var: %s", missing)
        return {"statusCode": 500, "body": json.dumps({"error": f"missing env: {missing}"})}

    hours_back = int(event.get("hours_back", os.environ.get("DMS_LOG_HOURS_BACK", "24")))
    limit = int(event.get("limit", 20))

    logger.info(
        "Checking DMS errors arn=%s log_group=%s hours_back=%s",
        replication_arn, log_group, hours_back,
    )

    error_tables = _get_error_tables(replication_arn)
    raw_log_events = _get_field_errors(log_group, hours_back, limit)

    # Render at most 10 log entries in the alert to keep messages scannable.
    field_errors = []
    for evt in raw_log_events[:10]:
        ts_ms = evt.get("timestamp", 0)
        ts_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        field_errors.append(
            {"timestamp": ts_str, "message": evt.get("message", "").strip()[:500]}
        )

    has_errors = bool(error_tables) or bool(raw_log_events)
    detail_type = "DMS Log Errors" if has_errors else "DMS Log Success"
    detail = {
        "replication_config_arn": replication_arn,
        "log_group": log_group,
        "hours_back": hours_back,
        "error_tables": error_tables,
        "field_errors": field_errors,
        "total_table_errors": len(error_tables),
        "total_field_errors": len(raw_log_events),
        "status": "failure" if has_errors else "success",
    }

    _events.put_events(
        Entries=[
            {
                "Source": "custom.dms",
                "DetailType": detail_type,
                "Detail": json.dumps(detail),
            }
        ]
    )
    logger.info(
        "Emitted %s tables=%s log_entries=%s",
        detail_type, len(error_tables), len(raw_log_events),
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "DMS check completed",
                "total_table_errors": len(error_tables),
                "total_field_errors": len(raw_log_events),
                "status": detail["status"],
            }
        ),
    }
