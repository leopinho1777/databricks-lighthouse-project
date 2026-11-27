CREATE TABLE lh_nautical.bronze.fiscal_invoices (
  id INT,
  order_id INT,
  nfe_number STRING COLLATE UTF8_BINARY,
  nfe_access_key STRING COLLATE UTF8_BINARY MASK `lh_nautical`.`bronze`.`regra_mascaramento`,
  series STRING COLLATE UTF8_BINARY,
  issued_at TIMESTAMP,
  status STRING COLLATE UTF8_BINARY,
  total_amount DECIMAL(14,2),
  xml_storage_uri STRING COLLATE UTF8_BINARY MASK `lh_nautical`.`bronze`.`regra_mascaramento`,
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
