"""Reply-rate metrics. v1: stub. v1.1: scan threads, look for replies
from sent-log leads, write per-variant reply rates."""

from __future__ import annotations

import datetime as dt
import logging

from src import db


log = logging.getLogger("inbox_zero.analytics.reply_rate")


def refresh_all_reply_metrics() -> None:
    """v1 stub. v1.1 will scan sent_log -> find each lead's email ->
    query Gmail threads for any inbound reply in the same chain -> write
    per-variant reply counts."""
    log.info("reply_scan: heartbeat (v1 stub)")
