import unittest

from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select

from bafser import Log, Role, TruncateString, UserBase
from bafser.data.operation import Operation


class TruncateStringTests(unittest.TestCase):
    def test_public_type_truncates_on_database_write(self):
        table = Table(
            "items",
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column("value", TruncateString(4), nullable=True),
        )
        engine = create_engine("sqlite://")
        table.metadata.create_all(engine)

        with engine.begin() as connection:
            connection.execute(table.insert(), [{"value": "abcdef"}, {"value": ""}, {"value": None}])
            values = connection.execute(select(table.c.value).order_by(table.c.id)).scalars().all()

        self.assertEqual(values, ["abcd", "", None])

    def test_name_columns_have_128_character_capacity(self):
        types = (
            UserBase.__dict__["name"].column.type,
            Operation.__table__.c.name.type,
            Role.__table__.c.name.type,
            Log.__table__.c.userName.type,
        )
        for type_ in types:
            self.assertIsInstance(type_, TruncateString)
            self.assertEqual(type_.impl.length, 128)  # type: ignore

    def test_length_must_be_positive(self):
        with self.assertRaises(ValueError):
            TruncateString(0)


if __name__ == "__main__":
    unittest.main()
