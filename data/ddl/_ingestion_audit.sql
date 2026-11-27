CREATE TABLE lh_nautical.bronze._ingestion_audit (
  table_name STRING COLLATE UTF8_BINARY NOT NULL COMMENT 'Source table that was ingested',
  status STRING COLLATE UTF8_BINARY NOT NULL COMMENT 'Outcome: success or failed',
  row_count BIGINT COMMENT 'Number of rows written (null on failure)',
  duration_seconds DOUBLE NOT NULL COMMENT 'Wall-clock time for the ingestion in seconds',
  error_message STRING COLLATE UTF8_BINARY COMMENT 'Exception message (null on success)',
  ingested_at TIMESTAMP NOT NULL COMMENT 'UTC timestamp when the record was written')
USING delta
COMMENT 'Audit log for SQL Server ingestion runs'
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.enableRowTracking' = 'true',
  'delta.feature.appendOnly' = 'supported',
  'delta.feature.deletionVectors' = 'supported',
  'delta.feature.domainMetadata' = 'supported',
  'delta.feature.invariants' = 'supported',
  'delta.feature.rowTracking' = 'supported',
  'delta.minReaderVersion' = '3',
  'delta.minWriterVersion' = '7',
  'delta.parquet.compression.codec' = 'zstd',
  'delta.parquet.format.version' = '2.12.0',
  'delta.parquet.format.version.afe.internal' = '2.12.0')
;
