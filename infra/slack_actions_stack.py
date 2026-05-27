"""Inbound Slack slash-command endpoint for re-running failed pipeline jobs.

This closes the loop on the alerting flow: when a Glue job or Step Functions
execution fails, the user can re-run it from Slack with one command, without
ever opening the AWS console.

Architecture:
    Slack (/pipeline command)
        ↓  HTTPS POST with X-Slack-Signature header
    API Gateway (HTTP API)
        ↓
    Lambda (slack_command_handler)
        ↓  verifies HMAC signature, checks allowlist, audits user_id
    boto3 → Glue.StartJobRun  /  StepFunctions.StartExecution

Security model:
    1. Slack signing secret lives in Secrets Manager; the Lambda reads it
       lazily and caches it for 5 minutes (so rotations are picked up fast).
    2. Every request is HMAC-SHA256-verified against the Slack timestamp
       header — replays older than 5 minutes are rejected.
    3. Allowlists for Glue job names and Step Functions state machines are
       passed in as Lambda environment variables and enforced *and* baked
       into the IAM policy's `resources`. The policy is the real boundary;
       the env-var check just gives a friendlier Slack error.
    4. The Slack `user_id` of every command invocation is logged for audit.
"""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class SlackActionsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        allowed_glue_jobs: list[str] | None = None,
        allowed_state_machines: list[str] | None = None,
        signing_secret_name: str = "aws-data-pipeline-notifications/slack-signing-secret",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        allowed_glue_jobs = allowed_glue_jobs or []
        allowed_state_machines = allowed_state_machines or []

        # ------------------------------------------------------------------ secret
        # The Slack signing secret. The value is set out-of-band by an operator
        # after deployment (Console → Secrets Manager → Retrieve secret value →
        # paste the signing secret from the Slack app's Basic Information page).
        signing_secret = secretsmanager.Secret(
            self,
            "SlackSigningSecret",
            secret_name=signing_secret_name,
            description=(
                "Slack app signing secret used to HMAC-verify incoming slash "
                "commands. Set the value manually in the AWS console after "
                "deployment."
            ),
        )

        # ------------------------------------------------------------------ Lambda
        handler = _lambda.Function(
            self,
            "SlackCommandHandler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="slack_command_handler.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(10),
            log_retention=logs.RetentionDays.ONE_MONTH,
            environment={
                "SLACK_SIGNING_SECRET_ARN": signing_secret.secret_arn,
                "ALLOWED_GLUE_JOBS": ",".join(allowed_glue_jobs),
                "ALLOWED_STATE_MACHINES": ",".join(allowed_state_machines),
            },
        )

        signing_secret.grant_read(handler)

        # ------------------------------------------------------------------ IAM
        # Scope the IAM policy to the named jobs / state machines where possible.
        # If the allowlist is empty we fall back to "*" so the deployer can
        # widen access later via the env-var list; the env-var check then
        # provides the runtime guardrail.
        glue_resources = (
            [
                f"arn:aws:glue:{self.region}:{self.account}:job/{name}"
                for name in allowed_glue_jobs
            ]
            if allowed_glue_jobs
            else [f"arn:aws:glue:{self.region}:{self.account}:job/*"]
        )
        handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns"],
                resources=glue_resources,
            )
        )

        sfn_resources = (
            [
                f"arn:aws:states:{self.region}:{self.account}:stateMachine:{name}"
                for name in allowed_state_machines
            ]
            if allowed_state_machines
            else [f"arn:aws:states:{self.region}:{self.account}:stateMachine:*"]
        )
        handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "states:StartExecution",
                    "states:DescribeStateMachine",
                ],
                resources=sfn_resources,
            )
        )

        # ------------------------------------------------------------------ API
        api = apigwv2.HttpApi(
            self,
            "SlackActionsApi",
            description="Inbound endpoint for Slack slash commands.",
        )
        api.add_routes(
            path="/slack/commands",
            methods=[apigwv2.HttpMethod.POST],
            integration=apigwv2_integrations.HttpLambdaIntegration(
                "SlackCommandIntegration", handler
            ),
        )

        # Expose the public URL so the operator can paste it into the Slack app's
        # slash command configuration.
        CfnOutput(
            self,
            "SlackCommandsUrl",
            value=f"{api.api_endpoint}/slack/commands",
            description=(
                "Paste this URL into the Slack app's Slash Commands "
                "configuration → Request URL."
            ),
        )
        CfnOutput(
            self,
            "SlackSigningSecretArn",
            value=signing_secret.secret_arn,
            description=(
                "ARN of the Secrets Manager entry that holds the Slack signing "
                "secret. Retrieve and set its value once, post-deploy."
            ),
        )
