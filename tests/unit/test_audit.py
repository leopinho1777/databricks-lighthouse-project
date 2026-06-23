"""Unit tests for grupo10.utils.audit — no cluster required."""

from unittest.mock import MagicMock, patch
from grupo10.utils.audit import ensure_audit_table, write_audit_record, AUDIT_TABLE_DDL


class TestEnsureAuditTable:
    def test_calls_spark_sql(self, mock_spark):
        ensure_audit_table(mock_spark, "catalog.schema._audit")
        mock_spark.sql.assert_called_once()

    def test_sql_contains_table_name(self, mock_spark):
        ensure_audit_table(mock_spark, "catalog.schema._audit")
        sql_call = mock_spark.sql.call_args[0][0]
        assert "catalog.schema._audit" in sql_call

    def test_sql_contains_create_if_not_exists(self, mock_spark):
        ensure_audit_table(mock_spark, "my.audit")
        sql_call = mock_spark.sql.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS" in sql_call


class TestWriteAuditRecord:
    def _write(self, mock_spark, **kwargs):
        defaults = dict(
            table_name="customers",
            status="success",
            duration_seconds=1.5,
            row_count=100,
            error_message=None,
            audit_table="catalog.schema._audit",
        )
        defaults.update(kwargs)
        write_audit_record(mock_spark, **defaults)

    def test_creates_dataframe(self, mock_spark):
        self._write(mock_spark)
        mock_spark.createDataFrame.assert_called_once()

    def test_appends_to_correct_table(self, mock_spark):
        write_obj = mock_spark.createDataFrame.return_value.write
        write_obj.format.return_value.mode.return_value.saveAsTable = MagicMock()
        self._write(mock_spark, audit_table="my.audit_table")
        write_obj.format.return_value.mode.return_value.saveAsTable.assert_called_once_with("my.audit_table")

    def test_write_mode_is_append(self, mock_spark):
        write_obj = mock_spark.createDataFrame.return_value.write
        self._write(mock_spark)
        write_obj.format.return_value.mode.assert_called_once_with("append")

    def test_success_record_has_correct_table_name(self, mock_spark):
        self._write(mock_spark, table_name="orders", status="success")
        record = mock_spark.createDataFrame.call_args[0][0][0]
        assert record[0] == "orders"
        assert record[1] == "success"

    def test_failure_record_includes_error_message(self, mock_spark):
        self._write(mock_spark, status="failed", row_count=None, error_message="JDBC timeout")
        record = mock_spark.createDataFrame.call_args[0][0][0]
        assert record[1] == "failed"
        assert record[2] is None  # row_count
        assert record[4] == "JDBC timeout"

    def test_duration_is_rounded(self, mock_spark):
        self._write(mock_spark, duration_seconds=1.23456789)
        record = mock_spark.createDataFrame.call_args[0][0][0]
        assert record[3] == round(1.23456789, 3)

    def test_uses_delta_format(self, mock_spark):
        write_obj = mock_spark.createDataFrame.return_value.write
        self._write(mock_spark)
        write_obj.format.assert_called_once_with("delta")
