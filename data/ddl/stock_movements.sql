CREATE TABLE lh_nautical.bronze.stock_movements (
  id BIGINT,
  product_variant_id INT,
  location_id INT,
  movement_type STRING COLLATE UTF8_BINARY,
  quantity DECIMAL(14,3),
  reference_table STRING COLLATE UTF8_BINARY,
  reference_id INT,
  employee_id INT,
  notes STRING COLLATE UTF8_BINARY,
  occurred_at TIMESTAMP,
  created_at TIMESTAMP,
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
