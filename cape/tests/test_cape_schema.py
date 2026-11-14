"""The entrypoint brings CAPE's database to the schema of the CAPE in the image.

CAPE answers a database of an older schema by printing "DB schema version mismatch" and exiting
with status 0: every CAPE program would then die at import while the entrypoint saw success. A
database an earlier image made is therefore migrated before anything else touches it, and a
schema CAPE still refuses stops the container. Proven against the real database by starting the
stack on a database of the previous CAPE pin; these keep the entrypoint from drifting.
"""

from pathlib import Path

ENTRYPOINT = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()


def function_body(name: str) -> str:
    start = ENTRYPOINT.index(f"\n{name}() {{\n")
    return ENTRYPOINT[start : ENTRYPOINT.index("\n}\n", start)]


def test_a_database_of_an_older_cape_is_migrated_before_its_schema_is_checked():
    calls = ENTRYPOINT[ENTRYPOINT.rindex("\nmake_network_sysctls_writable\n") :]

    assert calls.index("\nmigrate_cape_schema\n") < calls.index("\ncreate_cape_schema\n")


def test_the_migration_is_capes_own_run_as_the_cape_user():
    migrate = function_body("migrate_cape_schema")

    assert "cd /opt/CAPEv2/utils/db_migration" in migrate
    assert "runuser -u cape -- /opt/CAPEv2/.venv/bin/alembic upgrade head" in migrate


def test_a_new_database_is_left_to_cape_to_create():
    # alembic's revisions alter tables; on a database without any they fail, and CAPE creates a
    # new database at its current schema itself.
    assert "cape_database_has_a_schema || return 0" in function_body("migrate_cape_schema")


def test_a_schema_cape_refuses_stops_the_container():
    create = function_body("create_cape_schema")

    assert "except SystemExit" in create
    assert "sys.exit(1)" in create
