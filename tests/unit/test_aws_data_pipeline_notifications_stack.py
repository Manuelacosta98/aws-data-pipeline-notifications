import aws_cdk as core
import aws_cdk.assertions as assertions

from aws_data_pipeline_notifications.aws_data_pipeline_notifications_stack import AwsDataPipelineNotificationsStack

# example tests. To run these tests, uncomment this file along with the example
# resource in aws_data_pipeline_notifications/aws_data_pipeline_notifications_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = AwsDataPipelineNotificationsStack(app, "aws-data-pipeline-notifications")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
