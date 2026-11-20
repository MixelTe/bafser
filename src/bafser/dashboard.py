import math
import os
import statistics
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import jinja2
from flask import abort, current_app, has_request_context, render_template, request

import bafser_config

from .logger import get_log_fpath_all

_loc = os.path.abspath(os.path.dirname(__file__))
_template_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(_loc, "templates")),
    autoescape=jinja2.select_autoescape(("html",)),
)
_template_dashboard = _template_env.get_template("dashboard.html")
_CACHE_KEY = "bafser.dashboard"
StatsDict = dict[str, Any]


@dataclass(frozen=True)
class _RequestRecord:
    timestamp: datetime
    endpoint: str
    duration_ms: float
    status: int | None
    request_id: str | None


@dataclass
class _ReadInfo:
    bytes_read: int = 0
    lines_read: int = 0
    files_read: int = 0
    read_errors: int = 0
    partial_rows: int = 0
    bytes_limited: bool = False
    lines_limited: bool = False
    files_limited: bool = False


@dataclass(frozen=True)
class _Snapshot:
    records: tuple[_RequestRecord, ...]
    created_at: datetime
    read_info: _ReadInfo
    invalid_rows: int
    future_rows: int
    legacy_rows: int


class _SnapshotCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.key: tuple[Any, ...] | None = None
        self.snapshot: _Snapshot | None = None
        self.expires = 0.0


def calculate_box_stats(data_list: list[float]) -> StatsDict | None:
    """Retain the existing statistics helper without clipping measured values."""
    if not data_list:
        return None
    values = sorted(data_list)
    if len(values) == 1:
        value = values[0]
        return {"min": value, "q1": value, "median": value, "mean": value, "q3": value, "max": value, "items": []}
    quantiles = statistics.quantiles(values, n=4)
    return {
        "min": values[0],
        "q1": quantiles[0],
        "median": quantiles[1],
        "mean": statistics.mean(values),
        "q3": quantiles[2],
        "max": values[-1],
        "items": [],
    }


def _setting(name: str, default: int, *, minimum: int = 1) -> int:
    value = cast(Any, current_app.config.get(name, default))  # pyright: ignore[reportUnknownMemberType]
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _read_tails(paths: list[str], max_bytes: int, max_lines: int) -> tuple[list[str], _ReadInfo]:
    """Read newest tails with independent, total byte/line budgets."""
    lines: list[str] = []
    info = _ReadInfo()
    identities: set[tuple[int, int]] = set()
    for path in paths:
        try:
            with open(path, "rb") as source:
                identity = os.fstat(source.fileno())
                file_key = identity.st_dev, identity.st_ino
                # Rotation may rename an already-read file into a later path.
                if identity.st_ino and file_key in identities:
                    continue
                identities.add(file_key)
                source.seek(0, os.SEEK_END)
                size = source.tell()
                if not size:
                    continue
                if len(lines) >= max_lines:
                    info.lines_limited = True
                    break
                remaining = max_bytes - info.bytes_read
                if remaining <= 0:
                    info.bytes_limited = True
                    break
                start = max(0, size - remaining)
                source.seek(start)
                data = source.read(remaining)
        except FileNotFoundError:
            continue  # Rotation can move a path between discovery and opening.
        except OSError:
            info.read_errors += 1
            continue
        info.files_read += 1
        info.bytes_read += len(data)
        if data and not data.endswith(b"\n"):
            # A writer can pause at any valid-looking prefix, including one with
            # legacy field counts. Only newline-terminated physical records count.
            info.partial_rows += 1
            newline = data.rfind(b"\n")
            data = data[: newline + 1] if newline >= 0 else b""
        if start:
            info.bytes_limited = True
            newline = data.find(b"\n")
            data = data[newline + 1 :] if newline >= 0 else b""
        available = data.decode("utf8", errors="replace").splitlines()
        space = max_lines - len(lines)
        if len(available) > space:
            info.lines_limited = True
        lines.extend(reversed(available[-space:]))
        if info.lines_limited:
            break
    info.lines_read = len(lines)
    return lines, info


def _recent_lines(paths: list[str], max_bytes: int, max_lines: int) -> Iterator[str]:  # pyright: ignore[reportUnusedFunction]
    """Compatibility iterator over the same bounded reader used by the page."""
    yield from _read_tails(paths, max_bytes, max_lines)[0]


