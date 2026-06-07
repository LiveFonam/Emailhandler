"""Per-mailbox send throttling.

The throttler is the gate every send goes through. It:
  1. Checks per-mailbox daily cap (warmup.py)
  2. Waits until the recipient's local business hours (9am-5pm)
  3. Sleeps 60-90s after the previous send on the same mailbox

`wait_for_slot()` is called from the scheduler before each send. It
returns a datetime when the next legal send window opens.
"""
from __future__ import annotations

import datetime as dt
import random
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config import settings
from src import db


# Small static map of country ISO-3166-1 alpha-2 -> IANA timezone.
# Defaults to UTC for unknown. v1.1: pull this from a package.
_COUNTRY_TZ: dict[str, str] = {
    "US": "America/New_York",
    "CA": "America/Toronto",
    "GB": "Europe/London",
    "UK": "Europe/London",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "ES": "Europe/Madrid",
    "IT": "Europe/Rome",
    "NL": "Europe/Amsterdam",
    "JP": "Asia/Tokyo",
    "CN": "Asia/Shanghai",
    "KR": "Asia/Seoul",
    "IN": "Asia/Kolkata",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    "BR": "America/Sao_Paulo",
    "MX": "America/Mexico_City",
    "IL": "Asia/Jerusalem",
    "SE": "Europe/Stockholm",
    "NO": "Europe/Oslo",
    "FI": "Europe/Helsinki",
    "DK": "Europe/Copenhagen",
    "IE": "Europe/Dublin",
    "PT": "Europe/Lisbon",
    "PL": "Europe/Warsaw",
    "AT": "Europe/Vienna",
    "CH": "Europe/Zurich",
    "BE": "Europe/Brussels",
    "SG": "Asia/Singapore",
    "HK": "Asia/Hong_Kong",
    "TW": "Asia/Taipei",
    "TH": "Asia/Bangkok",
    "MY": "Asia/Kuala_Lumpur",
    "PH": "Asia/Manila",
    "ID": "Asia/Jakarta",
    "VN": "Asia/Ho_Chi_Minh",
    "AE": "Asia/Dubai",
    "SA": "Asia/Riyadh",
    "ZA": "Africa/Johannesburg",
    "EG": "Africa/Cairo",
    "NG": "Africa/Lagos",
    "AR": "America/Argentina/Buenos_Aires",
    "CL": "America/Santiago",
    "CO": "America/Bogota",
    "PE": "America/Lima",
}


def tz_for_lead(country: str | None, lead_tz: str | None) -> str:
    """Resolve the IANA timezone for a lead."""
    if lead_tz:
        try:
            ZoneInfo(lead_tz)
            return lead_tz
        except Exception:
            pass
    if country:
        c = country.strip().upper()
        if c in _COUNTRY_TZ:
            return _COUNTRY_TZ[c]
    return settings.throttler.default_recipient_timezone


def is_business_hours(
    when: dt.datetime, recipient_tz: str
) -> bool:
    """Is `when` between 9am-5pm in the recipient's local time, on a weekday?"""
    try:
        zi = ZoneInfo(recipient_tz)
    except ZoneInfoNotFoundError:
        zi = ZoneInfo(settings.throttler.default_recipient_timezone)
    local = when.astimezone(zi)
    if local.weekday() >= 5:  # Sat / Sun
        return False
    h = local.hour
    return settings.throttler.business_hours_start <= h < settings.throttler.business_hours_end


def next_business_hour(when: dt.datetime, recipient_tz: str) -> dt.datetime:
    """Return the next business-hour start at or after `when` in the recipient's TZ."""
    try:
        zi = ZoneInfo(recipient_tz)
    except ZoneInfoNotFoundError:
        zi = ZoneInfo(settings.throttler.default_recipient_timezone)
    local = when.astimezone(zi)
    start_h = settings.throttler.business_hours_start

    # If today is a weekday and we're before start, just move to today's start
    if local.weekday() < 5 and local.hour < start_h:
        target_local = local.replace(hour=start_h, minute=0, second=0, microsecond=0)
        return target_local.astimezone(dt.timezone.utc)

    # Otherwise jump to next weekday's 9am
    days_ahead = 1
    if local.weekday() < 4:
        days_ahead = 1
    elif local.weekday() == 4:  # Friday
        days_ahead = 3
    elif local.weekday() == 5:  # Saturday
        days_ahead = 2
    else:  # Sunday
        days_ahead = 1
    nxt = (local + dt.timedelta(days=days_ahead)).replace(
        hour=start_h, minute=0, second=0, microsecond=0
    )
    return nxt.astimezone(dt.timezone.utc)


def last_sent_at(mailbox_id: int) -> Optional[dt.datetime]:
    row = db.query_one(
        "SELECT last_sent_at FROM mailboxes WHERE id = ?", (mailbox_id,)
    )
    if not row or not row["last_sent_at"]:
        return None
    try:
        return dt.datetime.fromisoformat(row["last_sent_at"])
    except Exception:
        return None


def jitter_sleep_seconds() -> float:
    lo = settings.throttler.min_jitter_seconds
    hi = settings.throttler.max_jitter_seconds
    return random.uniform(lo, hi)


def wait_for_slot(
    mailbox_id: int,
    recipient_country: str | None = None,
    recipient_tz: str | None = None,
    now: Optional[dt.datetime] = None,
) -> dt.datetime:
    """Block (or rather, compute) until the next legal send window for
    this mailbox. Returns the datetime when the send may proceed."""
    from src.outreach.warmup import current_cap, mailbox_send_count_today

    now = now or dt.datetime.now(dt.timezone.utc)
    cap = current_cap(mailbox_id)
    sent_today = mailbox_send_count_today(mailbox_id)
    if sent_today >= cap:
        # Defer to tomorrow
        tomorrow = (now + dt.timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0
        )
        return tomorrow

    # Recipient-TZ business hours gate
    tz = tz_for_lead(recipient_country, recipient_tz)
    if not is_business_hours(now, tz):
        return next_business_hour(now, tz)

    # Per-mailbox jitter: must be 60-90s after the last send
    last = last_sent_at(mailbox_id)
    if last is not None:
        earliest = last + dt.timedelta(seconds=jitter_sleep_seconds())
        if now < earliest:
            return earliest

    return now
