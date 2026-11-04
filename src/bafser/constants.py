from datetime import date


class Constants:
    """Integer bounds, binary byte units and the MySQL DATE range."""

    INT8_MIN = -128
    INT8_MAX = 127
    UINT8_MAX = 255

    INT16_MIN = -32_768
    INT16_MAX = 32_767
    UINT16_MAX = 65_535

    INT32_MIN = -2_147_483_648
    INT32_MAX = 2_147_483_647
    UINT32_MAX = 4_294_967_295

    INT64_MIN = -9_223_372_036_854_775_808
    INT64_MAX = 9_223_372_036_854_775_807
    UINT64_MAX = 18_446_744_073_709_551_615

    KIB = 1024
    MIB = 1024 * KIB
    GIB = 1024 * MIB
    TIB = 1024 * GIB

    MYSQL_DATE_MIN = date(1000, 1, 1)
    MYSQL_DATE_MAX = date(9999, 12, 31)
