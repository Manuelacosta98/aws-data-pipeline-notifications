"""Proactive Redshift load-error scan, emitted as a custom EventBridge event.

Reads ``stl_load_errors`` via the Redshift Data API, packages the most
recent N errors into a structured detail payload, and puts a
``custom.redshift`` event onto the default EventBridge bus. The
``EventBridgeStack`` formatter Lambda picks it up via its
``RedshiftLoadCheckRule`` and turns it into a Slack alert.

The Data API is async — we submit the statement, poll for completion,
then fetch results. This avoids the need for a psycopg2 layer.
"""

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_redshift_data = boto3.client("redshift-data")
_events = boto3.client("events")

# How long to wait for a Data API statement to finish before giving up.
_POLL_TIMEOUT_SECONDS = 60
_POLL_INTERVAL_SECONDS = 1


def _execute_query(sql: str, cluster_id: str, database: str, db_user: str):
    """Submit a Redshift Data API statement and return its result Records."""
    submit = _redshift_data.execute_statement(
        ClusterIdentifier=cluster_id,
        Database=database,
        DbUser=db_user,
        Sql=sql,
    )
    query_id = submit["Id"]
    logger.info("Submitted query: %s", query_id)

    deadline = time.time() + _POLL_TIMEOUT_SECONDS
    while True:
        status = _redshift_data.describe_statement(Id=query_id)
        state = status["Status"]
        if state == "FINISHED":
            break
        if state in ("FAILED", "ABORTED"):
            raise RuntimeError(
                f"Query {state.lower()}: {status.get('Error', 'unknown error')}"
            )
        if time.time() >= deadline:
            raise TimeoutError(
                f"Query did not finish within {_POLL_TIMEOUT_SECONDS}s; "
                f"last state={state}"
            )
        time.sleep(_POLL_INTERVAL_SECONDS)

    return _redshift_data.get_statement_result(Id=query_id)["Records"]


def lambda_handler(event, context):
    """Scan stl_load_errors and emit a custom EventBridge event with the result."""
    try:
        cluster_id = os.environ["REDSHIFT_CLUSTER_ID"]
        database = os.environ["REDSHIFT_DATABASE"]
        db_user = os.environ["REDSHIFT_DB_USER"]
    except KeyError as missing:
        logger.error("Missing required env var: %s", missing)
        return {"statusCode": 500, "body": json.dumps({"error": f"missing env: {missing}"})}

    # Pagination is exposed as an event-level concern so the user can fetch
    # older error windows by passing {"limit": N, "offset": M} when invoking.
    limit = int(event.get("limit", 10))
    offset = int(event.get("offset", 0))

    logger.info(
        "Checking Redshift load errors cluster=%s limit=%s offset=%s",
        cluster_id, limit, offset,
    )

    sql = f"""
        SELECT starttime, filename, err_reason, colname
        FROM stl_load_errors
        ORDER BY starttime DESC
        LIMIT {limit}
        OFFSET {offset};
    """

    try:
        records = _execute_query(sql, cluster_id, database, db_user)
    except Exception as exc:
        logger.exception("Redshift query failed")
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}

    error_count = len(records) if records else 0
    error_details = []
    for row in records[:10]:
        error_details.append(
            {
                "starttime": row[0].get("stringValue", ""),
                "filename": row[1].get("stringValue", ""),
                "err_reason": row[2].get("stringValue", ""),
                "colname": row[3].get("stringValue", "N/A") or "N/A",
            }
        )

    detail_type = "Redshift Load Failure" if error_count else "Redshift Load Success"
    detail = {
        "cluster": cluster_id,
        "database": database,
        "error_count": error_count,
        "check_period": "all available records",
        "status": "failure" if error_count else "success",
        "error_details": error_details,
    }

    _events.put_events(
        Entries=[
            {
                "Source": "custom.redshift",
                "DetailType": detail_type,
                "Detail": json.dumps(detail),
            }
        ]
    )
    logger.info("Emitted %s with error_count=%s", detail_type, error_count)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Check completed",
                "error_count": error_count,
                "status": detail["status"],
            }
        ),
    }
