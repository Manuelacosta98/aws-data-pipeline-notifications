# AWS Data Pipeline Notifications

[![AWS CDK](https://img.shields.io/badge/AWS%20CDK-2.x-orange.svg)](https://aws.amazon.com/cdk/)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Event-driven notification system for AWS data pipeline monitoring and alerting**

This CDK project provides a robust, serverless notification system for monitoring AWS data pipeline errors and failures. It automatically captures error events from DMS, Glue, and Step Functions using Amazon EventBridge, then routes them to SNS topics integrated with AWS Chatbot for real-time Slack notifications.

## 🏗️ Architecture

```mermaid
flowchart LR
  A["AWS Services<br/>(DMS, Glue, Step Fn)"] --> B["EventBridge<br/>Rules"]
  B --> C["SNS<br/>Topics"]
  C --> D["AWS Chatbot<br/>(Slack)"]
```

The system is deployed as separate CDK stacks:
- **EventBridgeStack**: Manages EventBridge rules and SNS topics
- **ChatBotStack**: Handles AWS Chatbot configuration for Slack integration

## ✨ Features

- **Multi-Service Monitoring**: Captures errors from DMS, AWS Glue, and Step Functions
- **Real-time Notifications**: Instant Slack alerts via AWS Chatbot integration
- **Event-Driven Architecture**: Uses EventBridge for scalable, serverless event processing
- **Infrastructure as Code**: Fully defined using AWS CDK for reproducible deployments
- **Cost-Effective**: Pay-per-use serverless architecture with minimal overhead

## 🚀 Quick Start

### Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.8 or higher
- Node.js (for AWS CDK)
- AWS CDK v2.x installed globally

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Manuelacosta98/aws-data-pipeline-notifications.git
   cd aws-data-pipeline-notifications
   ```

2. **Set up environment configuration**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` file with your AWS configuration:
   ```
   CDK_DEFAULT_ACCOUNT=your-account-id
   CDK_DEFAULT_REGION=your-preferred-region
   AWS_REGION=your-preferred-region
   AWS_ACCESS_KEY_ID=your-access-key
   AWS_SECRET_ACCESS_KEY=your-secret-key
   SLACK_WORKSPACE_ID=your-slack-workspace-id
   SLACK_CHANNEL_ID=your-slack-channel-id
   ```

3. **Install dependencies using pipenv**
   ```bash
   pipenv install
   pipenv install --dev  # For development dependencies
   ```

4. **Bootstrap CDK (first time only)**
   ```bash
   cdk bootstrap
   ```

### Deployment

1. **Synthesize CloudFormation template**
   ```bash
   cdk synth
   ```

2. **Deploy the stack**
   ```bash
   cdk deploy
   ```

3. **Configure Slack Integration** (Pre-deployment)
   - Set your Slack workspace and channel IDs in the `.env` file
   - The ChatBotStack will automatically configure AWS Chatbot with SNS integration

## 🛠️ Configuration

### Environment Configuration

The application uses environment variables loaded from the `.env` file:

```bash
CDK_DEFAULT_ACCOUNT=your-account-id
CDK_DEFAULT_REGION=your-preferred-region
AWS_REGION=your-preferred-region
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
SLACK_WORKSPACE_ID=your-slack-workspace-id
SLACK_CHANNEL_ID=your-slack-channel-id
```

### Customization

The stacks can be customized by modifying the respective files:

**EventBridge Rules** (`infra/eventbridge_stack.py`):
- Add additional AWS services to monitor
- Configure custom EventBridge rules and patterns
- Modify SNS topic configuration

**Chatbot Configuration** (`infra/chatbot_stack.py`):
- Update Slack workspace and channel IDs
- Configure IAM permissions
- Add multiple notification channels

## 📁 Project Structure

```
aws-data-pipeline-notifications/
├── app.py                           # CDK app entry point
├── cdk.json                         # CDK configuration
├── .env.example                     # Environment variables template
├── .env                            # Environment variables (create from .env.example)
├── Pipfile                         # Pipenv configuration
├── requirements.txt                # Python dependencies
├── requirements-dev.txt            # Development dependencies
├── infra/
│   ├── __init__.py
│   ├── eventbridge_stack.py        # EventBridge rules and SNS topics
│   └── chatbot_stack.py            # AWS Chatbot configuration
└── tests/
    ├── __init__.py
    └── unit/
        ├── __init__.py
        └── test_aws_data_pipeline_notifications_stack.py
```

## 🧪 Testing

Run the test suite:

```bash
python -m pytest tests/
```

For test coverage:

```bash
python -m pytest --cov=aws_data_pipeline_notifications tests/
```

## 📚 CDK Commands

| Command | Description |
|---------|-------------|
| `cdk list` | List all stacks in the app |
| `cdk synth` | Synthesize CloudFormation template |
| `cdk deploy` | Deploy stack to AWS |
| `cdk diff` | Compare deployed stack with current state |
| `cdk destroy` | Remove the deployed stack |
| `cdk docs` | Open CDK documentation |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Issues**: Report bugs and request features via [GitHub Issues](https://github.com/Manuelacosta98/aws-data-pipeline-notifications/issues)
- **Documentation**: Check the [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- **Community**: Join the [AWS CDK Community](https://github.com/aws/aws-cdk)

## 🏷️ Tags

`aws` `cdk` `data-pipeline` `notifications` `eventbridge` `sns` `chatbot` `slack` `monitoring` `serverless`
