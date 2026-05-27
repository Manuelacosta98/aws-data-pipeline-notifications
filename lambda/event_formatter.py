"""Turn raw EventBridge events into AWS Chatbot custom-format payloads.

Each event source (native AWS or custom proactive monitor) is handled by a
dedicated method. Dispatch is driven by ``_dispatch``, which makes adding
a new source a one-method change instead of an ``if/elif`` edit.

For sources that need richer context than the EventBridge event provides
(e.g. resolving a QuickSight dataset ID to a human-readable name), the
relevant ``_format_*`` method actively enriches via boto3 inside the
``_enrich_*`` helper. Helpers are easy to monkeypatch in tests.

Severity is computed from the event detail and surfaces in:
- the leading emoji (🚨 / ⚠️ / ✅ / ℹ️),
- the Chatbot ``keywords`` list (useful for downstream Slack filters),
- the title verb ("Failed" vs. "Succeeded").

AWS Chatbot's custom format does not give us a colored attachment bar —
that requires bypassing Chatbot and posting straight to a Slack webhook —
so the emoji + structured keywords are how we convey severity here.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Callable


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    SUCCESS = "success"
    INFO = "info"


_SEVERITY_EMOJI: dict[Severity, str] = {
    Severity.ERROR: "🚨",
    Severity.WARNING: "⚠️",
    Severity.SUCCESS: "✅",
    Severity.INFO: "ℹ️",
}


# Each per-source method returns this 4-tuple.
FormatResult = tuple[str, str, str, Severity]  # (title, description, log_url, severity)


# ----------------------------------------------------------- DMS log cleanup

# DMS CloudWatch log lines look like:
#   "2026-03-03T17:17:47 [SOURCE_UNLOAD   ]E:  value exceeds length (file_unload.c:628)"
# After stripping noise:
#   "value exceeds length"
_DMS_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+")
_DMS_COMPONENT_RE = re.compile(r"^\[[\w\s]+\][EWI]:\s*")
_DMS_FILE_REF_RE = re.compile(r"\s*\([\w_]+\.c:\d+\)\s*$")


def clean_dms_log_message(raw_message: str) -> str:
    """Strip DMS-specific noise from a CloudWatch log line for Slack display.

    Removes the leading timestamp (we surface it separately), the
    component+level prefix (``[SOURCE_UNLOAD   ]E:  ``), and the trailing
    internal file reference (``(file_unload.c:628)``). The result is a
    one-line, human-readable message.
    """
    msg = raw_message.strip()
    msg = _DMS_TIMESTAMP_RE.sub("", msg)
    msg = _DMS_COMPONENT_RE.sub("", msg)
    msg = _DMS_FILE_REF_RE.sub("", msg)
    return msg.strip()


# ------------------------------------------------------------------ formatter


class EventFormatter:
    """Format an EventBridge event for AWS Chatbot.

    Parameters
    ----------
    region:
        The AWS region used to build deep-links into the AWS console.
    rerun_hints_enabled:
        When ``True``, Glue and Step Functions failure messages append a
        ``/pipeline rerun ...`` slash-command hint so the user can re-run
        the failed resource directly from Slack.
    """

    def __init__(self, region: str, rerun_hints_enabled: bool = False) -> None:
        self.region = region
        self.rerun_hints_enabled = rerun_hints_enabled

    # ------------------------------------------------------------------ public

    def format(self, event: dict[str, Any]) -> dict[str, Any]:
        source = event.get("source", "")
        detail_type = event.get("detail-type", "")

        handler = self._dispatch(source, detail_type)
        title, description, log_url, severity = handler(event)

        emoji = _SEVERITY_EMOJI[severity]
        return {
            "version": "1.0",
            "source": "custom",
            "content": {
                "textType": "client-markdown",
                "title": f"{emoji} {title}",
                "description": f"{description}\n\n<{log_url}|View in AWS Console>",
                "nextSteps": ["Check the AWS Console for more details"],
                "keywords": [source, severity.value, "data-pipeline"],
            },
        }

    # ----------------------------------------------------------------- private

    def _rerun_hint(self, kind: str, name: str) -> str:
        if not self.rerun_hints_enabled:
            return ""
        return f"\n\n🔁 To re-run: `/pipeline rerun {kind} {name}`"

    def _dispatch(
        self, source: str, detail_type: str
    ) -> Callable[[dict[str, Any]], FormatResult]:
        if source == "aws.states":
            return self._format_step_functions
        if source == "aws.glue":
            return self._format_glue
        if source == "aws.dms":
            if detail_type == "DMS Table State Change":
                return self._format_dms_table
            return self._format_dms_task
        if source == "aws.quicksight":
            return self._format_quicksight
        if source == "custom.redshift":
            return self._format_custom_redshift
        if source == "custom.dms":
            return self._format_custom_dms
        return self._format_unknown

    # -------------------------------------------------- native AWS formatters

    def _format_step_functions(self, event: dict[str, Any]) -> FormatResult:
        detail = event.get("detail", {})
        status = detail.get("status", "Unknown")
        name = detail.get("name", "Unknown")
        execution_arn = detail.get("executionArn", "")
        state_machine_name = detail.get("stateMachineArn", "").split(":")[-1]

        severity = Severity.SUCCESS if status == "SUCCEEDED" else Severity.ERROR
        verb = "Succeeded" if severity is Severity.SUCCESS else "Failed"
        title = f"Step Function {verb}"
        description = (
            f"Execution: {name}\n"
            f"Status: {status}\n"
            f"State Machine: {state_machine_name}"
        )
        if severity is Severity.ERROR and state_machine_name:
            description += self._rerun_hint("sfn", state_machine_name)
        encoded_arn = execution_arn.replace(":", "%3A").replace("/", "%2F")
        log_url = (
            f"https://{self.region}.console.aws.amazon.com/states/home"
            f"?region={self.region}#/executions/details/{encoded_arn}"
        )
        return title, description, log_url, severity

    def _format_glue(self, event: dict[str, Any]) -> FormatResult:
        detail = event.get("detail", {})
        job_name = detail.get("jobName", "Unknown")
        state = detail.get("state", "Unknown")
        message = detail.get("message", "None")
        title = "Glue Job Failed"
        description = f"Job: {job_name}\nState: {state}\nError Message: {message}"
        description += self._rerun_hint("glue", job_name)
        log_url = (
            f"https://{self.region}.console.aws.amazon.com/gluestudio/home"
            f"?region={self.region}#/editor/job/{job_name}/runs"
        )
        return title, description, log_url, Severity.ERROR

    def _format_dms_task(self, event: dict[str, Any]) -> FormatResult:
        detail = event.get("detail", {})
        task_id = detail.get("task-id", "Unknown")
        state = detail.get("state", "Unknown")
        title = "DMS Replication Task Failed"
        description = f"Task: {task_id}\nState: {state}"
        log_url = (
            f"https://{self.region}.console.aws.amazon.com/dms/v2/home"
            f"?region={self.region}#taskDetails/{task_id}"
        )
        return title, description, log_url, Severity.ERROR

    def _format_dms_table(self, event: dict[str, Any]) -> FormatResult:
        detail = event.get("detail", {})
        task_id = detail.get("task-id", "Unknown")
        table = detail.get("table-name", "Unknown")
        state = detail.get("state", "Unknown")
        is_recoverable = "issue" in state.lower()
        severity = Severity.WARNING if is_recoverable else Severity.ERROR
        verb = "Completed With Issues" if is_recoverable else "Errored"
        title = f"DMS Table {verb}"
        description = f"Task: {task_id}\nTable: {table}\nState: {state}"
        log_url = (
            f"https://{self.region}.console.aws.amazon.com/dms/v2/home"
            f"?region={self.region}#taskDetails/{task_id}"
        )
        return title, description, log_url, severity

    def _format_quicksight(self, event: dict[str, Any]) -> FormatResult:
        """SPICE ingestion failure with active enrichment via the QuickSight API.

        The EventBridge event only gives us the dataset ID (not human-readable)
        and a generic error type. We call ``describe_data_set`` to resolve the
        dataset name and ``describe_ingestion`` to get the detailed error
        message, which is usually a specific SQL error or row-count mismatch
        rather than the generic event payload.
        """
        detail = event.get("detail", {})
        dataset_id = detail.get("dataSetId", "Unknown")
        ingestion_id = detail.get("ingestionId", "")
        ingestion_status = detail.get("ingestionStatus", "Unknown")
        account_id = event.get("account", "")
        failure_time = event.get("time", "Unknown")

        error_info = detail.get("errorInfo", {}) or {}
        fallback_message = error_info.get("message", "N/A")
        fallback_type = error_info.get("type", "N/A")

        dataset_name, error_message, error_type = self._enrich_quicksight(
            dataset_id=dataset_id,
            ingestion_id=ingestion_id,
            account_id=account_id,
            fallback_message=fallback_message,
            fallback_type=fallback_type,
        )

        title = f'"{dataset_name}" failed to refresh'
        description = (
            f"Error: {error_message}\n"
            f"Error Type: {error_type}\n"
            f"Status: {ingestion_status}\n"
            f"Time of failure: {failure_time}"
        )
        log_url = (
            f"https://{self.region}.quicksight.aws.amazon.com/sn/data-sets/{dataset_id}"
        )
        return title, description, log_url, Severity.ERROR

    def _enrich_quicksight(
        self,
        *,
        dataset_id: str,
        ingestion_id: str,
        account_id: str,
        fallback_message: str,
        fallback_type: str,
    ) -> tuple[str, str, str]:
        """Resolve dataset name and detailed ingestion error via boto3.

        Returns ``(dataset_name, error_message, error_type)``. Falls back to
        the values from the EventBridge event when the API call fails, so a
        permissions hiccup degrades gracefully into a less-informative alert
        rather than crashing the Lambda.

        Imported lazily so unit tests that monkeypatch this method don't
        force a boto3 import.
        """
        try:
            import boto3  # local import keeps the module testable without AWS deps
        except ImportError:
            return dataset_id, fallback_message, fallback_type

        client = boto3.client("quicksight", region_name=self.region)

        dataset_name = dataset_id
        try:
            ds_info = client.describe_data_set(
                AwsAccountId=account_id, DataSetId=dataset_id
            )
            dataset_name = ds_info.get("DataSet", {}).get("Name", dataset_id)
        except Exception as exc:  # noqa: BLE001 — best-effort enrichment
            print(f"describe_data_set failed: {exc}")

        error_message = fallback_message
        error_type = fallback_type
        if ingestion_id:
            try:
                ing_info = client.describe_ingestion(
                    AwsAccountId=account_id,
                    DataSetId=dataset_id,
                    IngestionId=ingestion_id,
                )
                ing_error = ing_info.get("Ingestion", {}).get("ErrorInfo", {}) or {}
                error_message = ing_error.get("Message", error_message)
                error_type = ing_error.get("Type", error_type)
            except Exception as exc:  # noqa: BLE001 — best-effort enrichment
                print(f"describe_ingestion failed: {exc}")

        return dataset_name, error_message, error_type

    # --------------------------------------------- proactive monitor formatters

    def _format_custom_redshift(self, event: dict[str, Any]) -> FormatResult:
        """Render a structured Redshift load-error report emitted by the monitor Lambda."""
        detail = event.get("detail", {})
        cluster = detail.get("cluster", "Unknown")
        database = detail.get("database", "Unknown")
        error_count = detail.get("error_count", 0)
        check_period = detail.get("check_period", "recent period")
        status = detail.get("status", "unknown")
        error_details = detail.get("error_details", []) or []

        if status == "success" or error_count == 0:
            title = "Redshift Load Check — No Errors"
            description = (
                f"Cluster: {cluster}\n"
                f"Database: {database}\n"
                f"Status: All clear — no load errors {check_period}"
            )
            severity = Severity.SUCCESS
        else:
            title = "Redshift Load Errors Detected"
            description = (
                f"Cluster: {cluster}\n"
                f"Database: {database}\n"
                f"Total errors: {error_count} ({check_period})\n"
            )
            if error_details:
                description += "\n📋 Recent errors (showing up to 10):\n"
                for idx, err in enumerate(error_details, 1):
                    description += (
                        f"\n{idx}. Time: {err.get('starttime', 'N/A')}\n"
                        f"   File: {err.get('filename', 'N/A')}\n"
                        f"   Reason: {err.get('err_reason', 'N/A')}\n"
                        f"   Column: {err.get('colname', 'N/A')}\n"
                    )
            severity = Severity.ERROR

        log_url = (
            f"https://{self.region}.console.aws.amazon.com/redshiftv2/home"
            f"?region={self.region}#cluster-details?cluster={cluster}"
        )
        return title, description, log_url, severity

    def _format_custom_dms(self, event: dict[str, Any]) -> FormatResult:
        """Render a structured DMS error report emitted by the monitor Lambda."""
        detail = event.get("detail", {})
        log_group = detail.get("log_group", "")
        hours_back = detail.get("hours_back", 24)
        status = detail.get("status", "unknown")
        error_tables = detail.get("error_tables", []) or []
        field_errors = detail.get("field_errors", []) or []
        total_table_errors = detail.get("total_table_errors", 0)
        total_field_errors = detail.get("total_field_errors", 0)

        if status == "success":
            title = "DMS Check — No Errors"
            description = (
                f"Log group: {log_group}\n"
                f"Window: last {hours_back}h\n"
                f"Status: All clear — no table errors or `]E:` log entries"
            )
            severity = Severity.SUCCESS
        else:
            title = "DMS Load Errors Detected"
            description = (
                f"Log group: {log_group}\n"
                f"Window: last {hours_back}h\n"
                f"Tables with errors: {total_table_errors} | "
                f"`]E:` log entries: {total_field_errors}\n"
            )

            if error_tables:
                description += "\n📋 Tables with load errors:\n"
                for t in error_tables:
                    error_rows = t.get("full_load_error_rows", 0)
                    total_rows = t.get("full_load_rows", 0)
                    row_info = (
                        f"Error rows: {error_rows} / {total_rows} total"
                        if total_rows > 0
                        else "Error detected at source (SOURCE_UNLOAD)"
                    )
                    description += (
                        f"\n  • {t.get('schema', 'N/A')}.{t.get('table', 'N/A')}\n"
                        f"    State: {t.get('state', 'N/A')} | {row_info}\n"
                    )

            if field_errors:
                description += "\n🔍 Field errors from logs (up to 10):\n"
                for idx, err in enumerate(field_errors, 1):
                    clean_msg = clean_dms_log_message(err.get("message", "N/A"))
                    description += (
                        f"\n  {idx}. [{err.get('timestamp', 'N/A')}]\n"
                        f"     {clean_msg}\n"
                    )
            severity = Severity.ERROR

        encoded_log_group = log_group.replace("/", "$252F")
        log_url = (
            f"https://{self.region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={self.region}#logsV2:log-groups/log-group/{encoded_log_group}"
        )
        return title, description, log_url, severity

    def _format_unknown(self, event: dict[str, Any]) -> FormatResult:
        detail = event.get("detail", {})
        title = "Pipeline Alert"
        description = json.dumps(detail, indent=2)
        log_url = (
            f"https://{self.region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={self.region}#logsV2:logs-insights"
        )
        return title, description, log_url, Severity.INFO
