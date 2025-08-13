import datetime
from typing import Any, Callable


class SerializerMixin:
    """
    Mixin for retrieving public fields of sqlAlchemy-model in json-compatible format with no pain
    Can be inherited to redefine get_tzinfo callback, datetime formats or to add some extra serialization logic
    """
    serialize_only: tuple[str, ...] = ...
    serialize_rules: tuple[str, ...] = ...
    serialize_types: tuple[str, ...] = ...
    date_format: str = ...
    datetime_format: str = ...
    time_format: str = ...
    decimal_format: str = ...
    serializable_keys: tuple[str, ...] = ...
    auto_serialize_properties: bool = ...

    def get_tzinfo(self) -> datetime.tzinfo | None:
        """
        Callback to make serializer aware of user's timezone. Should be redefined if needed
        Example:
            return pytz.timezone('Asia/Krasnoyarsk')

        :return: datetime.tzinfo
        """
        ...

    def to_dict(self,
                only: list[str] | tuple[str, ...] = ...,
                rules: list[str] | tuple[str, ...] = ...,
                date_format: str = ...,
                datetime_format: str = ...,
                time_format: str = ...,
                tzinfo: datetime.tzinfo = ...,
                decimal_format: str = ...,
                serialize_types: list[tuple[type, Callable[[Any], Any]]] = ...
                ) -> dict[str, Any]:
        """
        Returns SQLAlchemy model's data in JSON compatible format

        For details about datetime formats follow:
        https://docs.python.org/3/library/datetime.html#strftime-and-strptime-behavior

        :param only: exclusive schema to replace default one (always have higher priority than rules)
        :param rules: schema to extend default one or schema defined in "only"
        :param date_format: str
        :param datetime_format: str
        :param time_format: str
        :param decimal_format: str
        :param serialize_types:
        :param tzinfo: datetime.tzinfo converts datetimes to local user timezone
        :return: data: dict
        """
        ...


__all__ = ["SerializerMixin"]
