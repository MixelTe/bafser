import os
import re
from alembic import command
from alembic.script import ScriptDirectory
from ..alembic import create_alembic_config

import bafser_config


def init(args):
    print("alembic init")

    os.makedirs(bafser_config.migrations_folder, exist_ok=True)
    os.makedirs(os.path.join(bafser_config.migrations_folder, "versions"), exist_ok=True)
    with open(os.path.join(bafser_config.migrations_folder, "env.py"), "w", encoding="utf8") as f:
        f.write("from bafser.alembic import run\n\nrun()\n")
    with open(os.path.join(bafser_config.migrations_folder, "script.py.mako"), "w", encoding="utf8") as f:
        f.write(script_py_mako)


def revision(args):
    alembic_cfg = create_alembic_config(dev=True)
    if len(args) == 0:
        script = ScriptDirectory.from_config(alembic_cfg)
        maxV = 0
        for s in os.scandir(script.versions):
            m = re.match("\\d{4}_\\d{2}_\\d{2}_[a-z\\d]+_v(\\d+)\\.py", s.name)
            if not m:
                continue
            maxV = max(maxV, int(m.group(1)))
        name = f"v{maxV + 1}"
    else:
        name = args[0]
    print(f"alembic revision --autogenerate -m \"{name}\"")
    command.revision(alembic_cfg, name, True)


def run(args):
    scripts = [
        ("init", "create folders and files", init),
        ("revision", "[name] : autogenerate migration script", revision),
    ]

    if len(args) == 0 or args[0] not in map(lambda v: v[0], scripts):
        ml = max(map(lambda v: len(v[0]), scripts))
        ml2 = max(map(lambda v: len(v[1]), scripts))
        l = ml + ml2 + 5
        t = " Scripts "
        l2 = (l - len(t))
        print("-" * (l2 // 2) + t + "-" * (l2 // 2 + l2 % 2))
        print("\n".join(map(lambda v: f"{' ' * (ml - len(v[0]))} {v[0]} : {v[1]}", scripts)))
        print("-" * l)
        return

    for s in scripts:
        if args[0] == s[0]:
            s[2](args[1:])


script_py_mako = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''
