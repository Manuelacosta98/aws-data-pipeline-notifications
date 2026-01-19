import json
import boto3
import os

sns = boto3.client('sns')

def lambda_handler(event, context):
    """Format EventBridge events for Slack notifications"""

    print(f"Received event: {json.dumps(event)}")
    
    detail = event.get('detail', {})
    source = event.get('source', '')
    detail_type = event.get('detail-type', '')
    region = os.environ.get('AWS_REGION', 'us-east-1')
    
    # Create Chatbot-compatible message structure with log URLs
    if source == 'aws.states':
        title = "🚨 Step Function Failed"
        execution_arn = detail.get('executionArn', '')
        state_machine_name = detail.get('stateMachineArn', '').split(':')[-1]
        description = f"Execution: {detail.get('name', 'Unknown')}\nStatus: {detail.get('status', 'Unknown')}\nState Machine: {state_machine_name}"
        log_url = f"https://{region}.console.aws.amazon.com/states/home?region={region}#/executions/details/{execution_arn.replace(':', '%3A').replace('/', '%2F')}"
        
    elif source == 'aws.dms':
        title = "🚨 DMS Task Failed"
        task_id = detail.get('task-id', 'Unknown')
        description = f"Task: {task_id}\nState: {detail.get('state', 'Unknown')}"
        log_url = f"https://{region}.console.aws.amazon.com/dms/v2/home?region={region}#taskDetails/{task_id}"
        
    elif source == 'aws.glue':
        title = "🚨 Glue Job Failed"
        job_name = detail.get('jobName', 'Unknown')
        job_run_id = detail.get('jobRunId', '')
        description = f"Job: {job_name}\nState: {detail.get('state', 'Unknown')}\nError Message: {detail.get('message', 'None')}"
        log_url = f"https://{region}.console.aws.amazon.com/gluestudio/home?region={region}#/editor/job/{job_name}/runs"
            
    else:
        title = "🚨 Pipeline Alert"
        description = json.dumps(detail, indent=2)
        log_url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:logs-insights"
    
    # Create Chatbot message with action button
    chatbot_message = {
        "version": "1.0",
        "source": "custom",
        "content": {
            "textType": "client-markdown",
            "title": title,
            "description": f"{description}\n\n<{log_url}|View Logs in AWS Console>",
            "nextSteps": ["Check AWS Console for more details"],
            "keywords": [source, "failure", "alert"]
        }
    }
    
    # Publish formatted message to SNS
    subject = f"Data Pipeline Alert - {source} - {detail_type}"
    sns.publish(
        TopicArn=os.environ['SNS_TOPIC_ARN'],
        Message=json.dumps(chatbot_message),
        Subject=subject
    )

    print(f"Published Chatbot message to SNS topic: {os.environ['SNS_TOPIC_ARN']}")
    
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Notification sent'})
    }