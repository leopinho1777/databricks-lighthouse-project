CREATE TABLE lh_nautical.bronze.suppliers (
  id INT,
  legal_name STRING COLLATE UTF8_BINARY MASK `lh_nautical`.`bronze`.`regra_mascaramento`,
  trade_name STRING COLLATE UTF8_BINARY MASK `lh_nautical`.`bronze`.`regra_mascaramento`,
  country STRING COLLATE UTF8_BINARY,
  tax_id STRING COLLATE UTF8_BINARY MASK `lh_nautical`.`bronze`.`regra_mascaramento`,
  tax_id_type STRING COLLATE UTF8_BINARY,
  email STRING COLLATE UTF8_BINARY,
  phone STRING COLLATE UTF8_BINARY,
  contact_name STRING COLLATE UTF8_BINARY,
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
