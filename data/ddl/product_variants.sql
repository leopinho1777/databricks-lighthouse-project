CREATE TABLE lh_nautical.bronze.product_variants (
  id INT,
  product_id INT,
  sku STRING COLLATE UTF8_BINARY,
  barcode_ean STRING COLLATE UTF8_BINARY,
  sale_price DECIMAL(14,2),
  cost_price DECIMAL(14,2),
  weight_kg DECIMAL(10,3),
  icms_rate DECIMAL(5,2),
  ipi_rate DECIMAL(5,2),
  is_active BOOLEAN,
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
