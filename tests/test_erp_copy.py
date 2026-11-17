"""The SQL Server -> PostgreSQL type mapping of the ERP copy (no database)."""
import pytest

from text2sql_calorvia.erp_copy import ddl, pg_type


@pytest.mark.parametrize("sqlserver, postgres", [
    ("int", "integer"), ("bit", "boolean"), ("date", "date"), ("datetime2", "timestamp"),
    ("nvarchar(60)", "varchar(60)"), ("varchar(10)", "varchar(10)"), ("nchar(2)", "char(2)"),
    ("nvarchar(max)", "text"), ("decimal(14,2)", "numeric(14,2)"), ("numeric(5,2)", "numeric(5,2)"),
])
def test_types(sqlserver, postgres):
    assert pg_type(sqlserver) == postgres


def test_unknown_type_is_an_error_not_a_guess():
    with pytest.raises(ValueError):
        pg_type("geography")


def test_ddl_lowercases_names_and_keeps_keys():
    tables = [
        {"table_name": "CLI_CLIENT", "columns": [
            {"column_name": "CLI_ID", "data_type": "int", "nullable": False},
            {"column_name": "VDR_ID", "data_type": "int", "nullable": True}],
         "keys": [{"kind": "primary", "definition": "PRIMARY KEY (CLI_ID)"},
                  {"kind": "foreign", "definition": "FOREIGN KEY (VDR_ID) REFERENCES VDR_VENDEUR(VDR_ID)"}]},
    ]
    creates, foreign = ddl(tables)
    assert creates == ["CREATE TABLE dbo.cli_client (\n  cli_id integer NOT NULL,\n  vdr_id integer,\n"
                       "  primary key (cli_id)\n)"]
    assert foreign == ["ALTER TABLE dbo.cli_client ADD CONSTRAINT fk_cli_client_1 "
                       "foreign key (vdr_id) REFERENCES dbo.vdr_vendeur(vdr_id)"]
