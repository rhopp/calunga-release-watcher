from unittest.mock import MagicMock, patch

from calunga_release_watcher.analyzer import FailureAnalysis
from calunga_release_watcher.retrier import (
    _meets_confidence_threshold,
    attempt_retry,
    should_retry,
)
from calunga_release_watcher.tracker import PipelineInfo, PipelineState

SHA = "abc1234567890def"


def make_pipeline_info(sha=SHA, state=PipelineState.BUILD_RUNNING, **kwargs):
    return PipelineInfo(
        sha=sha,
        sha_short=sha[:7],
        package_title=kwargs.pop("package_title", "test-package"),
        state=state,
        namespace=kwargs.pop("namespace", "calunga-tenant"),
        **kwargs,
    )


def _make_analysis(
    classification="fluke",
    confidence="high",
    failed_scenarios=None,
):
    return FailureAnalysis(
        classification=classification,
        confidence=confidence,
        root_cause="test",
        suggestion="test",
        failed_task="test-task",
        failed_scenarios=failed_scenarios or [],
    )


# ---------------------------------------------------------------------------
# _meets_confidence_threshold
# ---------------------------------------------------------------------------


class TestMeetsConfidenceThreshold:
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    def test_high_meets_medium(self):
        assert _meets_confidence_threshold("high") is True

    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    def test_medium_meets_medium(self):
        assert _meets_confidence_threshold("medium") is True

    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    def test_low_fails_medium(self):
        assert _meets_confidence_threshold("low") is False

    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "low")
    def test_low_meets_low(self):
        assert _meets_confidence_threshold("low") is True

    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "high")
    def test_medium_fails_high(self):
        assert _meets_confidence_threshold("medium") is False


# ---------------------------------------------------------------------------
# should_retry
# ---------------------------------------------------------------------------


class TestShouldRetry:
    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", False)
    def test_disabled(self):
        assert should_retry(_make_analysis(), 0) is False

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    @patch("calunga_release_watcher.retrier.MAX_RETRIES", 3)
    def test_fluke_high_confidence(self):
        assert should_retry(_make_analysis(classification="fluke", confidence="high"), 0) is True

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    def test_real_issue_rejected(self):
        assert should_retry(_make_analysis(classification="real"), 0) is False

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    def test_infra_rejected(self):
        assert should_retry(_make_analysis(classification="infra"), 0) is False

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    @patch("calunga_release_watcher.retrier.MAX_RETRIES", 3)
    def test_max_retries_exhausted(self):
        assert should_retry(_make_analysis(), 3) is False

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "high")
    def test_low_confidence_rejected(self):
        assert should_retry(_make_analysis(confidence="low"), 0) is False


# ---------------------------------------------------------------------------
# attempt_retry
# ---------------------------------------------------------------------------


class TestAttemptRetry:
    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", False)
    def test_retry_disabled_returns_empty(self):
        info = make_pipeline_info()
        analysis = _make_analysis()
        retried, msg = attempt_retry(analysis, PipelineState.BUILD_FAILED, {}, info)
        assert retried is False
        assert msg == ""

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    @patch("calunga_release_watcher.retrier.MAX_RETRIES", 3)
    def test_build_failure_not_implemented(self):
        info = make_pipeline_info()
        analysis = _make_analysis()
        retried, msg = attempt_retry(analysis, PipelineState.BUILD_FAILED, {}, info)
        assert retried is False
        assert "not yet implemented" in msg

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    @patch("calunga_release_watcher.retrier.MAX_RETRIES", 3)
    @patch("calunga_release_watcher.retrier.retry_test_scenarios")
    def test_test_failure_triggers_retry(self, mock_retry_tests):
        mock_retry_tests.return_value = ["scenario-a"]
        info = make_pipeline_info(snapshot="snap-1")
        analysis = _make_analysis(failed_scenarios=["scenario-a"])
        retried, msg = attempt_retry(analysis, PipelineState.TESTS_FAILED, {}, info)
        assert retried is True
        assert "scenario-a" in msg
        mock_retry_tests.assert_called_once()

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    @patch("calunga_release_watcher.retrier.MAX_RETRIES", 3)
    @patch("calunga_release_watcher.retrier.retry_release")
    def test_release_failure_triggers_retry(self, mock_retry_release):
        mock_retry_release.return_value = "retry-release-1"
        info = make_pipeline_info(snapshot="snap-1")
        analysis = _make_analysis()
        retried, msg = attempt_retry(analysis, PipelineState.RELEASE_FAILED, {}, info)
        assert retried is True
        assert "retry-release-1" in msg
        mock_retry_release.assert_called_once()

    @patch("calunga_release_watcher.retrier.RETRY_ENABLED", True)
    @patch("calunga_release_watcher.retrier.RETRY_CONFIDENCE_THRESHOLD", "medium")
    @patch("calunga_release_watcher.retrier.MAX_RETRIES", 1)
    def test_max_retries_exhausted_message(self):
        info = make_pipeline_info()
        info.build_retry_count = 1
        analysis = _make_analysis()
        retried, msg = attempt_retry(analysis, PipelineState.BUILD_FAILED, {}, info)
        assert retried is False
        assert "Max retries" in msg
        assert "manual intervention" in msg
