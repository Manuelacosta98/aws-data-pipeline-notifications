"""AWS Lambda entry point for the pipeline-notifications formatter.

The handler is intentionally thin: it delegates all per-source formatting
to :class:`event_formatter.EventFormatter`, then publishes the resulting
Chatbot payload to the SNS topic referenced by ``SNS_TOPIC_ARN``.

Splitting handler from formatter has two benefits:

1. ``EventFormatter`` is trivially unit-testable without mocking Lambda.
2. Adding a new AWS source means adding a method to ``EventFormatter``,
   not editing the I/O glue in this file.
"""

import json
import os

import boto3

from event_formatter import EventFormatter

# Module-level clients so they are reused across warm invocations.
_sns = boto3.client("sns")
_formatter = EventFormatter(
    region=os.environ.get("AWS_REGION", "us-east-1"),
    rerun_hints_enabled=os.environ.get("RERUN_HINTS_ENABLED", "").lower() == "true",
)


def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    payload = _formatter.format(event)
    subject = (
        f"Data Pipeline Alert - {event.get('source', 'unknown')} - "
        f"{event.get('detail-type', '')}"
    )[:100]  # SNS subject is capped at 100 characters.

    _sns.publish(
        TopicArn=os.environ["SNS_TOPIC_ARN"],
        Message=json.dumps(payload),
        Subject=subject,
    )

    print(f"Published Chatbot payload to {os.environ['SNS_TOPIC_ARN']}")
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Notification sent"}),
    }
