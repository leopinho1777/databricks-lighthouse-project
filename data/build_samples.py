"""Builds small, related CSV samples from the Bronze parquet archive.

Usage (from the repository root; pyarrow is installed with the default "dev" dependency group):

    uv run python data/build_samples.py <path-to>/sqlserver_bronze [--output data/samples]

The selection is deterministic: it starts from a fixed set of sales orders and purchase orders and follows
their foreign keys, so joins between the sample files resolve.
"""

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLES_CONFIG = REPO_ROOT / "databricks" / "ingestion" / "src" / "tables_config.json"

# Row cap for tables that no other table references
MAX_ROWS = 50
# Number of orders taken from each group when choosing the starting rows
RETURNED_ORDERS = 10
EXCHANGED_ORDERS = 5
RECEIVED_PURCHASE_ORDERS = 10
# Days of exchange rates kept before each foreign-currency purchase order
RATE_WINDOW_DAYS = 7

# Small reference tables, copied in full
FULL_TABLES = ("attributes", "brands", "categories", "employees", "locations", "suppliers")

# (child table, column, parent table): every non-null value must exist as an id in the parent sample
FOREIGN_KEYS = (
    ("addresses", "customer_id", "customers"),
    ("categories", "parent_category_id", "categories"),
    ("employees", "primary_location_id", "locations"),
    ("fiscal_invoices", "order_id", "orders"),
    ("goods_receipt_items", "goods_receipt_id", "goods_receipts"),
    ("goods_receipt_items", "purchase_order_item_id", "purchase_order_items"),
    ("goods_receipts", "purchase_order_id", "purchase_orders"),
    ("goods_receipts", "received_by_employee_id", "employees"),
    ("order_items", "order_id", "orders"),
    ("order_items", "product_variant_id", "product_variants"),
    ("orders", "customer_id", "customers"),
    ("orders", "location_id", "locations"),
    ("orders", "salesperson_id", "employees"),
    ("payments", "order_id", "orders"),
    ("product_suppliers", "product_variant_id", "product_variants"),
    ("product_suppliers", "supplier_id", "suppliers"),
    ("product_variants", "product_id", "products"),
    ("products", "brand_id", "brands"),
    ("products", "category_id", "categories"),
    ("purchase_order_items", "product_variant_id", "product_variants"),
    ("purchase_order_items", "purchase_order_id", "purchase_orders"),
    ("purchase_orders", "buyer_id", "employees"),
    ("purchase_orders", "destination_location_id", "locations"),
    ("purchase_orders", "supplier_id", "suppliers"),
    ("return_items", "exchange_variant_id", "product_variants"),
    ("return_items", "order_item_id", "order_items"),
    ("return_items", "return_id", "returns"),
    ("returns", "customer_id", "customers"),
    ("returns", "order_id", "orders"),
    ("returns", "received_at_location_id", "locations"),
    ("stock_levels", "location_id", "locations"),
    ("stock_levels", "product_variant_id", "product_variants"),
    ("stock_movements", "employee_id", "employees"),
    ("stock_movements", "location_id", "locations"),
    ("stock_movements", "product_variant_id", "product_variants"),
    ("variant_attribute_values", "attribute_id", "attributes"),
    ("variant_attribute_values", "product_variant_id", "product_variants"),
)


def load_primary_keys() -> dict[str, list[str]]:
    """Reads the primary key columns of each source table from the ingestion config."""
    tables = json.loads(TABLES_CONFIG.read_text(encoding="utf-8"))["tables"]
    return {
        t["name"]: [t["primary_key"]] if isinstance(t["primary_key"], str) else t["primary_key"] for t in tables
    }


def ordered(rows: list[dict], columns: list[str]) -> list[dict]:
    """Sorts rows by the given columns so the output does not depend on the parquet row order."""
    return sorted(rows, key=lambda row: tuple(row[c] for c in columns))


def keep(rows: list[dict], column: str, values: set) -> list[dict]:
    """Returns the rows whose column value is in the given set."""
    return [row for row in rows if row[column] in values]


