from typing import Any

from .undefined import Undefined


class PublicError(Exception):
    """An error whose message and optional details are safe for API clients."""

    status: int = 400
    code: str | None = None
    details: Any = None

    def __init__(self, message: str, status: int | None = None, code: str | None | Undefined.T = Undefined, details: Any = Undefined):
        super().__init__(message)
        if status is not None:
            self.status = status
        if Undefined.defined(code):
            self.code = code
        if Undefined.defined(details):
            self.details = details

    def get_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"msg": str(self)}
        if self.code is not None:
            result["code"] = self.code
        if self.details is not None:
            result["details"] = self.details
        return result
