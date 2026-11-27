CREATE TABLE lh_nautical.bronze._ingestion_control (
  source_table STRING COLLATE UTF8_BINARY NOT NULL COMMENT 'Source table being ingested',
  last_processed_id BIGINT NOT NULL COMMENT 'Last incremental key value successfully processed',
  updated_at TIMESTAMP NOT NULL COMMENT 'UTC timestamp of the last update')
USING delta
COMMENT 'Incremental ingestion control state'
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
