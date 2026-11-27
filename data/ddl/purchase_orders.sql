CREATE TABLE lh_nautical.bronze.purchase_orders (
  id INT,
  po_number STRING COLLATE UTF8_BINARY,
  supplier_id INT,
  buyer_id INT,
  destination_location_id INT,
  status STRING COLLATE UTF8_BINARY,
  currency STRING COLLATE UTF8_BINARY,
  subtotal DECIMAL(14,2),
  total DECIMAL(14,2),
  placed_at TIMESTAMP,
  expected_delivery_at DATE,
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
