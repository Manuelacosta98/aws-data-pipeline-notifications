#!/usr/bin/env python3
import os

import aws_cdk as cdk

from infra.eventbridge_stack import EventBridgeStack
from infra.chatbot_stack import ChatBotStack
from infra.github_oidc_role_stack import GithubOIDCRoleStack
from infra.slack_actions_stack import SlackActionsStack
from infra.redshift_monitor_stack import RedshiftMonitorStack
from infra.dms_monitor_stack import DmsMonitorStack

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION"),
)

app = cdk.App()


def _parse_csv_context(key: str) -> list[str]:
    raw = app.node.try_get_context(key) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# ----------------------------------------------------------------------
# Optional: inbound Slack slash-command endpoint for re-running jobs.
# Turn on with:
#   cdk synth -c enableSlackActions=true \
#             -c allowedGlueJobs=customer_etl_daily,inventory_sync \
#             -c allowedStateMachines=DataPipeline
# ----------------------------------------------------------------------
enable_slack_actions = bool(app.node.try_get_context("enableSlackActions"))

# ----------------------------------------------------------------------
# Optional: proactive monitors that emit custom EventBridge events for
# error sources AWS does not natively monitor (Redshift load errors via
# stl_load_errors; DMS table-level + field-level errors). Each monitor
# needs its own env vars; an unset env var skips that monitor.
#   cdk synth -c enableProactiveMonitors=true
# ----------------------------------------------------------------------
enable_proactive_monitors = bool(app.node.try_get_context("enableProactiveMonitors"))

redshift_cluster_id = os.getenv("REDSHIFT_CLUSTER_ID")
redshift_database = os.getenv("REDSHIFT_DATABASE")
redshift_db_user = os.getenv("REDSHIFT_DB_USER")
dms_task_arn = os.getenv("DMS_TASK_ARN")
dms_log_group = os.getenv("DMS_LOG_GROUP")
dms_log_hours_back = os.getenv("DMS_LOG_HOURS_BACK", "24")

deploy_redshift_monitor = (
    enable_proactive_monitors
    and redshift_cluster_id
    and redshift_database
    and redshift_db_user
)
deploy_dms_monitor = enable_proactive_monitors and dms_task_arn and dms_log_group

# Chatbot can be granted lambda:InvokeFunction on these names so users can
# run `@aws lambda invoke --function-name CheckRedshiftErrors` from Slack.
invokable_function_names: list[str] = []
if deploy_redshift_monitor:
    invokable_function_names.append("CheckRedshiftErrors")
if deploy_dms_monitor:
    invokable_function_names.append("CheckDMSErrors")

# ----------------------------------------------------------------------
# Stacks
# ----------------------------------------------------------------------

event_bridge = EventBridgeStack(
    app,
    "EventBridgeStack",
    env=env,
    description="EventBridge Stack for Data Pipeline Notifications",
    rerun_hints_enabled=enable_slack_actions,
)

ChatBotStack(
    app,
    "ChatBotStack",
    env=env,
    description="Chatbot Stack for Data Pipeline Notifications",
    sns_topic=event_bridge.sns_topic,
    slack_workspace_id=os.getenv("SLACK_WORKSPACE_ID"),
    slack_channel_id=os.getenv("SLACK_CHANNEL_ID"),
    invokable_function_names=invokable_function_names,
)

if enable_slack_actions:
    SlackActionsStack(
        app,
        "SlackActionsStack",
        env=env,
        description=(
            "Inbound Slack slash-command endpoint for re-running failed "
            "Glue / Step Functions jobs."
        ),
        allowed_glue_jobs=_parse_csv_context("allowedGlueJobs"),
        allowed_state_machines=_parse_csv_context("allowedStateMachines"),
    )

if deploy_redshift_monitor:
    RedshiftMonitorStack(
        app,
        "RedshiftMonitorStack",
        env=env,
        description="Proactive Redshift load-error monitor (custom.redshift events).",
        redshift_cluster_id=redshift_cluster_id,
        redshift_database=redshift_database,
        redshift_db_user=redshift_db_user,
    )

if deploy_dms_monitor:
    DmsMonitorStack(
        app,
        "DmsMonitorStack",
        env=env,
        description="Proactive DMS error monitor (custom.dms events).",
        dms_task_arn=dms_task_arn,
        dms_log_group=dms_log_group,
        dms_log_hours_back=dms_log_hours_back,
    )

# Opt-in: GitHub Actions OIDC deploy role.
github_org = os.getenv("GITHUB_ORG") or app.node.try_get_context("githubOrg")
github_repo = os.getenv("GITHUB_REPO") or app.node.try_get_context("githubRepo")
existing_oidc_arn = (
    os.getenv("EXISTING_OIDC_PROVIDER_ARN")
    or app.node.try_get_context("existingOidcProviderArn")
)
if github_org and github_repo:
    GithubOIDCRoleStack(
        app,
        "GithubOIDCRoleStack",
        env=env,
        description="GitHub Actions OIDC deploy role for this repository",
        github_org=github_org,
        github_repo=github_repo,
        existing_oidc_provider_arn=existing_oidc_arn,
    )

app.synth()
