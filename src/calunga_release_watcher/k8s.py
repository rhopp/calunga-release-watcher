import logging
import os

import kubernetes
from kubernetes import client as k8s_client

logger = logging.getLogger(__name__)

_api_client: k8s_client.ApiClient | None = None


def get_k8s_client() -> k8s_client.ApiClient:
    global _api_client
    if _api_client is not None:
        return _api_client

    token = os.environ.get("K8S_TOKEN", "")
    server = os.environ.get("K8S_API_URL", "")

    if token and server:
        configuration = kubernetes.client.Configuration()
        configuration.host = server
        configuration.api_key = {"authorization": f"Bearer {token}"}
        configuration.verify_ssl = False
        _api_client = k8s_client.ApiClient(configuration)
    else:
        kubernetes.config.load_incluster_config()
        _api_client = k8s_client.ApiClient()

    return _api_client
