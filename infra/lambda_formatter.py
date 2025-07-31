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
    
    # Create Chatbot-compatible message structure
    if source == 'aws.states':
        title = "🚨 Step Function Failed"
        description = f"Execution: {detail.get('name', 'Unknown')}\nStatus: {detail.get('status', 'Unknown')}\nState Machine: {detail.get('stateMachineArn', '').split(':')[-1]}"
        
    elif source == 'aws.dms':
        title = "🚨 DMS Task Failed"
        description = f"Task: {detail.get('task-id', 'Unknown')}\nState: {detail.get('state', 'Unknown')}"
        
    elif source == 'aws.glue':
        title = "🚨 Glue Job Failed"
        description = f"Job: {detail.get('jobName', 'Unknown')}\nState: {detail.get('state', 'Unknown')}\nError Message: {detail.get('message', 'None')}"
        
    else:
        title = "🚨 Pipeline Alert"
        description = json.dumps(detail, indent=2)
    
    # Create Chatbot-compatible message
    chatbot_message = {
        "version": "1.0",
        "source": "custom",
        "content": {
            "textType": "client-markdown",
            "title": title,
            "description": description,
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