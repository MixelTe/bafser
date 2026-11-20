import copy
import datetime
import heapq
import json
import logging
import logging.handlers
import os
import re
import sys
import time
import traceback
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode

from concurrent_log_handler import ConcurrentRotatingFileHandler
from flask import g, has_request_context, request

import bafser_config

from .utils.create_folder_for_file import create_folder_for_file
from .utils.ip_to_emoji import ip_to_emoji

SENSITIVE_FIELD_NAMES = frozenset(
    {
        "password",
        "password_hash",
        "passwd",
        "passphrase",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "secret",
        "api_secret_key",
        "apikey",
        "api_key",
        "client_secret",
        "code",
        "email",
        "buyer_email",
        "customer_email",
        "payer_email",
        "recipient",
        "to",
        "phone",
        "address",
        "name",
        "full_name",
        "first_name",
        "last_name",
        "person_name",
        "person_link",
        "attendee_name",
        "visitor_name",
        "customer_name",
        "payer_name",
        "card_number",
        "cardholder",
        "pan",
        "cvv",
        "cvc",
        "signature",
        "checksum",
        "sign",
        "return_url",
        "redirect_url",
        "success_url",
        "fail_url",
    }
)
_SENSITIVE_NAMES = frozenset(re.sub(r"[^a-z0-9]", "", name.casefold()) for name in SENSITIVE_FIELD_NAMES)
_OWNED_HANDLER = "_bafser_handler"
_OMITTED = "[omitted by log policy]"
MaxBytes = 8 * 1000 * 1000
BackupCount = 5


def _get_config() -> Any:
    from .app import get_app_config

    try:
        return get_app_config()
    except RuntimeError:
        return None
    except AssertionError:
        from .app import _config  # pyright: ignore[reportPrivateUsage]

        # Before the first app exists, get_app_config asserts its global fallback.
        if _config is not None:
            raise
        return None


def get_request_log_policy() -> Any:
    """Return the effective policy without reading a request or response body."""
    if has_request_context() and "request_policy" in g:
        return g.request_policy
    return getattr(_get_config(), "REQUEST_POLICY", None)


def _dev_mode() -> bool:
    return bool(getattr(_get_config(), "DEV_MODE", False))


def log_error_details() -> bool:
    """Server messages/exceptions are complete by default, independently of HTTP data."""
    config = _get_config()
    return bool(getattr(config, "DEV_MODE", False) or getattr(config, "LOG_ERROR_DETAILS", True))


def should_log_body() -> bool:
    configured = getattr(get_request_log_policy(), "log_body", None)
    return _dev_mode() if configured is None else configured


