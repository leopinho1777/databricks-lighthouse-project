"""Unit tests for grupo10.ingest — no cluster required.

Spark is fully mocked with MagicMock so these tests run without Databricks Connect.
"""

from unittest.mock import MagicMock, patch, call
from grupo10.ingest import (
    _build_jdbc_base_options,
    ensure_control_table,
    ensure_metadata_columns,
    get_last_processed_id,
    update_control_table,
    CONTROL_TABLE_DDL,
)


# ---------------------------------------------------------------------------
# _build_jdbc_base_options
# ---------------------------------------------------------------------------


class TestBuildJdbcBaseOptions:
    def test_returns_dict(self):
        result = _build_jdbc_base_options("jdbc://host", "user", "pass")
        assert isinstance(result, dict)

    def test_contains_url(self):
        result = _build_jdbc_base_options("jdbc://host", "user", "pass")
        assert result["url"] == "jdbc://host"

    def test_contains_credentials(self):
        result = _build_jdbc_base_options("jdbc://host", "myuser", "mypass")
        assert result["user"] == "myuser"
        assert result["password"] == "mypass"

    def test_driver_is_sqlserver(self):
        result = _build_jdbc_base_options("jdbc://host", "u", "p")
        assert result["driver"] == "com.microsoft.sqlserver.jdbc.SQLServerDriver"

    def test_encrypt_true(self):
        result = _build_jdbc_base_options("jdbc://host", "u", "p")
        assert result["encrypt"] == "true"

    def test_trust_server_certificate(self):
        result = _build_jdbc_base_options("jdbc://host", "u", "p")
        assert result["trustServerCertificate"] == "true"

    def test_login_timeout(self):
        result = _build_jdbc_base_options("jdbc://host", "u", "p")
        assert result["loginTimeout"] == "30"

    def test_seven_keys_total(self):
        result = _build_jdbc_base_options("jdbc://host", "u", "p")
        assert len(result) == 7


# ---------------------------------------------------------------------------
# ensure_control_table
# ---------------------------------------------------------------------------


class TestEnsureControlTable:
    def test_calls_spark_sql(self, mock_spark):
        ensure_control_table(mock_spark, "catalog.schema._control")
        mock_spark.sql.assert_called_once()

    def test_sql_contains_table_name(self, mock_spark):
        ensure_control_table(mock_spark, "catalog.schema._control")
        sql_call = mock_spark.sql.call_args[0][0]
        assert "catalog.schema._control" in sql_call

    def test_sql_contains_create_if_not_exists(self, mock_spark):
        ensure_control_table(mock_spark, "my.table")
        sql_call = mock_spark.sql.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS" in sql_call


# ---------------------------------------------------------------------------
# ensure_metadata_columns
# ---------------------------------------------------------------------------


class TestEnsureMetadataColumns:
    def test_skips_when_table_does_not_exist(self, mock_spark):
        mock_spark.catalog.tableExists.return_value = False
        ensure_metadata_columns(mock_spark, "catalog.schema.table")
        mock_spark.sql.assert_not_called()

    def test_no_alter_when_all_columns_present(self, mock_spark):
        from pyspark.sql.types import StructType, StructField, StringType, TimestampType

        mock_spark.catalog.tableExists.return_value = True
        schema = StructType(
            [
                StructField("_ingested_at", TimestampType()),
                StructField("_source_origin", StringType()),
                StructField("_batch_id", StringType()),
            ]
        )
        mock_spark.read.table.return_value.schema.fields = schema.fields
        ensure_metadata_columns(mock_spark, "catalog.schema.table")
        mock_spark.sql.assert_not_called()

    def test_alters_missing_columns(self, mock_spark):
        from pyspark.sql.types import StructType, StructField, StringType

        mock_spark.catalog.tableExists.return_value = True
        # Only one metadata column present
        schema = StructType([StructField("_ingested_at", StringType())])
        mock_spark.read.table.return_value.schema.fields = schema.fields

        ensure_metadata_columns(mock_spark, "catalog.schema.table")

        # Two missing columns → two ALTER TABLE calls
        assert mock_spark.sql.call_count == 2

    def test_alter_contains_add_column(self, mock_spark):
        from pyspark.sql.types import StructType

        mock_spark.catalog.tableExists.return_value = True
        mock_spark.read.table.return_value.schema.fields = []  # all columns missing

        ensure_metadata_columns(mock_spark, "my.table")

        for call_args in mock_spark.sql.call_args_list:
            assert "ALTER TABLE" in call_args[0][0]
            assert "ADD COLUMN" in call_args[0][0]


# ---------------------------------------------------------------------------
# get_last_processed_id
# ---------------------------------------------------------------------------


class TestGetLastProcessedId:
    def test_returns_minus_one_when_control_table_missing(self, mock_spark):
        mock_spark.catalog.tableExists.return_value = False
        result = get_last_processed_id(mock_spark, "catalog.schema._control", "my_table")
        assert result == -1

    def test_returns_minus_one_when_no_record(self, mock_spark):
        mock_spark.catalog.tableExists.return_value = True
        mock_df = MagicMock()
        mock_df.filter.return_value = mock_df
        mock_df.isEmpty.return_value = True
        mock_spark.read.table.return_value = mock_df
        result = get_last_processed_id(mock_spark, "catalog.schema._control", "my_table")
        assert result == -1

    def test_returns_correct_id(self, mock_spark):
        mock_spark.catalog.tableExists.return_value = True
        mock_df = MagicMock()
        mock_df.filter.return_value = mock_df
        mock_df.isEmpty.return_value = False
        mock_df.select.return_value.collect.return_value = [[42]]
        mock_spark.read.table.return_value = mock_df
        result = get_last_processed_id(mock_spark, "catalog.schema._control", "my_table")
        assert result == 42


# ---------------------------------------------------------------------------
# update_control_table
# ---------------------------------------------------------------------------


class TestUpdateControlTable:
    def test_creates_dataframe_with_update_data(self, mock_spark):
        with patch("grupo10.ingest.DeltaTable") as mock_delta:
            mock_delta.forName.return_value.alias.return_value.merge.return_value.whenMatchedUpdateAll.return_value.whenNotMatchedInsertAll.return_value.execute = MagicMock()
            update_control_table(mock_spark, "my.control", "customers", 500)
            mock_spark.createDataFrame.assert_called_once()
            rows, schema = mock_spark.createDataFrame.call_args[0]
            assert rows[0][0] == "customers"
            assert rows[0][1] == 500

    def test_calls_delta_merge(self, mock_spark):
        with patch("grupo10.ingest.DeltaTable") as mock_delta:
            merge_chain = mock_delta.forName.return_value.alias.return_value.merge.return_value.whenMatchedUpdateAll.return_value.whenNotMatchedInsertAll.return_value
            merge_chain.execute = MagicMock()
            update_control_table(mock_spark, "my.control", "orders", 100)
            merge_chain.execute.assert_called_once()