def _parse_record(line: str, utc: bool) -> tuple[_RequestRecord, bool] | None:
    parts = line.split(";")
    if len(parts) not in (3, 4, 7):
        return None
    asctime, endpoint, duration = parts[:3]
    if not endpoint or len(endpoint) > 256:
        return None
    try:
        # logging.Formatter uses a comma before milliseconds; normalize it for
        # the narrower fromisoformat parser on supported older Python versions.
        timestamp = datetime.fromisoformat(asctime.replace(",", "."))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc if utc else timezone(timedelta(hours=3)))
        timestamp = timestamp.astimezone(timezone.utc)
        elapsed = float(duration) / 1_000_000
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(elapsed) or elapsed < 0:
        return None
    status = None
    if len(parts) >= 4 and parts[3].isascii() and parts[3].isdigit() and len(parts[3]) == 3:
        candidate = int(parts[3])
        if 100 <= candidate <= 599:
            status = candidate
    request_id = parts[4] if len(parts) == 7 else None
    if not request_id or len(request_id) > 128 or request_id.startswith("["):
        request_id = None
    return _RequestRecord(timestamp, endpoint, elapsed, status, request_id), len(parts) != 7


def _load_snapshot(now: datetime, hours: int, max_bytes: int, max_lines: int, max_files: int, utc: bool) -> _Snapshot:
    try:
        paths = get_log_fpath_all(bafser_config.log_dashboard_path, limit=max_files + 1)
        lines, info = _read_tails(paths[:max_files], max_bytes, max_lines)
    except OSError:
        paths, lines, info = [], [], _ReadInfo(read_errors=1)
    info.files_limited = len(paths) > max_files
    cutoff = now - timedelta(hours=hours)
    records: list[_RequestRecord] = []
    invalid_rows = future_rows = legacy_rows = 0
    for line in lines:
        parsed = _parse_record(line, utc)
        if parsed is None:
            invalid_rows += 1
            continue
        record, legacy = parsed
        if record.timestamp > now:
            future_rows += 1
            continue
        if record.timestamp < cutoff:
            continue
        legacy_rows += legacy
        records.append(record)
    records.sort(key=lambda item: item.timestamp)
    return _Snapshot(tuple(records), now, info, invalid_rows, future_rows, legacy_rows)


def _snapshot(now: datetime, hours: int, *, refresh: bool) -> _Snapshot:
    max_bytes = _setting("DASHBOARD_MAX_BYTES", 2 * 1024 * 1024)
    max_lines = _setting("DASHBOARD_MAX_LINES", 20000)
    max_files = _setting("DASHBOARD_MAX_FILES", 6)
    cache_seconds = _setting("DASHBOARD_CACHE_SECONDS", 3, minimum=0)
    utc = bool(getattr(bafser_config, "datetime_utc", False))
    key = (os.path.abspath(bafser_config.log_dashboard_path), hours, max_bytes, max_lines, max_files, utc, cache_seconds)
    cache = cast(_SnapshotCache, current_app.extensions.setdefault(_CACHE_KEY, _SnapshotCache()))
    with cache.lock:
        if cache_seconds and not refresh and cache.key == key and cache.snapshot is not None and time.monotonic() < cache.expires:
            return cache.snapshot
        snapshot = _load_snapshot(now, hours, max_bytes, max_lines, max_files, utc)
        cache.key, cache.snapshot = key, snapshot
        cache.expires = time.monotonic() + cache_seconds
        return snapshot


def _filters(max_hours: int) -> tuple[int, str, str, bool]:
    if not has_request_context():
        return max_hours, "", "all", False
    try:
        hours = int(request.args.get("hours", str(max_hours)))
    except ValueError:
        abort(400, description="Invalid dashboard period")
    endpoint = request.args.get("endpoint", "")
    status = request.args.get("status", "all")
    numeric_status = status.isascii() and status.isdigit() and len(status) == 3 and 100 <= int(status) <= 599
    if not 1 <= hours <= max_hours or len(endpoint) > 256:
        abort(400, description="Invalid dashboard filter")
    if status not in ("all", "errors", "4xx", "5xx", "unknown") and not numeric_status:
        abort(400, description="Invalid dashboard status")
    return hours, endpoint, status, request.args.get("refresh") == "1"


def _matches_status(record: _RequestRecord, status: str) -> bool:
    if status == "all":
        return True
    if status == "unknown":
        return record.status is None
    if record.status is None:
        return False
    if status == "errors":
        return record.status >= 400
    if status == "4xx":
        return 400 <= record.status < 500
    if status == "5xx":
        return record.status >= 500
    return record.status == int(status)


def _percentile(values: list[float], fraction: float) -> float | None:
    """Linear interpolation on sorted samples, including a single sample."""
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _stats(records: list[_RequestRecord]) -> StatsDict:
    durations = sorted(item.duration_ms for item in records)
    return {
        "count": len(records),
        "client_errors": sum(item.status is not None and 400 <= item.status < 500 for item in records),
        "server_errors": sum(item.status is not None and item.status >= 500 for item in records),
        "unknown_status": sum(item.status is None for item in records),
        "p50": _percentile(durations, 0.5),
        "p95": _percentile(durations, 0.95),
        "max": durations[-1] if durations else None,
    }


