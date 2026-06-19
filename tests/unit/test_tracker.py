from unittest.mock import patch

from calunga_release_watcher.tracker import (
    PipelineInfo,
    PipelineState,
    PipelineTracker,
    extract_package_title,
    extract_sha,
    extract_snapshot_name,
    get_condition_status,
    get_named_condition,
)

SHA = "abc1234567890def"
SHA_SHORT = "abc1234"

CONDITION_SUCCEEDED = [{"type": "Succeeded", "status": "True", "reason": "Completed", "message": ""}]
CONDITION_FAILED = [{"type": "Succeeded", "status": "False", "reason": "Failed", "message": "step failed"}]
CONDITION_RUNNING = [{"type": "Succeeded", "status": "Unknown", "reason": "Running", "message": ""}]


def make_body(name="test-plr-1", sha=SHA, kind="PipelineRun", namespace="calunga-tenant",
              labels=None, annotations=None, conditions=None, extra_status=None):
    body = {
        "kind": kind,
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"pac.test.appstudio.openshift.io/sha": sha, **(labels or {})},
            "annotations": annotations or {},
        },
        "status": {},
    }
    if conditions is not None:
        body["status"]["conditions"] = conditions
    if extra_status:
        body["status"].update(extra_status)
    return body


def make_pipeline_info(sha=SHA, state=PipelineState.BUILD_RUNNING, **kwargs):
    return PipelineInfo(
        sha=sha,
        sha_short=sha[:7],
        package_title=kwargs.pop("package_title", "test-package"),
        state=state,
        namespace=kwargs.pop("namespace", "calunga-tenant"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


class TestExtractSha:
    def test_from_labels(self):
        body = make_body(sha="deadbeef1234")
        assert extract_sha(body) == "deadbeef1234"

    def test_from_annotations(self):
        body = make_body()
        body["metadata"]["labels"] = {}
        body["metadata"]["annotations"] = {
            "pac.test.appstudio.openshift.io/sha": "cafe1234"
        }
        assert extract_sha(body) == "cafe1234"

    def test_missing(self):
        body = {"metadata": {"labels": {}, "annotations": {}}}
        assert extract_sha(body) is None

    def test_empty_metadata(self):
        body = {"metadata": {}}
        assert extract_sha(body) is None


class TestExtractPackageTitle:
    def test_from_annotation(self):
        body = make_body(annotations={
            "pac.test.appstudio.openshift.io/sha-title": "Update dependencies"
        })
        assert extract_package_title(body) == "Update dependencies"

    def test_strips_automatic_build_prefix(self):
        body = make_body(annotations={
            "pac.test.appstudio.openshift.io/sha-title": "Automatic build of something"
        })
        assert extract_package_title(body) == "of something"

    def test_takes_first_line(self):
        body = make_body(annotations={
            "pac.test.appstudio.openshift.io/sha-title": "First line\nSecond line"
        })
        assert extract_package_title(body) == "First line"

    def test_defaults_to_unknown(self):
        body = make_body()
        assert extract_package_title(body) == "unknown"


class TestExtractSnapshotName:
    def test_present(self):
        body = make_body(labels={"appstudio.openshift.io/snapshot": "snap-1"})
        assert extract_snapshot_name(body) == "snap-1"

    def test_missing(self):
        body = make_body()
        assert extract_snapshot_name(body) == ""


class TestGetConditionStatus:
    def test_succeeded(self):
        body = make_body(conditions=CONDITION_SUCCEEDED)
        status, reason = get_condition_status(body)
        assert status == "True"
        assert reason == "Completed"

    def test_failed(self):
        body = make_body(conditions=CONDITION_FAILED)
        status, reason = get_condition_status(body)
        assert status == "False"
        assert reason == "Failed"

    def test_no_conditions(self):
        body = make_body()
        status, reason = get_condition_status(body)
        assert status is None
        assert reason is None

    def test_empty_conditions(self):
        body = make_body(conditions=[])
        status, reason = get_condition_status(body)
        assert status is None
        assert reason is None


class TestGetNamedCondition:
    def test_finds_matching_type(self):
        body = make_body(conditions=[
            {"type": "AppStudioTestSucceeded", "status": "True", "reason": "Passed"},
            {"type": "AutoReleased", "status": "False", "reason": "Pending"},
        ])
        status, reason = get_named_condition(body, "AppStudioTestSucceeded")
        assert status == "True"
        assert reason == "Passed"

    def test_not_found(self):
        body = make_body(conditions=CONDITION_SUCCEEDED)
        status, reason = get_named_condition(body, "NoSuchCondition")
        assert status is None
        assert reason is None


# ---------------------------------------------------------------------------
# PipelineTracker
# ---------------------------------------------------------------------------


class TestPipelineTrackerGetOrCreate:
    def test_creates_new(self):
        tracker = PipelineTracker()
        body = make_body()
        info = tracker.get_or_create(SHA, body)
        assert info is not None
        assert info.sha == SHA
        assert info.sha_short == SHA_SHORT

    def test_returns_existing(self):
        tracker = PipelineTracker()
        body = make_body()
        info1 = tracker.get_or_create(SHA, body)
        info2 = tracker.get_or_create(SHA, body)
        assert info1 is info2

    def test_returns_none_for_seen_sha_when_live(self):
        tracker = PipelineTracker()
        body = make_body()
        tracker.get_or_create(SHA, body)
        info = tracker._pipelines.pop(SHA)
        tracker.set_live()
        assert tracker.get_or_create(SHA, body) is None


class TestPipelineTrackerTransition:
    def test_same_state_is_noop(self):
        tracker = PipelineTracker()
        info = make_pipeline_info(state=PipelineState.BUILD_RUNNING)
        tracker._transition(info, PipelineState.BUILD_RUNNING)
        assert info.state == PipelineState.BUILD_RUNNING

    def test_terminal_state_blocks_further_transitions(self):
        tracker = PipelineTracker()
        info = make_pipeline_info(state=PipelineState.RELEASED)
        tracker._transition(info, PipelineState.BUILD_RUNNING)
        assert info.state == PipelineState.RELEASED

    def test_retrying_blocks_failure_reentry(self):
        tracker = PipelineTracker()
        info = make_pipeline_info(state=PipelineState.BUILD_RETRYING)
        tracker._transition(info, PipelineState.BUILD_FAILED)
        assert info.state == PipelineState.BUILD_RETRYING

    def test_normal_transition(self):
        tracker = PipelineTracker()
        info = make_pipeline_info(state=PipelineState.BUILD_RUNNING)
        tracker._transition(info, PipelineState.BUILD_SUCCEEDED)
        assert info.state == PipelineState.BUILD_SUCCEEDED


class TestPipelineTrackerSetLive:
    def test_filters_terminal_and_stale(self):
        tracker = PipelineTracker()
        body_released = make_body(name="plr-released", sha="sha1")
        body_stale = make_body(name="plr-stale", sha="sha2")
        body_active = make_body(name="plr-active", sha="sha3")

        info_released = tracker.get_or_create("sha1", body_released)
        info_released.state = PipelineState.RELEASED
        info_released.build_pipelinerun = "plr-released"

        info_stale = tracker.get_or_create("sha2", body_stale)
        # no build_pipelinerun set — stale

        info_active = tracker.get_or_create("sha3", body_active)
        info_active.state = PipelineState.BUILD_RUNNING
        info_active.build_pipelinerun = "plr-active"

        tracker.set_live()

        assert "sha1" not in tracker._pipelines
        assert "sha2" not in tracker._pipelines
        assert "sha3" in tracker._pipelines


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


class TestOnBuildPipelineRun:
    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_running(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="build-1")
        tracker.on_build_pipelinerun(body)
        info = tracker.get(SHA)
        assert info is not None
        assert info.state == PipelineState.BUILD_RUNNING
        assert info.build_pipelinerun == "build-1"

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_succeeded(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="build-1", conditions=CONDITION_SUCCEEDED)
        tracker.on_build_pipelinerun(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.BUILD_SUCCEEDED

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_failed_when_live(self, mock_handle):
        tracker = PipelineTracker()
        tracker._live = True
        body = make_body(name="build-1", conditions=CONDITION_FAILED)
        tracker.on_build_pipelinerun(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.BUILD_FAILED
        mock_handle.assert_called_once()

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_no_sha_is_noop(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body()
        body["metadata"]["labels"] = {}
        tracker.on_build_pipelinerun(body)
        assert len(tracker._pipelines) == 0


class TestOnSnapshot:
    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_snapshot_created(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="snap-1", kind="Snapshot")
        tracker.on_snapshot(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.SNAPSHOT_CREATED
        assert info.snapshot == "snap-1"

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_tests_passed(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="snap-1", kind="Snapshot", conditions=[
            {"type": "AppStudioTestSucceeded", "status": "True", "reason": "Passed"},
        ])
        tracker.on_snapshot(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.TESTS_PASSED

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_tests_failed_when_live(self, mock_handle):
        tracker = PipelineTracker()
        tracker._live = True
        body = make_body(name="snap-1", kind="Snapshot", conditions=[
            {"type": "AppStudioTestSucceeded", "status": "False", "reason": "TestFailed"},
        ])
        tracker.on_snapshot(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.TESTS_FAILED
        mock_handle.assert_called_once()


class TestOnTestPipelineRun:
    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_test_started_transitions_to_testing(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="build-1")
        tracker.on_build_pipelinerun(body)
        info = tracker.get(SHA)
        info.state = PipelineState.SNAPSHOT_CREATED

        test_body = make_body(
            name="test-1",
            labels={"test.appstudio.openshift.io/scenario": "my-scenario"},
        )
        tracker.on_test_pipelinerun(test_body)
        assert info.state == PipelineState.TESTING

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_tracks_test_pipelinerun_status(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="test-1", conditions=CONDITION_SUCCEEDED)
        tracker.on_test_pipelinerun(body)
        info = tracker.get(SHA)
        assert "test-1" in info.test_pipelineruns
        assert info.test_pipelineruns["test-1"] == "True"


class TestOnRelease:
    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_releasing(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="rel-1", kind="Release", conditions=[
            {"type": "Released", "status": "Unknown", "reason": "Progressing"},
        ])
        tracker.on_release(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.RELEASING
        assert info.release == "rel-1"

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_released(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(name="rel-1", kind="Release", conditions=[
            {"type": "Released", "status": "True", "reason": "Succeeded"},
        ])
        tracker.on_release(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.RELEASED

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_release_failed_when_live(self, mock_handle):
        tracker = PipelineTracker()
        tracker._live = True
        body = make_body(name="rel-1", kind="Release", conditions=[
            {"type": "Released", "status": "False", "reason": "Error"},
        ])
        tracker.on_release(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.RELEASE_FAILED
        mock_handle.assert_called_once()


class TestOnReleasePipelineRun:
    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_succeeded(self, mock_handle):
        tracker = PipelineTracker()
        body = make_body(
            name="managed-plr-1",
            namespace="rhtap-releng-tenant",
            conditions=CONDITION_SUCCEEDED,
        )
        tracker.on_release_pipelinerun(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.RELEASED
        assert info.release_pipelinerun == "rhtap-releng-tenant/managed-plr-1"

    @patch("calunga_release_watcher.tracker._handle_failure")
    def test_failed_when_live(self, mock_handle):
        tracker = PipelineTracker()
        tracker._live = True
        body = make_body(
            name="managed-plr-1",
            namespace="rhtap-releng-tenant",
            conditions=CONDITION_FAILED,
        )
        tracker.on_release_pipelinerun(body)
        info = tracker.get(SHA)
        assert info.state == PipelineState.RELEASE_FAILED
        mock_handle.assert_called_once()
