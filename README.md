# aws-data-pipeline-notifications
This project provides a CDK stack to set up event-driven notifications for AWS data pipeline errors and failures. It leverages Amazon EventBridge to capture error events from DMS, Glue, and Step Functions, then routes them to an SNS topic integrated with AWS Chatbot for Slack. Ideal for ensuring operational visibility and quick response to data pipeline issues.