def _trend(records: list[_RequestRecord], cutoff: datetime, now: datetime, display_zone: timezone) -> list[StatsDict]:
    seconds = max(60, int((now - cutoff).total_seconds() / 48 // 60) * 60)
    count = math.ceil((now - cutoff).total_seconds() / seconds)
    buckets: list[StatsDict] = []
    for index in range(count):
        start = cutoff + timedelta(seconds=index * seconds)
        buckets.append({"label": start.astimezone(display_zone).strftime("%Y-%m-%d %H:%M"), "count": 0, "errors": 0})
    for record in records:
        index = min(int((record.timestamp - cutoff).total_seconds() // seconds), count - 1)
        buckets[index]["count"] += 1
        buckets[index]["errors"] += record.status is not None and record.status >= 400
    peak = max((item["count"] for item in buckets), default=1) or 1
    for bucket in buckets:
        bucket["height"] = round(bucket["count"] / peak * 100, 2)
        bucket["error_height"] = round(bucket["errors"] / peak * 100, 2)
    return buckets


def render_dashboard_page() -> str:
    """Render bounded request diagnostics; the application owns its route/access."""
    max_hours = _setting("DASHBOARD_WINDOW_HOURS", 24)
    recent_limit = _setting("DASHBOARD_RECENT_LIMIT", 50)
    hours, endpoint, status, refresh = _filters(max_hours)
    snapshot = _snapshot(datetime.now(timezone.utc), max_hours, refresh=refresh)
    # Another thread may refresh the cache while this caller waits for its lock.
    # Choose the rendered interval afterwards, never before the snapshot's clock.
    now = max(datetime.now(timezone.utc), snapshot.created_at)
    cutoff = now - timedelta(hours=hours)
    records = [
        item
        for item in snapshot.records
        if item.timestamp >= cutoff and (not endpoint or item.endpoint == endpoint) and _matches_status(item, status)
    ]
    grouped: dict[str, list[_RequestRecord]] = {}
    for record in records:
        grouped.setdefault(record.endpoint, []).append(record)
    endpoints = [{"endpoint": name, **_stats(items)} for name, items in grouped.items()]
    endpoints.sort(key=lambda item: (-item["count"], item["endpoint"]))  # type: ignore
    display_zone = timezone.utc if getattr(bafser_config, "datetime_utc", False) else timezone(timedelta(hours=3))
    recent: list[StatsDict] = []
    for item in reversed(records):
        if item.status is None or item.status < 400:
            continue
        recent.append(
            {
                "time": item.timestamp.astimezone(display_zone).strftime("%Y-%m-%d %H:%M:%S"),
                "endpoint": item.endpoint,
                "status": item.status,
                "duration_ms": item.duration_ms,
                "request_id": item.request_id,
            }
        )
        if len(recent) == recent_limit:
            break
    endpoint_options = sorted({item.endpoint for item in snapshot.records} | ({endpoint} if endpoint else set()))
    status_options = sorted({str(item.status) for item in snapshot.records if item.status is not None})
    if status.isdigit() and status not in status_options:
        status_options.append(status)
        status_options.sort()
    period_options = sorted({value for value in (1, 3, 6, 12, 24, 48, 72, 168, hours, max_hours) if value <= max_hours})
    return render_template(
        _template_dashboard,
        dashboard={
            "stats": _stats(records),
            "endpoints": endpoints,
            "recent": recent,
            "trend": _trend(records, cutoff, now, display_zone),
            "filters": {"hours": hours, "endpoint": endpoint, "status": status},
            "period_options": period_options,
            "endpoint_options": endpoint_options,
            "status_options": status_options,
            "window_start": cutoff.astimezone(display_zone).strftime("%Y-%m-%d %H:%M:%S"),
            "window_end": now.astimezone(display_zone).strftime("%Y-%m-%d %H:%M:%S"),
            "observed_start": records[0].timestamp.astimezone(display_zone).strftime("%Y-%m-%d %H:%M:%S") if records else None,
            "observed_end": records[-1].timestamp.astimezone(display_zone).strftime("%Y-%m-%d %H:%M:%S") if records else None,
            "timezone": "UTC" if display_zone == timezone.utc else "UTC+03:00",
            "snapshot_age": max(0, int((now - snapshot.created_at).total_seconds())),
            "read": snapshot.read_info,
            "invalid_rows": snapshot.invalid_rows,
            "future_rows": snapshot.future_rows,
            "legacy_rows": snapshot.legacy_rows,
            "recent_limit": recent_limit,
        },
    )
