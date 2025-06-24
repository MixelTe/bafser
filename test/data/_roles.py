from bafser import RolesBase
from test.data._operations import Operations


class Roles(RolesBase):
    user = 2


Roles.ROLES = {
    Roles.user: {
        "name": "User",
        "operations": []
    },
}
