"""Adaptador ObjectStore S3-compatible (MinIO). Cifra el payload en reposo. Ref: ADR-06, 1.DATA.4."""
from __future__ import annotations

from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from app.adapters.object_store.interface import ObjectStore
from app.core.crypto import ObjectCipher


def build_s3_client(
    *,
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    region: str,
) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


class S3ObjectStore(ObjectStore):
    def __init__(
        self,
        *,
        bucket: str,
        cipher: ObjectCipher,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        self._cipher = cipher
        self._region = region
        self._client = client or build_s3_client(
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            try:
                kwargs: dict[str, Any] = {"Bucket": self._bucket}
                if self._region != "us-east-1":
                    kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self._region}
                self._client.create_bucket(**kwargs)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                    raise

    def put(self, *, key: str, content: bytes, content_type: str) -> None:
        encrypted = self._cipher.encrypt(content)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=encrypted,
            ContentType="application/octet-stream",
            Metadata={"original-content-type": content_type},
        )

    def get(self, *, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise KeyError(key) from exc
            raise
        return self._cipher.decrypt(response["Body"].read())