def _max_log_length() -> int:
    maximum = getattr(get_request_log_policy(), "max_log_length", 2048)
    return maximum if type(maximum) is int and maximum > 0 else 2048


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def redact_sensitive_data(
    value: Any,
    *,
    sensitive_fields: tuple[str, ...] = (),
    body_fields: tuple[str, ...] | None = None,
    max_length: int = 4096,
) -> Any:
    """Return a bounded log-safe copy; untrusted object repr is never evaluated.

    This is explicitly a redactor, independent of DEV_MODE. App/request logging
    should use format_log_data, which selects complete dev or bounded prod data.
    A body_fields allowlist selects exact root object keys; other root JSON
    types are omitted. Allowed fields may contain nested values, still redacted.
    """
    if body_fields is not None and not isinstance(value, Mapping):
        return _OMITTED
    sensitive = _SENSITIVE_NAMES | {_normalized_name(name) for name in sensitive_fields}
    allowed = None if body_fields is None else set(body_fields)
    remaining = max(0, max_length)
    nodes = 128

    def visit(item: Any, depth: int = 0) -> Any:
        nonlocal remaining, nodes
        if remaining <= 0 or nodes <= 0 or depth > 8:
            return "[truncated]"
        nodes -= 1
        if isinstance(item, str):
            res = item[:remaining]
            remaining -= len(res)
            return res + ("[truncated]" if len(res) < len(item) else "")
        if item is None or type(item) in (bool, int, float):
            remaining -= 24
            return item
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for key, child in item.items():  # pyright: ignore[reportUnknownVariableType]
                if remaining <= 0 or nodes <= 0:
                    result["[truncated]"] = True
                    break
                # Bound work on keys too: a huge key must not cause a full scan.
                nodes -= 1
                if not isinstance(key, str):
                    result["[non-string key]"] = "[omitted]"
                    continue
                if len(key) > 256:
                    # Even a prefix can disclose an unapproved field name.
                    continue
                if depth == 0 and allowed is not None and key not in allowed:
                    continue
                normalized = _normalized_name(key)
                remaining -= len(key) + 4
                result[key] = "***" if normalized in sensitive else visit(child, depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            result_list: list[Any] = []
            for child in item:  # pyright: ignore[reportUnknownVariableType]
                if remaining <= 0 or nodes <= 0:
                    result_list.append("[truncated]")
                    break
                result_list.append(visit(child, depth + 1))
            return result_list
        remaining -= 16
        return "[non-JSON value]"

    return visit(value)


def format_log_data(value: Any) -> str | None:
    """Format already available JSON according to request policy; None means omit."""
    if not should_log_body():
        return None
    if _dev_mode():
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError, RecursionError):
            return "[unserializable JSON]"
    policy = get_request_log_policy()
    maximum = _max_log_length()
    safe_value = redact_sensitive_data(
        value,
        sensitive_fields=getattr(policy, "sensitive_fields", ()),
        body_fields=getattr(policy, "body_fields", None),
        max_length=maximum,
    )
    try:
        result = json.dumps(safe_value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return "[unserializable JSON]"
    return result if len(result) <= maximum else result[:maximum] + "[truncated]"


def format_log_url() -> str:
    """Apply query policy; dev keeps permitted queries complete, prod masks them."""
    if not has_request_context():
        return ""
    dev = _dev_mode()
    path = request.path
    if not dev:
        path = request.url_rule.rule if request.url_rule is not None else "[unmatched]"
    policy = get_request_log_policy()
    log_query = getattr(policy, "log_query", None)
    if log_query is False or not request.query_string:
        return path
    if dev:
        return request.full_path
    if log_query is not True:
        return path
    raw = request.query_string[: _max_log_length()].decode("utf8", errors="replace")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, max_num_fields=64)
    except ValueError:
        return path + "?[query omitted]"
    # Provider-specific query names may also hold secrets: retain names only.
    masked = [(key if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", key) else "[field]", "***") for key, _ in pairs]
    suffix = urlencode(masked)
    return path + "?" + suffix[: _max_log_length()]


def customTime(*args: Any):
    utc_dt = datetime.datetime.now(datetime.timezone.utc)
    if not getattr(bafser_config, "datetime_utc", False):
        utc_dt += datetime.timedelta(hours=3)
    return utc_dt.timetuple()


def _field(value: Any) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n").replace(";", "\\u003b")


class InfoFilter(logging.Filter):
    def filter(self, record: logging.LogRecord):
        return record.levelno == logging.INFO and record.name == "root"


class RequestFormatter(logging.Formatter):
    converter = customTime
    max_msg_len = -1
    max_json_len = 2048
    json_indent: int | None = None
    outer_args: list[str] | None = None

    def format(self, record: logging.LogRecord):
        try:
            return self._format(record)
        except Exception:
            if _dev_mode():
                raise
            if log_error_details():
                # Do not retry logging or dump the original message/arguments.
                return "[log formatting failed]\n" + traceback.format_exc()
            return "[log formatting failed]"

    def _format(self, record: logging.LogRecord):
        # A LogRecord is shared among handlers; never alter another handler's input.
        record = copy.copy(record)
        dev = _dev_mode()
        details = log_error_details()
        if has_request_context():
            record.url = _field(format_log_url())
            record.method = _field(request.method)
            record.endpoint = _field(request.endpoint or "[unmatched]")
            record.ip = _field(request.remote_addr or "")
            record.ip_emoji = _field(ip_to_emoji(request.remote_addr or ""))
            record.req_id = _field(g.get("req_id", getattr(record, "req_id", "")))
            record.uid = _field(g.get("userId", getattr(record, "uid", "")))
            g_json = g.get("json")
            record.json = _OMITTED
            if should_log_body() and g_json is not None and g_json[1]:
                record.json = format_log_data(g_json[0]) or ""
            start = g.get("req_start")
            if start is not None:
                record.duration = time.perf_counter_ns() - start
        elif not dev:
            # Extra fields supplied by a background caller are not a substitute
            # for formatting structured data through the policy helper.
            record.json = _OMITTED
            record.url = "[background]"
        metadata_fields = ("url", "method", "endpoint", "ip", "ip_emoji", "req_id", "json", "uid", "duration", "code")
        for name in metadata_fields:
            if not hasattr(record, name):
                setattr(record, name, f"[{name}]")
        if not dev:
            if self.max_json_len > 0 and len(record.json) > self.max_json_len:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownArgumentType, reportUnknownMemberType]
                record.json = record.json[: self.max_json_len] + "[truncated]"  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
        if not details:
            if getattr(record, "bafser_safe_message", False) is not True:
                record.msg = _OMITTED
                record.args = ()
            else:
                # Trusted callers mark constants or data already formatted by policy.
                message = record.getMessage()
                maximum = _max_log_length()
                if self.max_msg_len > 0:
                    maximum = min(maximum, self.max_msg_len)
                record.msg = message[:maximum] + ("[truncated]" if len(message) > maximum else "")
                record.args = ()
            if record.exc_info is not None:
                exc_type, _, tb = record.exc_info
                frames = traceback.extract_tb(tb, limit=-16)
                # Source lines and exception values may themselves contain credentials.
                record.exc_text = "\n".join(
                    [f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}' for frame in frames]
                    + [exc_type.__name__ if exc_type is not None else "Exception"]
                )
                maximum = _max_log_length()
                if len(record.exc_text) > maximum:
                    record.exc_text = "[truncated]\n" + record.exc_text[-maximum:]
                record.exc_info = None
            elif record.exc_text:
                record.exc_text = "[exception details omitted]"
            if record.stack_info:
                record.stack_info = "[stack details omitted]"
        if self.outer_args:
            for arg in self.outer_args:
                if not dev and arg in metadata_fields:
                    continue
                value = record.args.get(arg, f"[{arg}]") if isinstance(record.args, dict) else f"[{arg}]"
                setattr(record, arg, str(value) if details else _OMITTED)
        if not dev and details and self.max_msg_len > 0:
            message = record.getMessage()
            record.msg = message[: self.max_msg_len] + ("[truncated]" if len(message) > self.max_msg_len else "")
            record.args = ()
        return super().format(record)


class _PrivateLogErrors(logging.Handler):
    def handleError(self, record: logging.LogRecord):
        if _dev_mode():
            return super().handleError(record)
        try:
            if log_error_details():
                # Standard handleError also dumps raw Message/Arguments, which
                # could bypass HTTP data policy. Print only the write failure.
                sys.stderr.write("bafser log write failed\n")
                traceback.print_exc(file=sys.stderr)
                return
            error_type = sys.exc_info()[0]
            name = error_type.__name__ if error_type is not None else "Exception"
            sys.stderr.write(f"bafser log write failed ({name})\n")
        except (OSError, UnicodeError):
            pass


class RotatingFileHandler(_PrivateLogErrors, logging.handlers.RotatingFileHandler):
    """Single-process logging with standard basename.N rotation and retention."""


class _ConcurrentFileHandler(_PrivateLogErrors, ConcurrentRotatingFileHandler):
    pass


def get_log_fpath(fpath: str, next: bool = False) -> str:
    """Return the current log path or its first standard rotation path."""
    return fpath + ".1" if next else fpath


def get_log_fpath_all(fpath: str, *, limit: int | None = None) -> list[str]:
    """List active and newest archives, accepting standard and legacy names."""
    directory = os.path.dirname(os.path.abspath(fpath))
    basename = os.path.basename(fpath)
    stem, extension = os.path.splitext(basename)
    pattern = re.compile(rf"(?:{re.escape(basename)}\.\d+|{re.escape(stem)}\.\d+{re.escape(extension)})\Z")
    if limit is not None and limit <= 0:
        return []

    def archive_records():
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if pattern.fullmatch(entry.name) and entry.is_file():
                            yield entry.stat().st_mtime_ns, entry.path
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            return

    # With a dashboard limit, do not retain every legacy archive in memory.
    archives = sorted(archive_records(), reverse=True) if limit is None else heapq.nlargest(limit - 1, archive_records())
    result = [fpath] + [path for _, path in archives]
    return result


def _remove_owned_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _OWNED_HANDLER, False):
            logger.removeHandler(handler)
            handler.close()


