from datetime import datetime, timedelta
import json
import logging
import logging.handlers
import os

from flask import g, has_request_context, request

from bafser import create_folder_for_file, ip_to_emoji
import bafser_config


def customTime(*args):
    utc_dt = datetime.utcnow()
    utc_dt += timedelta(hours=3)
    return utc_dt.timetuple()


class InfoFilter(logging.Filter):
    def filter(self, rec):
        return rec.levelno == logging.INFO and rec.name == "root"


class RequestFormatter(logging.Formatter):
    converter = customTime
    max_msg_len = -1
    max_json_len = 2048
    json_indent = None
    outer_args: list[str] = []

    def format(self, record):
        if has_request_context():
            url_start = request.url.find(bafser_config.api_url)
            record.url = request.url[url_start:] if url_start >= 0 else request.url
            record.method = request.method
            remote_addr = request.headers.get("X-Real-IP", request.remote_addr)
            record.ip = remote_addr
            record.ip_emoji = ip_to_emoji(remote_addr)
            record.req_id = g.get("req_id", "")
            record.uid = g.get("userId", "")
            g_json = g.get("json", None)
            if g_json is not None and g_json[1]:
                record.json = json.dumps(g_json[0], indent=self.json_indent)
            else:
                record.json = "[no json]"
        else:
            record.url = "[url]"
            record.method = "[method]"
            record.ip = "[ip]"
            record.ip_emoji = "[ip_emoji]"
            record.req_id = "[req_id]"
            record.json = "[json]"
            record.uid = "[uid]"

        if self.max_msg_len > 0 and len(record.msg) > self.max_msg_len:
            record.msg = record.msg[:self.max_msg_len] + "..."

        if self.max_json_len > 0 and len(record.json) > self.max_json_len:
            record.json = record.json[:1024] + "..."

        for arg in self.outer_args:
            setattr(record, arg, record.args.get(arg, f"[{arg}]"))

        return super().format(record)


class RotatingFileHandler(logging.handlers.RotatingFileHandler):
    def __init__(self, *kargs, **kwargs):
        self.rollover = False
        super().__init__(*kargs, **kwargs)

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


def get_log_fpath(fpath: str, next=False):
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


MaxBytes = 8 * 1000 * 1000


def setLogging():
    logging.basicConfig(
        level=logging.DEBUG,
        # filename="log.log",
        format="[%(asctime)s] %(levelname)s in %(module)s (%(name)s): %(message)s",
        encoding="utf-8"
    )
    create_folder_for_file(bafser_config.log_errors_path)
    create_folder_for_file(bafser_config.log_info_path)
    create_folder_for_file(bafser_config.log_requests_path)
    create_folder_for_file(bafser_config.log_frontend_path)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logging.Formatter.converter = customTime

    formatter_error = RequestFormatter("[%(asctime)s] %(ip_emoji)s (%(req_id)s by uid=%(uid)-6s) %(method)-6s %(url)-40s | %(levelname)s in %(module)s (%(name)s):\nReq json: %(json)s\n%(message)s\n")  # noqa: E501
    formatter_error.max_json_len = -1
    file_handler_error = RotatingFileHandler(
        bafser_config.log_errors_path, mode="a", encoding="utf-8", maxBytes=MaxBytes)
    file_handler_error.setFormatter(formatter_error)
    file_handler_error.setLevel(logging.WARNING)
    file_handler_error.encoding = "utf-8"
    logger.addHandler(file_handler_error)

    formatter_info = RequestFormatter("%(req_id)s;%(ip_emoji)s;%(uid)-6s;%(asctime)s;%(method)s;%(url)s;%(levelname)s;%(module)s;%(message)s")
    formatter_info.max_json_len = 4096
    file_handler_info = RotatingFileHandler(
        bafser_config.log_info_path, mode="a", encoding="utf-8", maxBytes=MaxBytes)
    file_handler_info.setFormatter(formatter_info)
    file_handler_info.addFilter(InfoFilter())
    file_handler_info.encoding = "utf-8"
    logger.addHandler(file_handler_info)

    logger_requests = get_logger_requests()
    logger_requests.setLevel(logging.DEBUG)
    formatter_req = RequestFormatter("%(req_id)s;%(ip_emoji)s;%(uid)-6s;%(asctime)s;%(method)s;%(url)s;%(levelname)s;%(message)s")
    formatter_req.max_msg_len = 1024
    file_handler_req = RotatingFileHandler(
        bafser_config.log_requests_path, mode="a", encoding="utf-8", maxBytes=MaxBytes)
    file_handler_req.setFormatter(formatter_req)
    file_handler_req.setLevel(logging.INFO)
    file_handler_req.encoding = "utf-8"
    logger_requests.addHandler(file_handler_req)

    logger_frontend = get_logger_frontend()
    logger_frontend.setLevel(logging.DEBUG)
    formatter_frontend = RequestFormatter("[%(asctime)s] %(ip_emoji)s (uid=%(uid)s):\n%(json)s\n%(message)s\n")
    formatter_frontend.max_json_len = 8192
    formatter_frontend.json_indent = 4
    file_handler_frontend = RotatingFileHandler(
        bafser_config.log_frontend_path, mode="a", encoding="utf-8", maxBytes=MaxBytes)
    file_handler_frontend.setFormatter(formatter_frontend)
    file_handler_frontend.setLevel(logging.INFO)
    file_handler_frontend.encoding = "utf-8"
    logger_frontend.addHandler(file_handler_frontend)


def get_logger_frontend():
    return logging.getLogger("frontend")


def get_logger_requests():
    return logging.getLogger("requests")


def log_frontend_error():
    get_logger_frontend().info("")


def add_file_logger(
    fpath: str,
    name: str,
    format="%(req_id)s;%(ip_emoji)s;%(uid)-6s;%(asctime)s;%(method)s;%(url)s;%(levelname)s;%(module)s;%(message)s",
    outer_args: list[str] = [],
    max_json_len=4096
):
    create_folder_for_file(fpath)
    logger = logging.getLogger(name)
    formatter = RequestFormatter(format)
    formatter.max_json_len = max_json_len
    formatter.outer_args = outer_args
    file_handler = RotatingFileHandler(fpath, mode="a", encoding="utf-8", maxBytes=MaxBytes)
    file_handler.setFormatter(formatter)
    file_handler.encoding = "utf-8"
    logger.addHandler(file_handler)
    return logger


class ParametrizedLogger:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def _get_args(self):
        return {}

    def info(self, msg: str):
        self._log(self.logger.info, msg)

    def error(self, msg: str):
        self._log(self.logger.error, msg)

    def warning(self, msg: str):
        self._log(self.logger.warning, msg)

    def _log(self, fn, msg: str):
        fn(msg, self._get_args(), stacklevel=3)
