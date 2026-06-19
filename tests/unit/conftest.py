import pytest


@pytest.fixture(autouse=True)
def _isolate_slack(mocker):
    mocker.patch("calunga_release_watcher.slack.SLACK_BOT_TOKEN", "")
    mocker.patch("calunga_release_watcher.slack.SLACK_CHANNEL", "")