def values_of(rows: list[dict], column: str = "id") -> set:
    """Returns the distinct non-null values of a column."""
    return {row[column] for row in rows if row[column] is not None}


def first_per_group(rows: list[dict], columns: tuple[str, ...]) -> list[dict]:
    """Returns the first row (rows must be pre-sorted) of each combination of the given columns."""
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[c] for c in columns), row)
    return list(groups.values())


def select_samples(tables: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Picks the sample rows of every table, starting from a fixed set of orders and purchase orders."""
    sample = {name: tables[name] for name in FULL_TABLES}

    # Sales orders: some with returns, some with exchanges, plus one per status and channel
    returned_ids = [r["order_id"] for r in tables["returns"]][:RETURNED_ORDERS]
    exchange_returns = values_of([r for r in tables["return_items"] if r["action"] == "exchange"], "return_id")
    exchanged_ids = [r["order_id"] for r in keep(tables["returns"], "id", exchange_returns)][:EXCHANGED_ORDERS]
    all_returned = values_of(tables["returns"], "order_id")
    without_return = [o for o in tables["orders"] if o["id"] not in all_returned]
    variety_ids = values_of(first_per_group(without_return, ("status", "channel")))
    sample["orders"] = keep(tables["orders"], "id", set(returned_ids) | set(exchanged_ids) | variety_ids)

    # Everything that hangs off the selected orders
    order_ids = values_of(sample["orders"])
    for name in ("order_items", "payments", "fiscal_invoices", "returns"):
        sample[name] = keep(tables[name], "order_id", order_ids)
    sample["return_items"] = keep(tables["return_items"], "return_id", values_of(sample["returns"]))

    # Purchase orders: one per status and currency, plus a few received ones so receipts are represented
    variety = values_of(first_per_group(tables["purchase_orders"], ("status", "currency")))
    received = [p["id"] for p in tables["purchase_orders"] if p["status"] == "received"][:RECEIVED_PURCHASE_ORDERS]
    sample["purchase_orders"] = keep(tables["purchase_orders"], "id", variety | set(received))
    po_ids = values_of(sample["purchase_orders"])
    sample["purchase_order_items"] = keep(tables["purchase_order_items"], "purchase_order_id", po_ids)
    sample["goods_receipts"] = keep(tables["goods_receipts"], "purchase_order_id", po_ids)
    receipt_ids = values_of(sample["goods_receipts"])
    sample["goods_receipt_items"] = keep(tables["goods_receipt_items"], "goods_receipt_id", receipt_ids)

    # Customers and their addresses
    customer_ids = values_of(sample["orders"], "customer_id") | values_of(sample["returns"], "customer_id")
    sample["customers"] = keep(tables["customers"], "id", customer_ids)
    sample["addresses"] = keep(tables["addresses"], "customer_id", customer_ids)

    # Product variants used anywhere above, and their products
    variant_ids = (
        values_of(sample["order_items"], "product_variant_id")
        | values_of(sample["purchase_order_items"], "product_variant_id")
        | values_of(sample["return_items"], "exchange_variant_id")
    )
    sample["product_variants"] = keep(tables["product_variants"], "id", variant_ids)
    sample["products"] = keep(tables["products"], "id", values_of(sample["product_variants"], "product_id"))

    # Tables that nothing references: related rows only, capped
    for name in ("product_suppliers", "stock_levels", "variant_attribute_values"):
        sample[name] = keep(tables[name], "product_variant_id", variant_ids)[:MAX_ROWS]
    sample["stock_movements"] = select_stock_movements(tables["stock_movements"], sample, variant_ids)

    # Exchange rates on and shortly before the dates of the foreign-currency purchase orders
    rate_dates = {
        p["placed_at"].date() - timedelta(days=offset)
        for p in sample["purchase_orders"]
        if p["currency"] != "BRL" and p["placed_at"] is not None
        for offset in range(RATE_WINDOW_DAYS)
    }
    sample["raw_exchange_rates"] = keep(tables["raw_exchange_rates"], "exchange_date", rate_dates)[:MAX_ROWS]

    # Pipeline control tables: the most recent rows
    for name in ("_ingestion_control", "_ingestion_audit", "_alert_run_history"):
        sample[name] = tables[name][-MAX_ROWS:]

    return sample


def select_stock_movements(movements: list[dict], sample: dict, variant_ids: set) -> list[dict]:
    """Picks movements that point to sampled documents, spread evenly over the movement types."""
    documents = {name: values_of(sample[name]) for name in ("orders", "goods_receipts", "returns")}
    related = [
        m
        for m in movements
        if m["product_variant_id"] in variant_ids
        and (m["reference_table"] is None or m["reference_id"] in documents[m["reference_table"]])
    ]
    groups = {}
    for movement in related:
        groups.setdefault((movement["movement_type"], movement["reference_table"] or ""), []).append(movement)
    per_group = MAX_ROWS // max(len(groups), 1)
    return ordered([m for key in sorted(groups) for m in groups[key][:per_group]], ["id"])


def validate(sample: dict[str, list[dict]], primary_keys: dict[str, list[str]]) -> None:
    """Fails if a sample has a repeated primary key or a foreign key that does not resolve."""
    problems = []
    for name, columns in primary_keys.items():
        keys = [tuple(row[c] for c in columns) for row in sample[name]]
        if len(keys) != len(set(keys)):
            problems.append(f"{name}: repeated primary key")
    for child, column, parent in FOREIGN_KEYS:
        orphans = values_of(sample[child], column) - values_of(sample[parent])
        if orphans:
            problems.append(f"{child}.{column}: {len(orphans)} values missing from {parent}")
    # stock_movements.reference_id points to the table named in reference_table
    for parent in ("orders", "goods_receipts", "returns"):
        references = keep(sample["stock_movements"], "reference_table", {parent})
        if values_of(references, "reference_id") - values_of(sample[parent]):
            problems.append(f"stock_movements.reference_id: values missing from {parent}")
    if problems:
        raise ValueError("Invalid sample: " + "; ".join(problems))


def format_value(value: object) -> object:
    """Formats a value for CSV: empty for null, lowercase booleans, timestamps in UTC without offset."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Writes one sample file with a header row."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows([format_value(row[c]) for c in columns] for row in rows)


def main() -> None:
    """Reads the archive, selects and validates the samples, and writes one CSV per table."""
    parser = argparse.ArgumentParser(description="Build CSV samples from the Bronze parquet archive.")
    parser.add_argument("archive", type=Path, help="archive folder that contains parquet/")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "samples", help="output folder")
    args = parser.parse_args()

    files = sorted((args.archive / "parquet").glob("*.parquet"))
    if not files:
        parser.error(f"no parquet files under {args.archive / 'parquet'}")

    primary_keys = load_primary_keys()
    # Sort order for the tables that have no configured primary key
    sort_columns = primary_keys | {
        "raw_exchange_rates": ["exchange_date", "currency_from", "currency_to"],
        "_ingestion_control": ["source_table"],
        "_ingestion_audit": ["ingested_at", "table_name"],
        "_alert_run_history": ["run_date", "task_name"],
    }

    tables, columns = {}, {}
    for file in files:
        table = pq.read_table(file)
        columns[file.stem] = table.column_names
        tables[file.stem] = ordered(table.to_pylist(), sort_columns[file.stem])

    sample = select_samples(tables)
    validate(sample, primary_keys)
    if set(sample) != set(tables):
        raise ValueError(f"Tables without a sample rule: {sorted(set(tables) ^ set(sample))}")

    args.output.mkdir(parents=True, exist_ok=True)
    for name in sorted(sample):
        write_csv(args.output / f"{name}.csv", columns[name], sample[name])
        print(f"{name:<26} {len(sample[name]):>5} of {len(tables[name]):>7} rows")


if __name__ == "__main__":
    main()
