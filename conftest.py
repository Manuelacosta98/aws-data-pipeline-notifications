"""Pytest bootstrap shared across the whole test suite.

We add the project's `lambda/` directory to sys.path so the Lambda handler
and its supporting modules can be imported as top-level modules
(`import lambda_formatter`, `from event_formatter import EventFormatter`).
This mirrors how the AWS Lambda runtime sees them at execution time —
the asset directory is on `sys.path`, not a Python package — so tests
exercise the exact same import surface as production.

`lambda` is a Python keyword, so we cannot use `import lambda.lambda_formatter`;
the sys.path injection is what makes the directory usable.
"""

import os
import sys
from pathlib import Path

_LAMBDA_DIR = Path(__file__).parent / "lambda"
if str(_LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(_LAMBDA_DIR))

# AWS Lambda always sets AWS_REGION at runtime; locally we set a default so
# the handler module's top-level `boto3.client("sns")` call doesn't trip
# NoRegionError at import time. Individual tests can override with monkeypatch.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
