import json
from unittest.mock import MagicMock, patch

from calunga_release_watcher.analyzer import (
    FailureAnalysis,
    _truncate_context,
    extract_failed_scenarios,
    format_analysis,
    _call_claude,
)


# ---------------------------------------------------------------------------
# extract_failed_scenarios
# ---------------------------------------------------------------------------


class TestExtractFailedScenarios:
    def test_extracts_failed(self):
        body = {
            "kind": "Snapshot",
            "metadata": {
                "annotations": {
                    "test.appstudio.openshift.io/status": json.dumps([
                        {"scenario": "scenario-a", "status": "TestFailed"},
                        {"scenario": "scenario-b", "status": "TestPassed"},
                        {"scenario": "scenario-c", "status": "EnvironmentProvisionError"},
                    ]),
                },
            },
        }
        result = extract_failed_scenarios(body)
        assert result == ["scenario-a", "scenario-c"]

    def test_not_snapshot(self):
        body = {"kind": "PipelineRun", "metadata": {"annotations": {}}}
        assert extract_failed_scenarios(body) == []

    def test_missing_annotation(self):
        body = {"kind": "Snapshot", "metadata": {"annotations": {}}}
        assert extract_failed_scenarios(body) == []

    def test_bad_json(self):
        body = {
            "kind": "Snapshot",
            "metadata": {"annotations": {"test.appstudio.openshift.io/status": "not-json"}},
        }
        assert extract_failed_scenarios(body) == []

    def test_empty_list(self):
        body = {
            "kind": "Snapshot",
            "metadata": {"annotations": {"test.appstudio.openshift.io/status": "[]"}},
        }
        assert extract_failed_scenarios(body) == []

    def test_deployment_error(self):
        body = {
            "kind": "Snapshot",
            "metadata": {
                "annotations": {
                    "test.appstudio.openshift.io/status": json.dumps([
                        {"scenario": "deploy-test", "status": "DeploymentError"},
                    ]),
                },
            },
        }
        assert extract_failed_scenarios(body) == ["deploy-test"]


# ---------------------------------------------------------------------------
# _truncate_context
# ---------------------------------------------------------------------------


class TestTruncateContext:
    def test_within_budget(self):
        parts = [("Label A", "short content"), ("Label B", "more content")]
        result = _truncate_context(parts)
        assert "Label A" in result
        assert "Label B" in result
        assert "short content" in result

    def test_truncates_large_content(self):
        large = "x" * 100_000
        parts = [("Big", large)]
        result = _truncate_context(parts)
        assert "[... truncated" in result
        assert len(result) < 100_000

    def test_budget_exhausted_marks_truncated(self):
        parts = [("A", "x" * 50_000), ("B", "y" * 50_000)]
        result = _truncate_context(parts)
        assert "A" in result
        assert "[TRUNCATED]" in result


# ---------------------------------------------------------------------------
# format_analysis
# ---------------------------------------------------------------------------


class TestFormatAnalysis:
    def test_fluke_format(self):
        analysis = FailureAnalysis(
            classification="fluke",
            confidence="high",
            root_cause="Network timeout pulling image",
            suggestion="Retry the pipeline",
            failed_task="build-container",
        )
        result = format_analysis(analysis)
        assert "AI Analysis" in result
        assert "fluke" in result
        assert "Network timeout" in result
        assert "Retry the pipeline" in result

    def test_real_format(self):
        analysis = FailureAnalysis(
            classification="real",
            confidence="medium",
            root_cause="Compilation error",
            suggestion="Fix syntax",
            failed_task="compile",
        )
        result = format_analysis(analysis)
        assert "real" in result

    def test_suggestion_none_omitted(self):
        analysis = FailureAnalysis(
            classification="unknown",
            confidence="low",
            root_cause="Unclear",
            suggestion="none",
            failed_task="unknown",
        )
        result = format_analysis(analysis)
        assert "Suggestion" not in result


# ---------------------------------------------------------------------------
# _call_claude
# ---------------------------------------------------------------------------


class TestCallClaude:
    @patch("calunga_release_watcher.analyzer.GOOGLE_CLOUD_PROJECT", "test-project")
    @patch("calunga_release_watcher.analyzer.AnthropicVertex")
    def test_returns_analysis(self, mock_vertex_cls):
        mock_client = MagicMock()
        mock_vertex_cls.return_value = mock_client

        response_json = json.dumps({
            "classification": "fluke",
            "confidence": "high",
            "root_cause": "Image pull timeout",
            "suggestion": "Retry",
            "failed_task": "build-container",
            "failed_scenarios": [],
        })
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_json)]
        mock_client.messages.create.return_value = mock_response

        result = _call_claude("some context", "build_failed")
        assert result is not None
        assert result.classification == "fluke"
        assert result.confidence == "high"

        mock_vertex_cls.assert_called_once_with(
            project_id="test-project",
            region="global",
        )

    @patch("calunga_release_watcher.analyzer.GOOGLE_CLOUD_PROJECT", "")
    def test_skips_when_no_project(self):
        result = _call_claude("context", "build_failed")
        assert result is None
