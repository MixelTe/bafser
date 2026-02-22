import datetime
import json
import logging
import logging.handlers
import os
import time
from typing import Any

from flask import g, has_request_context, request

import bafser_config
from bafser import create_folder_for_file, ip_to_emoji


def customTime(*args: Any):
    utc_dt = datetime.datetime.now(datetime.timezone.utc)
    utc_dt += datetime.timedelta(hours=3)
    return utc_dt.timetuple()


class InfoFilter(logging.Filter):
    def filter(self, record: Any):
        return record.levelno == logging.INFO and record.name == "root"


class RequestFormatter(logging.Formatter):
    converter = customTime
    max_msg_len = -1
    max_json_len = 2048
    json_indent: int | None = None
    outer_args: list[str] | None = None

    def format(self, record: Any):
        def set_if_lack(name: str):
            if not hasattr(record, name):
                setattr(record, name, f"[{name}]")

        def get_if_has(name: str):
            if hasattr(record, name):
                return getattr(record, name)
            return ""

        if has_request_context():
            url_start = request.url.find(bafser_config.api_url)
            record.url = request.url[url_start:] if url_start >= 0 else request.url
            record.method = request.method
            record.endpoint = request.endpoint
            remote_addr = request.headers.get("X-Real-IP", request.remote_addr or "")
            record.ip = remote_addr
            record.ip_emoji = ip_to_emoji(remote_addr)
            record.req_id = g.get("req_id", get_if_has("req_id"))
            record.uid = g.get("userId", get_if_has("uid"))
            g_json = g.get("json", None)
            if g_json is not None and g_json[1]:
                record.json = json.dumps(g_json[0], indent=self.json_indent)
            req_start = g.get("req_start", None)
            if req_start:
                record.duration = time.perf_counter_ns() - req_start
        set_if_lack("url")
        set_if_lack("method")
        set_if_lack("endpoint")
        set_if_lack("ip")
        set_if_lack("ip_emoji")
        set_if_lack("req_id")
        set_if_lack("json")
        set_if_lack("uid")
        set_if_lack("duration")
        set_if_lack("code")

        if self.max_msg_len > 0 and len(record.msg) > self.max_msg_len:
            record.msg = record.msg[: self.max_msg_len] + "..."

        if self.max_json_len > 0 and len(record.json) > self.max_json_len:
            record.json = record.json[: self.max_json_len] + "..."

        if self.outer_args:
            for arg in self.outer_args:
                if isinstance(record.args, dict):  # pyright: ignore[reportUnknownMemberType]
                    value = str(record.args.get(arg, f"[{arg}]"))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                else:
                    value = f"[{arg}]"
                setattr(record, arg, value)

        return super().format(record)


class RotatingFileHandler(logging.handlers.RotatingFileHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        self.rollover = False
        super().__init__(*args, **kwargs)

    def doRollover(self):
        self.rollover = True
        s = self.stream
        self.stream = self._open()
        if s:
            s.close()

    def _open(self):
        filename = get_log_fpath(self.baseFilename, self.rollover)
        self.rollover = False
        bn = self.baseFilename
        self.baseFilename = filename
        r = super()._open()
        self.baseFilename = bn
        return r


def get_log_fpath(fpath: str, next: bool = False) -> str:
    i = 0
    n = fpath.split(".")
    name, ext = (".".join(n[:-1]), n[-1]) if len(n) > 1 else (n[0], "")
    while True:
        i += 1
        npath = f"{name}.{i}.{ext}"
        if not os.path.exists(npath):
            if next:
                return npath
            if i - 1 == 0:
                return fpath
            return f"{name}.{i - 1}.{ext}"


def get_log_fpath_all(fpath: str) -> list[str]:
    r = [fpath]
    i = 0
    n = fpath.split(".")
    name, ext = (".".join(n[:-1]), n[-1]) if len(n) > 1 else (n[0], "")
    while True:
        i += 1
        npath = f"{name}.{i}.{ext}"
        if not os.path.exists(npath):
            return r
        r.append(npath)


MaxBytes = 8 * 1000 * 1000


def setLogging():
    logging.basicConfig(
        level=logging.DEBUG,
        # filename="log.log",
        format="[%(asctime)s] %(levelname)s in %(module)s (%(name)s): %(message)s",
        encoding="utf-8",
    )
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logging.Formatter.converter = customTime

    logger.addHandler(
        create_log_handler(
            bafser_config.log_errors_path,
            "[%(asctime)s] %(ip_emoji)s (%(req_id)s by uid=%(uid)-6s) %(method)-6s %(url)-40s | %(levelname)s in %(module)s (%(name)s):\nReq json: %(json)s\n%(message)s\n",
            logging.WARNING,
            max_json_len=-1,
        )
    )

    logger.addHandler(
        create_log_handler(
            bafser_config.log_info_path,
            "%(req_id)s;%(ip_emoji)s;%(uid)-6s;%(asctime)s;%(method)-4s;%(url)s;%(module)s;%(message)s",
            max_json_len=4096,
            filter=InfoFilter(),
        )
    )

    add_logger(
        "requests",
        create_log_handler(
            bafser_config.log_requests_path,
            "%(req_id)s;%(ip_emoji)s;%(uid)-6s;%(asctime)s;%(method)-4s;%(url)s;%(message)s",
            max_msg_len=1024,
        ),
    )

    add_logger(
        "frontend",
        create_log_handler(
            bafser_config.log_frontend_path,
            "[%(asctime)s] %(ip_emoji)s (uid=%(uid)s):\n%(json)s\n%(message)s\n",
            max_json_len=8192,
            json_indent=4,
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
    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def create_log_handler(
    fpath: str,
    format: str = "%(levelname)s in %(module)s: %(message)s",
    level: "logging._Level" = logging.INFO,  # pyright: ignore[reportPrivateUsage]
    *,
    outer_args: list[str] | None = None,
    max_msg_len: int = -1,
    max_json_len: int = 4096,
    json_indent: int | None = None,
    filter: "logging._FilterType | None" = None,  # pyright: ignore[reportPrivateUsage]
):
    from bafser import get_app_config

    create_folder_for_file(fpath)
    formatter = RequestFormatter(format)
    formatter.max_msg_len = max_msg_len
    formatter.max_json_len = max_json_len
    formatter.outer_args = outer_args
    formatter.json_indent = json_indent

    config = get_app_config()
    if config.THREADED:
        handler = logging.handlers.WatchedFileHandler(fpath, encoding="utf-8")
    else:
        handler = RotatingFileHandler(fpath, mode="a", encoding="utf-8", maxBytes=MaxBytes)

    handler.setFormatter(formatter)
    if filter:
        handler.addFilter(filter)
    handler.setLevel(level)
    handler.encoding = "utf-8"
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
