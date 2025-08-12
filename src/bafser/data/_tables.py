from ..utils import get_all_fields


class TablesBase:
    User = "User"
    Role = "Role"
    UserRole = "UserRole"
    Image = "Image"

    @classmethod
    def get_all(cls):
        return list(get_all_fields(cls()))
