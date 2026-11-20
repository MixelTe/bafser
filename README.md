# bafser

A synchronous Flask and SQLAlchemy foundation for small applications and services:
typed JSON schemas, JWT authentication, permissions, audit logs, model helpers,
transaction-aware files, a bounded request dashboard and a project generator.
Python 3.10 or newer.

## Start a small project

Install `bafser` in your Python environment, then run:

```sh
bafser init_project
```

The first invocation creates `bafser_config.py` if it is missing. Edit that file,
then rerun the generator and answer `n` when it asks whether you want to change
the ready configuration. Existing files are preserved unless `--force` is
supplied. `--directory PATH` selects the project directory.

For a small SQLite prototype, set `use_alembic = False` in the generated config:

```sh
bafser init_project
python main.py dev
```

The generated one-process entry point can prepare its database and storage at
startup with `AUTO_SETUP=True`. `DEV_MODE=True` enables full diagnostic logging.
For a migration-managed application, create the initial revision before starting
it; see the [guide](documentation.md#database-migrations).

## Production

Use `AUTO_SETUP=False` for normal web/worker startup and perform setup explicitly:

```sh
python main.py --setup
```

Enable `MULTIPROCESS_LOGGING=True` when processes share log files. Keep persistent
storage and keys outside replaceable release directories. Server logs retain
messages and full exceptions by default; `LOG_ERROR_DETAILS=False` selects
reduced production diagnostics. Per-route `RequestPolicy` controls body limits
and HTTP data logging; production bodies and queries are omitted by default.

See [deployment and security](documentation.md#deployment-and-security) for keys,
migrations, JWT validation, proxy configuration, database pools and backups.

## Documentation

- [Guide and API contracts](documentation.md): quick start, `Undefined`, schemas,
  transactions, authentication, files and deployment.
- [Agent notes](AGENTS.md): short reminders for code-generating agents.

Dependency bounds and package metadata are maintained in
[pyproject.toml](pyproject.toml). The library keeps a small-project workflow;
production requirements are configured explicitly by the application.
