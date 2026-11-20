"""Run the required real-database suite; a skipped test is a CI failure."""

import os
import unittest


def main() -> int:
    if not os.environ.get("BAFSER_TEST_MYSQL_URL"):
        raise SystemExit("BAFSER_TEST_MYSQL_URL is required for the MySQL CI job")
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [
            "test.test_locking.MySQLLockingTests",
            "test.test_auth_refresh_mysql.MySQLAuthRefreshTests",
            "test.test_userbase_roles_mysql.MySQLUserRoleTests",
        ]
    )
    if suite.countTestCases() == 0:
        raise SystemExit("The required MySQL test suite is empty")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print("The required MySQL suite must not skip tests")
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
