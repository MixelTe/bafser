import json
import os
from datetime import datetime
from typing import Any

import jinja2
from flask import render_template

import bafser_config

from .logger import get_log_fpath_all

_loc = os.path.abspath(os.path.dirname(__file__))
_templateEnv = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(_loc, "templates")))
_template_dashboard = _templateEnv.get_template("dashboard.html")


def render_dashboard_page():
    logs = get_log_fpath_all(bafser_config.log_dashboard_path)
    endpoints: dict[str, dict[str, int]] = {}
    for log in logs:
        if not os.path.exists(log):
            continue
        with open(log, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split(";")
                try:
                    asctime, endpoint, duration, code, req_id, ip, uid = parts  # pyright: ignore[reportUnusedVariable]
                    t = datetime.fromisoformat(asctime)
                    # key = t.strftime("%Y-%m-%d %H:%M")
                    key = t.strftime("%Y-%m-%d %H")
                    group = endpoints.get(key, {})
                    endpoints[key] = group
                    v = group.get(endpoint, 0)
                    group[endpoint] = v + 1
                except Exception:
                    pass

    # _template_dashboard = _templateEnv.get_template("dashboard.html")
    return render_template(
        _template_dashboard,
        endpoints=json.dumps(endpoints, default=json_default_datetime),
    )


def json_default_datetime(obj: Any):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError()
