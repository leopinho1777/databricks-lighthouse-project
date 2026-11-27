CREATE TABLE lh_nautical.bronze.payments (
  id INT,
  order_id INT,
  method STRING COLLATE UTF8_BINARY,
  installments SMALLINT,
  amount DECIMAL(14,2),
  status STRING COLLATE UTF8_BINARY,
  paid_at TIMESTAMP,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  _ingested_at TIMESTAMP,
  _source_origin STRING COLLATE UTF8_BINARY,
  _batch_id STRING COLLATE UTF8_BINARY)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.feature.appendOnly' = 'supported',
  'delta.feature.deletionVectors' = 'supported',
  'delta.feature.invariants' = 'supported',
  'delta.minReaderVersion' = '3',
  'delta.minWriterVersion' = '7',
  'delta.parquet.compression.codec' = 'zstd',
  'delta.parquet.format.version' = '2.12.0',
  'delta.parquet.format.version.afe.internal' = '2.12.0')
;
