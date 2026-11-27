CREATE TABLE lh_nautical.bronze._alert_run_history (
  task_name STRING COLLATE UTF8_BINARY NOT NULL COMMENT 'Task being tracked for consecutive-failure alerting',
  run_date DATE NOT NULL COMMENT 'Calendar date (UTC) of the scheduled run',
  status STRING COLLATE UTF8_BINARY NOT NULL COMMENT 'Outcome: success or failed',
  recorded_at TIMESTAMP NOT NULL COMMENT 'UTC timestamp when the record was written')
USING delta
COMMENT 'Daily run outcomes used to gate consecutive-failure alerts'
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
