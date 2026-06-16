import logging

import urllib.request
import json

from calunga_release_watcher.config import SLACK_BOT_TOKEN, SLACK_CHANNEL

logger = logging.getLogger(__name__)


def send_slack_sync(message: str) -> None:
    if not SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set — skipping Slack notification")
        return
    if not SLACK_CHANNEL:
        logger.warning("SLACK_CHANNEL not set — skipping Slack notification")
        return

    try:
        data = json.dumps({"channel": SLACK_CHANNEL, "text": message}).encode()
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
    except Exception:
        logger.exception("Failed to send Slack notification")