def setLogging(*, configure_root: bool = True):
    """Install own handlers without clearing the embedding application's handlers.

    Set configure_root=False when the host owns general error logging. Existing
    non-bafser handlers remain the host application's privacy responsibility.
    """
    logger = logging.getLogger()
    _remove_owned_handlers(logger)
    if configure_root:
        if not logger.handlers:
            logger.setLevel(logging.DEBUG if _dev_mode() else logging.INFO)
        logger.addHandler(
            create_log_handler(
                bafser_config.log_errors_path,
                "[%(asctime)s] %(ip_emoji)s (%(req_id)s by uid=%(uid)s) %(method)s %(url)s | "
                "%(levelname)s in %(module)s:%(lineno)s:\nReq json: %(json)s\n%(message)s\n",
                logging.WARNING,
            )
        )
        logger.addHandler(
            create_log_handler(
                bafser_config.log_info_path,
                "%(req_id)s;%(ip_emoji)s;%(uid)s;%(asctime)s;%(method)s;%(url)s;%(module)s;%(message)s",
                filter=InfoFilter(),
            )
        )
    add_logger(
        "requests",
        create_log_handler(
            bafser_config.log_requests_path,
            "%(req_id)s;%(ip_emoji)s;%(uid)s;%(asctime)s;%(method)s;%(url)s;%(message)s",
        ),
    )
    add_logger(
        "frontend",
        create_log_handler(
            bafser_config.log_frontend_path,
            "[%(asctime)s] %(ip_emoji)s (uid=%(uid)s):\n%(json)s\n%(message)s\n",
        ),
    )
    add_logger(
        "dashboard",
        create_log_handler(
            bafser_config.log_dashboard_path,
            "%(asctime)s;%(endpoint)s;%(duration)s;%(code)s;%(req_id)s;%(ip)s;%(uid)s",
        ),
    )


