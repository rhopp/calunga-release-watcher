import logging

import urllib.request
import json

from calunga_release_watcher.config import SLACK_BOT_TOKEN, SLACK_CHANNEL

logger = logging.getLogger(__name__)


def send_slack_sync(message: str, thread_ts: str = "") -> str:
    """Send a Slack message. Returns the message ts (for threading) or empty string on failure."""
    if not SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set — skipping Slack notification")
        return ""
    if not SLACK_CHANNEL:
        logger.warning("SLACK_CHANNEL not set — skipping Slack notification")
        return ""

    try:
        payload: dict = {"channel": SLACK_CHANNEL, "text": message}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=data,
            headers={
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.error("Slack API error: %s", result.get("error", "unknown"))
                return ""
            return result.get("ts", "")
    except Exception:
        logger.exception("Failed to send Slack notification")
        return ""
