import os
import re

from alembic import command
from alembic.script import ScriptDirectory

import bafser_config

from ..alembic import create_alembic_config


def init(args: list[str]):
    print("alembic init")

    os.makedirs(bafser_config.migrations_folder, exist_ok=True)
    os.makedirs(os.path.join(bafser_config.migrations_folder, "versions"), exist_ok=True)
    for path, content in (
        (os.path.join(bafser_config.migrations_folder, "env.py"), "from bafser.alembic import run\n\nrun()\n"),
        (os.path.join(bafser_config.migrations_folder, "script.py.mako"), script_py_mako),
    ):
        try:
            with open(path, "w" if "--force" in args else "x", encoding="utf8") as f:
                f.write(content)
        except FileExistsError:
            print(f"Skipping existing file: {path}")


def revision(args: list[str]):
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
    print(f'alembic revision --autogenerate -m "{name}"')
    command.revision(alembic_cfg, name, True)


def upgrade(args: list[str]):
    alembic_cfg = create_alembic_config(dev="--prod" not in args)
    command.upgrade(alembic_cfg, "head")


def downgrade(args: list[str]):
    if len(args) < 1:
        print("alembic downgrade: error: the following arguments are required: revision")
        return
    alembic_cfg = create_alembic_config(dev="--prod" not in args)
    command.downgrade(alembic_cfg, args[0])


def run(args: list[str]):
    scripts = [
        ("init", "[--force] : create folders and files", init),
        ("revision", "[name] : autogenerate migration script", revision),
        ("upgrade", "[--prod] : upgrade head", upgrade),
        ("downgrade", "<revision> [--prod] : downgrade <revision>", downgrade),
    ]

    if len(args) == 0 or args[0] not in (v[0] for v in scripts):
        ml = max(len(v[0]) for v in scripts)
        ml2 = max(len(v[1]) for v in scripts)
        l = ml + ml2 + 5
        t = " Scripts "
        l2 = l - len(t)
        print("-" * (l2 // 2) + t + "-" * (l2 // 2 + l2 % 2))
        print("\n".join(f"{' ' * (ml - len(v[0]))} {v[0]} : {v[1]}" for v in scripts))
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
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''
