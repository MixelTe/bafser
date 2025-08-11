from sqlalchemy import Column, orm, String
from sqlalchemy.orm import Session

from .. import SqlAlchemyBase, ObjMixin, get_datetime_now
from ._roles import RoleDesc, RolesBase, TRole, get_roles
from ._tables import TablesBase
from .log import Actions, Log
from .operation import Operation, get_operations
from .permission import Permission


class Role(SqlAlchemyBase, ObjMixin):
    __tablename__ = TablesBase.Role

    name = Column(String(32), nullable=False)

    permissions = orm.relationship("Permission")

    def __repr__(self):
        return f"<Role> [{self.id}] {self.name}"

    def get_dict(self):
        return self.to_dict(only=("id", "name"))

    @staticmethod
    def update_roles_permissions(db_sess: Session):
        ROLES = get_roles().ROLES
        # add new operations
        operations_new = list(get_operations().get_all())
        operations_new_ids = [v[0] for v in operations_new]
        operations_cur = list(db_sess.query(Operation).all())
        operations_cur_ids = [v.id for v in operations_cur]
        for operation in operations_new:
            operation_id, operation_name = operation
            if operation_id not in operations_cur_ids:
                db_sess.add(Operation(id=operation_id, name=operation_name))

        # update roles
        roles_new_ids = ROLES.keys()
        roles = db_sess.query(Role).all()
        roles_cur_ids = [v.id for v in roles]
        removed_roles: list[int] = []
        restored_roles: list[int] = []
        updated_roles: list[tuple[int, str, str]] = []
        for role in list(roles):
            # delete removed roles
            if role.id not in roles_new_ids and role.id != RolesBase.admin:
                role.deleted = True
                removed_roles.append(role.id)
                for permission in list(role.permissions):
                    db_sess.delete(permission)
                continue

            # restore role with old id
            if role.deleted:
                role.deleted = False
                restored_roles.append(role.id)

            # get role data
            if role.id == RolesBase.admin:
                name = "Админ"
                operations = operations_new
            else:
                name = ROLES[role.id]["name"]
                operations = ROLES[role.id]["operations"]
            operations_ids = [v[0] for v in operations]

            # update role name
            if role.name != name:
                updated_roles.append((role.id, role.name, name))
                role.name = name

            # delete removed permissions
            cur_permissions: list[Permission] = list(role.permissions)
            for permission in cur_permissions:
                if permission.operationId not in operations_ids:
                    db_sess.delete(permission)

            # add new permissions
            cur_operations_ids = [v.operationId for v in cur_permissions]
            for operation in operations:
                operation_id = operation[0]
                if operation_id not in cur_operations_ids:
                    db_sess.add(Permission(roleId=role.id, operationId=operation_id))

        # delete removed operations
        for operation in operations_cur:
            if operation.id not in operations_new_ids:
                db_sess.delete(operation)

        # add new roles
        new_roles: list[tuple[int, str]] = []
        admin_role: tuple[TRole, RoleDesc] = (RolesBase.admin, {"name": "Админ", "operations": operations_new})
        for role_id, role_data in [admin_role, *list(ROLES.items())]:
            if role_id in roles_cur_ids:
                continue
            name, operations = role_data["name"], role_data["operations"]

            role = Role(name=name, id=role_id)
            new_roles.append((role_id, name))
            db_sess.add(role)

            for operation in operations:
                db_sess.add(Permission(roleId=role_id, operationId=operation[0]))

        now = get_datetime_now()

        def log_role(actionCode, recordId, changes):
            db_sess.add(Log(
                date=now,
                actionCode=actionCode,
                userId=1,
                userName="System",
                tableName=TablesBase.Role,
                recordId=recordId,
                changes=changes
            ))

        for role_id in removed_roles:
            log_role(Actions.deleted, role_id, [])
        for role_id in restored_roles:
            log_role(Actions.restored, role_id, [])
        for (role_id, old_name, name) in updated_roles:
            log_role(Actions.updated, role_id, [("name", old_name, name)])
        for (role_id, name) in new_roles:
            log_role(Actions.added, role_id, [("name", None, name)])

        db_sess.commit()
