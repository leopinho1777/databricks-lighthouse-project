CREATE TABLE lh_nautical.bronze.addresses (
  id INT,
  customer_id INT,
  address_type STRING COLLATE UTF8_BINARY,
  postal_code STRING COLLATE UTF8_BINARY,
  street STRING COLLATE UTF8_BINARY,
  number STRING COLLATE UTF8_BINARY,
  complement STRING COLLATE UTF8_BINARY,
  district STRING COLLATE UTF8_BINARY,
  city STRING COLLATE UTF8_BINARY,
  state STRING COLLATE UTF8_BINARY,
  country STRING COLLATE UTF8_BINARY,
  is_primary BOOLEAN,
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
