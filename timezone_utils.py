"""Timezone detection and resolution utilities."""

import datetime
from zoneinfo import ZoneInfo


def parse_utc_offset(tz_str: str) -> datetime.timezone:
    """Convert a UTC offset string like 'UTC+02:00' to a datetime.timezone."""
    tz_offset_str = tz_str.replace("UTC", "")
    sign = -1 if tz_offset_str.startswith("-") else 1
    tz_offset_str = tz_offset_str.lstrip("+-")

    if ":" in tz_offset_str:
        hh, mm = map(int, tz_offset_str.split(":"))
    else:
        hh, mm = int(tz_offset_str), 0

    return datetime.timezone(datetime.timedelta(minutes=sign * (hh * 60 + mm)))


def make_tz_options() -> list[str]:
    """Generate UTC offset strings in 15-minute increments."""
    result = []
    for minutes in range(-12 * 60, 14 * 60 + 1, 15):
        h, m = divmod(abs(minutes), 60)
        sign = "+" if minutes >= 0 else "-"
        result.append(f"UTC{sign}{h}:{m:02d}")
    return result


def resolve_timezone(
    use_auto: bool,
    browser_tz: str | None,
    manual_tz_str: str,
) -> datetime.timezone | ZoneInfo:
    """
    Return the active timezone based on user settings.

    Prefers the browser-detected IANA timezone when use_auto is True,
    falls back to the manually selected UTC offset otherwise.
    """
    if use_auto and browser_tz:
        try:
            return ZoneInfo(browser_tz)
        except Exception:
            return datetime.timezone.utc
    return parse_utc_offset(manual_tz_str)