def get_logger_frontend():
    return logging.getLogger("frontend")


def get_logger_requests():
    return logging.getLogger("requests")


def get_logger_dashboard():
    return logging.getLogger("dashboard")


def log_frontend_error(msg: str | None = None):
    get_logger_frontend().info(msg or "")


def add_logger(name: str, handler: logging.Handler):
    logger = logging.getLogger(name)
    _remove_owned_handlers(logger)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def create_log_handler(
    fpath: str,
    format: str = "%(levelname)s in %(module)s: %(message)s",
    level: int = logging.INFO,
    *,
    outer_args: list[str] | None = None,
    max_msg_len: int = -1,
    max_json_len: int = 4096,
    json_indent: int | None = None,
    filter: logging.Filter | None = None,
):
    config = _get_config()
    if getattr(config, "AUTO_SETUP", True) or "--setup" in sys.argv:
        create_folder_for_file(fpath)
    elif not os.path.isdir(os.path.dirname(os.path.abspath(fpath))):
        raise FileNotFoundError("Log directory does not exist; run setup before runtime")
    formatter = RequestFormatter(format)
    formatter.max_msg_len = max_msg_len
    formatter.max_json_len = max_json_len
    formatter.outer_args = outer_args
    formatter.json_indent = json_indent
    handler_class = _ConcurrentFileHandler if getattr(config, "MULTIPROCESS_LOGGING", False) else RotatingFileHandler
    handler = handler_class(fpath, mode="a", encoding="utf8", maxBytes=MaxBytes, backupCount=BackupCount)
    handler.setFormatter(formatter)
    if filter is not None:
        handler.addFilter(filter)
    handler.setLevel(level)
    setattr(handler, _OWNED_HANDLER, True)
    return handler


class ParametrizedLogger:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def _get_args(self) -> object:
        raise Exception("not implemented")

    def info(self, msg: object):
        self.__log(self.logger.info, msg)

    def error(self, msg: object):
        self.__log(self.logger.error, msg)

    def warning(self, msg: object):
        self.__log(self.logger.warning, msg)

    def __log(self, fn: Any, msg: object):
        fn(msg, self._get_args(), stacklevel=3)
