from typing import Type, TypedDict

from ..utils.get_all_vars import get_all_fields


Roles: "Type[RolesBase]" = None


def get_roles():
    if Roles is None:
        raise Exception("[bafser] No class inherited from RolesBase")
    return Roles


class RoleDesc(TypedDict):
    name: str
    operations: list[tuple[str, str]]


TRole = int
TRoles = dict[TRole, RoleDesc]


class RolesBase:
    admin = 1

    ROLES: TRoles = {}

    def __init_subclass__(cls, **kwargs):
        global Roles
        Roles = cls
        fields = list(get_all_fields(cls()))
        same = []
        for i in range(len(fields)):
            for k in range(i + 1, len(fields)):
                if fields[i][1] == fields[k][1]:
                    same.append((fields[i][0], fields[k][0], fields[i][1]))
        if len(same) > 0:
            raise Exception(f"[bafser] Same ids for Role: {'; '.join(f'{n1} and {n2} is {v}' for (n1, n2, v) in same)}")
