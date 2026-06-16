import logging
import os
from dataclasses import dataclass

import kubernetes
from kubernetes import client as k8s_client

from anthropic import AnthropicVertex

from calunga_release_watcher.config import (
    AI_MAX_LOG_LINES,
    AI_MODEL,
    AI_TIMEOUT_SECONDS,
    AI_ANALYSIS_ENABLED,
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_CLOUD_REGION,
)

logger = logging.getLogger(__name__)

MAX_TOTAL_LOG_CHARS = 50_000

SYSTEM_PROMPT = """\
You are an expert CI/CD failure analyst for Tekton pipelines running in Konflux/RHTAP.

Analyze pipeline failures and classify them as:
- "fluke": Transient/intermittent failure that would likely pass on retry \
(network timeouts, image pull failures from registries like quay.io or registry.redhat.io, \
rate limits, DNS resolution failures, temporary infrastructure issues)
- "real": Genuine code or configuration problem that requires human attention \
(compilation errors, test assertion failures, missing dependencies, security policy violations, \
broken build scripts)
- "infra": Infrastructure problem outside the developer's control \
(cluster issues, storage problems, node failures, certificate expiration, OOM kills)
- "unknown": Insufficient information to determine the cause

Respond in EXACTLY this format with no additional text:
CLASSIFICATION: <fluke|real|infra|unknown>
CONFIDENCE: <high|medium|low>
FAILED_TASK: <name of the failed Tekton task, or "unknown">
ROOT_CAUSE: <1-2 sentence explanation of what went wrong>
SUGGESTION: <1 sentence actionable recommendation, or "none">\
"""

USER_PROMPT_TEMPLATE = """\
A Tekton pipeline has failed with state: {failure_state}

Here is the failure context from the Kubernetes cluster:

{context}

Analyze this failure. What went wrong, and is this a fluke, a real issue, \
or an infrastructure problem?\
"""


@dataclass
class FailureAnalysis:
    classification: str
    confidence: str
    root_cause: str
    suggestion: str
    failed_task: str


# ---------------------------------------------------------------------------
# Kubernetes client (lazy singleton)
# ---------------------------------------------------------------------------
_api_client: k8s_client.ApiClient | None = None


def _get_k8s_client() -> k8s_client.ApiClient:
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


# ---------------------------------------------------------------------------
# K8s context gathering
# ---------------------------------------------------------------------------


def _get_child_taskruns(body: dict, namespace: str) -> list[dict]:
    child_refs = body.get("status", {}).get("childReferences", [])
    if not child_refs:
        return []

    api = k8s_client.CustomObjectsApi(_get_k8s_client())
    taskruns = []
    for ref in child_refs:
        if ref.get("kind") != "TaskRun":
            continue
        try:
            tr = api.get_namespaced_custom_object(
                group="tekton.dev",
                version="v1",
                namespace=namespace,
                plural="taskruns",
                name=ref["name"],
            )
            taskruns.append(tr)
        except Exception:
            logger.warning("Failed to fetch TaskRun %s/%s", namespace, ref["name"])
    return taskruns


def _get_failed_taskruns(taskruns: list[dict]) -> list[dict]:
    failed = []
    for tr in taskruns:
        conditions = tr.get("status", {}).get("conditions", [])
        for c in conditions:
            if c.get("type") == "Succeeded" and c.get("status") == "False":
                failed.append(tr)
                break
    return failed


def _get_pod_logs(taskrun: dict, namespace: str, max_lines: int) -> dict[str, str]:
    pod_name = taskrun.get("status", {}).get("podName", "")
    if not pod_name:
        return {}

    core_v1 = k8s_client.CoreV1Api(_get_k8s_client())
    logs: dict[str, str] = {}

    try:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        containers = [c.name for c in (pod.spec.containers or [])]
        containers += [c.name for c in (pod.spec.init_containers or [])]
    except Exception:
        logger.warning("Failed to read pod %s/%s", namespace, pod_name)
        return {}

    for container_name in containers:
        try:
            log = core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container_name,
                tail_lines=max_lines,
            )
            if log:
                logs[container_name] = log
        except Exception:
            pass

    return logs


# ---------------------------------------------------------------------------
# Context assembly and truncation
# ---------------------------------------------------------------------------


def _truncate_context(context_parts: list[tuple[str, str]]) -> str:
    result = []
    budget = MAX_TOTAL_LOG_CHARS

    for label, content in context_parts:
        if budget <= 0:
            result.append(f"\n--- {label}: [TRUNCATED] ---\n")
            continue
        if len(content) > budget:
            content = content[-budget:]
            content = f"[... truncated, showing last {budget} chars ...]\n" + content
        result.append(f"\n--- {label} ---\n{content}")
        budget -= len(content)

    return "\n".join(result)


