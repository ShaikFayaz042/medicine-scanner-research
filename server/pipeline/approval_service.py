"""Compatibility wrapper for approval service imports."""

from server.config import AWS_REGION, S3_BUCKET_NAME
from server.services.workflow_approval_service import approve_run, reject_run

# Preserve the old module-level constants that existing tests monkeypatch.
AWS_REGION = AWS_REGION
S3_BUCKET_NAME = S3_BUCKET_NAME
boto3 = __import__("boto3")

__all__ = ["approve_run", "reject_run", "AWS_REGION", "S3_BUCKET_NAME", "boto3"]
