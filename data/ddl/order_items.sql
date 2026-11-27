CREATE TABLE lh_nautical.bronze.order_items (
  id INT,
  order_id INT,
  product_variant_id INT,
  quantity DECIMAL(14,3),
  unit_price DECIMAL(14,2),
  icms_rate DECIMAL(5,2),
  ipi_rate DECIMAL(5,2),
  line_total DECIMAL(14,2),
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