def _build_context(body: dict, info, detail: str) -> str:
    namespace = info.namespace or body.get("metadata", {}).get("namespace", "")
    context_parts: list[tuple[str, str]] = []

    context_parts.append(("Failure Detail", detail))

    conditions = body.get("status", {}).get("conditions", [])
    if conditions:
        cond = conditions[0]
        context_parts.append((
            "PipelineRun Condition",
            f"status={cond.get('status')} reason={cond.get('reason')} "
            f"message={cond.get('message', '')}",
        ))

    if not namespace:
        return _truncate_context(context_parts)

    taskruns = _get_child_taskruns(body, namespace)
    failed_taskruns = _get_failed_taskruns(taskruns)

    if not failed_taskruns and taskruns:
        for tr in taskruns:
            tr_name = tr.get("metadata", {}).get("name", "?")
            tr_conditions = tr.get("status", {}).get("conditions", [])
            if tr_conditions:
                c = tr_conditions[0]
                context_parts.append((
                    f"TaskRun: {tr_name}",
                    f"status={c.get('status')} reason={c.get('reason')} "
                    f"message={c.get('message', '')}",
                ))

    target_taskruns = failed_taskruns if failed_taskruns else taskruns[-3:]
    for tr in target_taskruns:
        tr_name = tr.get("metadata", {}).get("name", "?")
        pipeline_task = ""
        for ref in body.get("status", {}).get("childReferences", []):
            if ref.get("name") == tr.get("metadata", {}).get("name"):
                pipeline_task = ref.get("pipelineTaskName", "")
                break

        tr_label = pipeline_task or tr_name

        tr_conditions = tr.get("status", {}).get("conditions", [])
        if tr_conditions:
            c = tr_conditions[0]
            context_parts.append((
                f"TaskRun '{tr_label}' Condition",
                f"status={c.get('status')} reason={c.get('reason')} "
                f"message={c.get('message', '')}",
            ))

        tr_ns = tr.get("metadata", {}).get("namespace", namespace)
        pod_logs = _get_pod_logs(tr, tr_ns, AI_MAX_LOG_LINES)
        for container, log in pod_logs.items():
            context_parts.append((
                f"TaskRun '{tr_label}' / Container '{container}' "
                f"(last {AI_MAX_LOG_LINES} lines)",
                log,
            ))

    return _truncate_context(context_parts)


# ---------------------------------------------------------------------------
# Claude invocation and response parsing
# ---------------------------------------------------------------------------


def _parse_response(text: str) -> FailureAnalysis:
    lines = {}
    for line in text.strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            lines[key.strip().upper()] = value.strip()

    return FailureAnalysis(
        classification=lines.get("CLASSIFICATION", "unknown"),
        confidence=lines.get("CONFIDENCE", "low"),
        root_cause=lines.get("ROOT_CAUSE", "Unable to determine root cause"),
        suggestion=lines.get("SUGGESTION", ""),
        failed_task=lines.get("FAILED_TASK", "unknown"),
    )


def _call_claude(context: str, failure_state: str) -> FailureAnalysis | None:
    if not GOOGLE_CLOUD_PROJECT:
        logger.warning("GOOGLE_CLOUD_PROJECT not set — skipping AI analysis")
        return None

    client = AnthropicVertex(
        project_id=GOOGLE_CLOUD_PROJECT,
        region=GOOGLE_CLOUD_REGION,
    )

    response = client.messages.create(
        model=AI_MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    failure_state=failure_state,
                    context=context,
                ),
            },
        ],
        timeout=AI_TIMEOUT_SECONDS,
    )

    return _parse_response(response.content[0].text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_failure(body: dict, info, failure_state, detail: str) -> FailureAnalysis | None:
    if not AI_ANALYSIS_ENABLED or not GOOGLE_CLOUD_PROJECT:
        return None

    context = _build_context(body, info, detail)
    if not context.strip():
        logger.info("No context gathered for AI analysis")
        return None

    return _call_claude(context, failure_state.value)


def format_analysis(analysis: FailureAnalysis) -> str:
    emoji = {
        "fluke": "\U0001f504",   # 🔄
        "real": "\U0001f534",    # 🔴
        "infra": "\U0001f3d7️",  # 🏗️
        "unknown": "❓",     # ❓
    }.get(analysis.classification, "❓")

    confidence_emoji = {
        "high": "\U0001f7e2",    # 🟢
        "medium": "\U0001f7e1",  # 🟡
        "low": "\U0001f534",     # 🔴
    }.get(analysis.confidence, "\U0001f534")

    parts = [
        f"\n\n{emoji} *AI Analysis* ({confidence_emoji} {analysis.confidence} confidence)",
        f"*Classification:* {analysis.classification}",
        f"*Failed Task:* {analysis.failed_task}",
        f"*Root Cause:* {analysis.root_cause}",
    ]
    if analysis.suggestion and analysis.suggestion.lower() != "none":
        parts.append(f"*Suggestion:* {analysis.suggestion}")

    return "\n".join(parts)
