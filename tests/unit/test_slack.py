import json
from unittest.mock import MagicMock, patch

from calunga_release_watcher.slack import send_slack_sync


class TestSendSlackSync:
    def test_skips_when_no_token(self, mocker):
        mocker.patch("calunga_release_watcher.slack.SLACK_BOT_TOKEN", "")
        mocker.patch("calunga_release_watcher.slack.SLACK_CHANNEL", "test-channel")
        result = send_slack_sync("hello")
        assert result == ""

    def test_skips_when_no_channel(self, mocker):
        mocker.patch("calunga_release_watcher.slack.SLACK_BOT_TOKEN", "xoxb-test")
        mocker.patch("calunga_release_watcher.slack.SLACK_CHANNEL", "")
        result = send_slack_sync("hello")
        assert result == ""

    def test_sends_message(self, mocker):
        mocker.patch("calunga_release_watcher.slack.SLACK_BOT_TOKEN", "xoxb-test")
        mocker.patch("calunga_release_watcher.slack.SLACK_CHANNEL", "C123")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "ts": "1234.5678"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen = mocker.patch("calunga_release_watcher.slack.urllib.request.urlopen", return_value=mock_resp)

        result = send_slack_sync("hello world")
        assert result == "1234.5678"

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "https://slack.com/api/chat.postMessage"
        payload = json.loads(req.data)
        assert payload["channel"] == "C123"
        assert payload["text"] == "hello world"

    def test_sends_threaded_message(self, mocker):
        mocker.patch("calunga_release_watcher.slack.SLACK_BOT_TOKEN", "xoxb-test")
        mocker.patch("calunga_release_watcher.slack.SLACK_CHANNEL", "C123")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "ts": "9999.0001"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen = mocker.patch("calunga_release_watcher.slack.urllib.request.urlopen", return_value=mock_resp)

        result = send_slack_sync("reply", thread_ts="1234.5678")
        assert result == "9999.0001"

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["thread_ts"] == "1234.5678"

    def test_api_error_returns_empty(self, mocker):
        mocker.patch("calunga_release_watcher.slack.SLACK_BOT_TOKEN", "xoxb-test")
        mocker.patch("calunga_release_watcher.slack.SLACK_CHANNEL", "C123")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": False, "error": "channel_not_found"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mocker.patch("calunga_release_watcher.slack.urllib.request.urlopen", return_value=mock_resp)

        result = send_slack_sync("hello")
        assert result == ""

    def test_network_error_returns_empty(self, mocker):
        mocker.patch("calunga_release_watcher.slack.SLACK_BOT_TOKEN", "xoxb-test")
        mocker.patch("calunga_release_watcher.slack.SLACK_CHANNEL", "C123")

        mocker.patch(
            "calunga_release_watcher.slack.urllib.request.urlopen",
            side_effect=ConnectionError("network down"),
        )

        result = send_slack_sync("hello")
        assert result == ""
