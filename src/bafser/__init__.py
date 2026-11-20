# base for flask server by Mixel Te

from .configuration import load_config

bafser_config = load_config()

from .validate_config import validate_config
from .undefined import Undefined, U, UD
from .public_error import PublicError
from .constants import Constants

validate_config(bafser_config)

# ruff: isort: skip_file
from .utils.response_msg import response_msg
from .utils.get_json_values import get_json_values, get_json_list

from .utils.abort_if_none import abort_if_none
from .utils.create_file_response import create_file_response
from .utils.create_folder_for_file import create_folder_for_file
from .utils.get_datetime_now import get_datetime_now, get_datetime_utc
from .utils.get_db_session import get_db_session, override_get_db_session
from .utils.get_json import get_json
from .utils.get_json_values_from_req import get_json_values_from_req, get_json_list_from_req
from .utils.get_userId import get_userId_required, get_userId
from .utils.ip_to_emoji import ip_to_emoji, emoji_to_ip
from .utils.jsonify_list import jsonify_list
from .utils.listfind import listfind
from .utils.normalized_column import (
    normalized_column,
    normalize_search,
    normalized_update_values,
    rebuild_normalized_columns,
    NormalizationError,
    NormalizedValueTooLongError,
)
from .utils.parse_date import parse_date, parse_date_required, parse_datetime
from .utils.permission_required import create_permission_required_decorator  # pyright: ignore[reportDeprecated]
from .utils.permission_required import permission_required, permission_required_any  # pyright: ignore[reportDeprecated]
from .utils.protected_route import protected_route
from .utils.randstr import randstr
from .utils.response_not_found import response_not_found
from .utils.strfind import strfind
from .utils.truncate_string import TruncateString
from .utils.transaction_files import track_created_file
from .utils.use_db_session import use_db_session, use_db_sess
from .utils.use_user import use_user  # pyright: ignore[reportDeprecated]
from .utils.use_userId import use_userId  # pyright: ignore[reportDeprecated]

from .app import AppConfig, AccessControlHeaders, RequestPolicy, request_policy, create_app, update_message_to_frontend, get_app_config
from .logger import get_logger_frontend, log_frontend_error, get_log_fpath, get_log_fpath_all, add_logger, create_log_handler, ParametrizedLogger
from .authentication import create_access_token, get_user_by_jwt_identity, get_user_id_by_jwt_identity
from .jsonobj import JsonObj, JsonOpt, JsonParseError, UnionParseError
from .doc_api import doc_api, get_api_docs, TJson, TJsonListOf, render_docs_page
from .dashboard import render_dashboard_page

from .db_session import SqlAlchemyBase, get_engine, dispose_engine
from .table_base import IdMixin, ObjMixin, SingletonMixin, BigIdMixin
from .locking import ForUpdateRequiredError, LockNotSupportedError
from .data._tables import TablesBase
from .data._roles import RolesBase
from .data.operation import OperationsBase, OperationDict, TOperation
from .data.user_role import UserRole
from .data.user import UserBase, UserKwargs, UserDict, UserDictFull, override_get_current_user
from .data.log import Log, LogDict
from .data.role import Role, RoleDict
from .data.image import Image, ImageError, ImageKwargs, ImageDict, ImageJson


class M:
    DELETE = "DELETE"
    GET = "GET"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    PATCH = "PATCH"
    POST = "POST"
    PUT = "PUT"


__all__ = [
    "UD",
    "AccessControlHeaders",
    "AppConfig",
    "BigIdMixin",
    "Constants",
    "ForUpdateRequiredError",
    "IdMixin",
    "Image",
    "ImageDict",
    "ImageError",
    "ImageJson",
    "ImageKwargs",
    "JsonObj",
    "JsonOpt",
    "JsonParseError",
    "LockNotSupportedError",
    "Log",
    "LogDict",
    "M",
    "NormalizationError",
    "NormalizedValueTooLongError",
    "ObjMixin",
    "OperationDict",
    "OperationsBase",
    "ParametrizedLogger",
    "PublicError",
    "Role",
    "RoleDict",
    "RolesBase",
    "RequestPolicy",
    "SingletonMixin",
    "SqlAlchemyBase",
    "TJson",
    "TJsonListOf",
    "TOperation",
    "TablesBase",
    "TruncateString",
    "U",
    "Undefined",
    "UnionParseError",
    "UserBase",
    "UserDict",
    "UserDictFull",
    "UserKwargs",
    "UserRole",
    "abort_if_none",
    "add_logger",
    "create_access_token",
    "create_app",
    "create_file_response",
    "create_folder_for_file",
    "create_log_handler",
    "create_permission_required_decorator",
    "doc_api",
    "dispose_engine",
    "emoji_to_ip",
    "get_api_docs",
    "get_app_config",
    "get_datetime_now",
    "get_datetime_utc",
    "get_db_session",
    "get_engine",
    "get_json",
    "get_json_list",
    "get_json_list_from_req",
    "get_json_values",
    "get_json_values_from_req",
    "get_log_fpath",
    "get_log_fpath_all",
    "get_logger_frontend",
    "get_userId",
    "get_userId_required",
    "get_user_by_jwt_identity",
    "get_user_id_by_jwt_identity",
    "ip_to_emoji",
    "jsonify_list",
    "listfind",
    "log_frontend_error",
    "load_config",
    "normalize_search",
    "normalized_column",
    "normalized_update_values",
    "override_get_current_user",
    "override_get_db_session",
    "parse_date",
    "parse_date_required",
    "parse_datetime",
    "permission_required",
    "permission_required_any",
    "protected_route",
    "randstr",
    "rebuild_normalized_columns",
    "render_dashboard_page",
    "render_docs_page",
    "response_msg",
    "request_policy",
    "response_not_found",
    "strfind",
    "track_created_file",
    "update_message_to_frontend",
    "use_db_sess",
    "use_db_session",
    "use_user",
    "use_userId",
    "validate_config",
]
