import os
import warnings
from typing import Optional

from .base import BaseDataLayer
from .utils import (
    queue_until_user_message as queue_until_user_message,  # TODO: Consider deprecating re-export.; Redundant alias tells type checkers to STFU.
)

_data_layer: Optional[BaseDataLayer] = None
_data_layer_initialized = False


def get_data_layer():
    global _data_layer, _data_layer_initialized

    if not _data_layer_initialized:
        if _data_layer:
            # Data layer manually set, warn user that this is deprecated.

            warnings.warn(
                "Setting data layer manually is deprecated. Use @data_layer instead.",
                DeprecationWarning,
            )

        else:
            from chainlit.config import config

            if config.code.data_layer:
                # When @data_layer is configured, call it to get data layer.
                _data_layer = config.code.data_layer()
            elif database_url := os.environ.get("DATABASE_URL"):
                from .chainlit_data_layer import ChainlitDataLayer

                bucket_name = os.environ.get("BUCKET_NAME")

                # AWS S3
                aws_region = os.getenv("APP_AWS_REGION")
                aws_access_key = os.getenv("APP_AWS_ACCESS_KEY")
                aws_secret_key = os.getenv("APP_AWS_SECRET_KEY")
                dev_aws_endpoint = os.getenv("DEV_AWS_ENDPOINT")
                is_using_s3 = bool(aws_access_key and aws_secret_key and aws_region)

                # Google Cloud Storage
                gcs_project_id = os.getenv("APP_GCS_PROJECT_ID")
                gcs_client_email = os.getenv("APP_GCS_CLIENT_EMAIL")
                gcs_private_key = os.getenv("APP_GCS_PRIVATE_KEY")
                is_using_gcs = bool(gcs_project_id)

                # Azure Storage
                azure_storage_account = os.getenv("APP_AZURE_STORAGE_ACCOUNT")
                azure_storage_key = os.getenv("APP_AZURE_STORAGE_ACCESS_KEY")
                is_using_azure = bool(azure_storage_account and azure_storage_key)

                storage_client = None

                if sum([is_using_s3, is_using_gcs, is_using_azure]) > 1:
                    warnings.warn(
                        "Multiple storage configurations detected. Please use only one."
                    )
                elif is_using_s3:
                    from chainlit.data.storage_clients.s3 import S3StorageClient

                    storage_client = S3StorageClient(
                        bucket=bucket_name,
                        region_name=aws_region,
                        aws_access_key_id=aws_access_key,
                        aws_secret_access_key=aws_secret_key,
                        endpoint_url=dev_aws_endpoint,
                    )
                elif is_using_gcs:
                    from chainlit.data.storage_clients.gcs import GCSStorageClient

                    storage_client = GCSStorageClient(
                        project_id=gcs_project_id,
                        client_email=gcs_client_email,
                        private_key=gcs_private_key,
                        bucket_name=bucket_name,
                    )
                elif is_using_azure:
                    from chainlit.data.storage_clients.azure_blob import (
                        AzureBlobStorageClient,
                    )

                    storage_client = AzureBlobStorageClient(
                        container_name=bucket_name,
                        storage_account=azure_storage_account,
                        storage_key=azure_storage_key,
                    )

                _data_layer = ChainlitDataLayer(
                    database_url=database_url, storage_client=storage_client
                )
            elif os.environ.get("LITERAL_API_KEY"):
                warnings.warn(
                    "The LiteralAI data layer has been removed because the service was shut down. "
                    "LITERAL_API_KEY is ignored and persistence is disabled. "
                    "Set DATABASE_URL to use the built-in data layer, or register a custom one with @cl.data_layer."
                )

        _data_layer_initialized = True

    return _data_layer
