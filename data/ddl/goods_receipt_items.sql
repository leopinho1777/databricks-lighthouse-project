CREATE TABLE lh_nautical.bronze.goods_receipt_items (
  id INT,
  goods_receipt_id INT,
  purchase_order_item_id INT,
  quantity_received DECIMAL(14,3),
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
