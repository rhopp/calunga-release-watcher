"""
E2E tests for analyze_failure using real Vertex AI (Claude) with fixture data
from kubearchive.

Each test loads a complete fixture chain (body + test PLRs + TaskRuns + pod logs),
mocks k8s API calls to serve this canned data, then sends the assembled context
to a real Claude model via Vertex AI. Assertions are soft — checking classification
falls within an acceptable set rather than exact matching.

Requires:
  - ANTHROPIC_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT env var
  - CLOUD_ML_REGION env var (defaults to "global")
  - Valid GCP credentials (gcloud auth application-default login)
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from calunga_release_watcher.analyzer import FailureAnalysis, analyze_failure
from calunga_release_watcher.tracker import PipelineState


def _make_info(body, **overrides):
    ns = body.get("metadata", {}).get("namespace", "calunga-tenant")
    defaults = dict(
        sha="test-sha",
        sha_short="test-sh",
        package_title="test-package",
        state=PipelineState.BUILD_FAILED,
        namespace=ns,
        snapshot=body["metadata"]["name"] if body.get("kind") == "Snapshot" else "",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_k8s_mocks(fixture):
    """
    Create mock k8s API objects that serve fixture data.

    Returns (mock_custom_api, mock_core_api) configured to respond
    to the exact calls that _build_context makes.
    """
    mock_custom = MagicMock()
    mock_core = MagicMock()

    # --- CustomObjectsApi.list_namespaced_custom_object ---
    # Called by _get_test_pipelineruns_for_snapshot
    def list_custom(group, version, namespace, plural, label_selector="", **kw):
        if plural == "pipelineruns" and "type=test" in label_selector:
            return {"items": fixture.get("test_pipelineruns", [])}
        return {"items": []}

    mock_custom.list_namespaced_custom_object.side_effect = list_custom

    # --- CustomObjectsApi.get_namespaced_custom_object ---
    # Called by _get_child_taskruns for each childReference
    taskruns = fixture.get("taskruns", {})

    def get_custom(group, version, namespace, plural, name, **kw):
        if plural == "taskruns" and name in taskruns:
            return taskruns[name]
        raise Exception(f"TaskRun {name} not in fixture")

    mock_custom.get_namespaced_custom_object.side_effect = get_custom

    # --- CoreV1Api.read_namespaced_pod ---
    # Called by _get_pod_logs to get container names
    pods = fixture.get("pods", {})

    def read_pod(name, namespace, **kw):
        if name in pods:
            pod_info = pods[name]
            pod_mock = MagicMock()
            pod_mock.spec.containers = [
                SimpleNamespace(name=c) for c in pod_info.get("containers", [])
            ]
            pod_mock.spec.init_containers = [
                SimpleNamespace(name=c) for c in pod_info.get("init_containers", [])
            ]
            return pod_mock
        raise Exception(f"Pod {name} not in fixture")

    mock_core.read_namespaced_pod.side_effect = read_pod

    # --- CoreV1Api.read_namespaced_pod_log ---
    # Called by _get_pod_logs for each container
    all_logs = fixture.get("pod_logs", {})

    def read_log(name, namespace, container, tail_lines=None, **kw):
        pod_logs = all_logs.get(name, {})
        return pod_logs.get(container, "")

    mock_core.read_namespaced_pod_log.side_effect = read_log

    return mock_custom, mock_core


@pytest.fixture()
def run_analysis(load_fixture):
    """
    Returns a callable that loads a fixture, mocks k8s, and runs
    analyze_failure against real Vertex AI.
    """

    def _run(fixture_name, failure_state, detail="test failure"):
        fixture = load_fixture(fixture_name)
        body = fixture["body"]
        info = _make_info(body, state=failure_state)

        mock_custom, mock_core = _build_k8s_mocks(fixture)

        vertex_project = (
            os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
        )
        vertex_region = os.environ.get("CLOUD_ML_REGION", "global")

        with (
            patch("calunga_release_watcher.analyzer.AI_ANALYSIS_ENABLED", True),
            patch("calunga_release_watcher.analyzer.GOOGLE_CLOUD_PROJECT", vertex_project),
            patch("calunga_release_watcher.analyzer.GOOGLE_CLOUD_REGION", vertex_region),
            patch("calunga_release_watcher.analyzer.get_k8s_client", return_value=MagicMock()),
            patch("calunga_release_watcher.analyzer.k8s_client") as mock_k8s_mod,
        ):
            mock_k8s_mod.CustomObjectsApi.return_value = mock_custom
            mock_k8s_mod.CoreV1Api.return_value = mock_core

            result = analyze_failure(body, info, failure_state, detail)

        return result

    return _run


def _assert_valid_analysis(analysis: FailureAnalysis):
    """Common structural assertions for any FailureAnalysis."""
    assert analysis is not None, "analyze_failure returned None"
    assert analysis.classification in ("fluke", "real", "infra", "unknown")
    assert analysis.confidence in ("high", "medium", "low")
    assert analysis.root_cause, "root_cause should not be empty"
    assert analysis.failed_task, "failed_task should not be empty"


@pytest.mark.e2e
class TestBuildFailure:
    def test_dependency_resolution_error(self, run_analysis):
        analysis = run_analysis(
            "build_failure.json",
            PipelineState.BUILD_FAILED,
            detail="Build pipeline failed: Tasks Completed: 5 (Failed: 1, Cancelled 0), Skipped: 5",
        )
        _assert_valid_analysis(analysis)
        assert analysis.classification in ("real", "unknown"), (
            f"Dependency resolution error should be 'real' or 'unknown', got '{analysis.classification}'"
        )


@pytest.mark.e2e
class TestEnterpriseContractFailure:
    def test_policy_violations(self, run_analysis):
        analysis = run_analysis(
            "test_enterprise_contract_failure.json",
            PipelineState.TESTS_FAILED,
            detail="Some Integration pipeline tests failed",
        )
        _assert_valid_analysis(analysis)
        assert analysis.classification in ("real", "infra", "unknown"), (
            f"EC policy violation should be 'real', 'infra', or 'unknown', got '{analysis.classification}'"
        )
        assert analysis.failed_scenarios == [
            "calunga-v2-index-main-enterprise-contract"
        ]


@pytest.mark.e2e
class TestImagePullFailure:
    def test_multi_wheel_check_image_pull_backoff(self, run_analysis):
        analysis = run_analysis(
            "test_multi_wheel_check_failure.json",
            PipelineState.TESTS_FAILED,
            detail="Some Integration pipeline tests failed",
        )
        _assert_valid_analysis(analysis)
        assert analysis.classification in ("fluke", "infra", "unknown"), (
            f"Image pull back-off should be 'fluke' or 'infra', got '{analysis.classification}'"
        )
        assert set(analysis.failed_scenarios) == {
            "wheel-check-hummingbird-python-312",
            "wheel-check-ubi8",
            "wheel-check-fedora43",
        }
