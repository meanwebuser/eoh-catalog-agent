from __future__ import annotations

import csv
import json
from pathlib import Path

from eoh_catalog_agent.pipeline import prepare_catalog


FIXTURE = Path(__file__).parent / "fixtures" / "catalog-20.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_twenty_product_canary_writes_both_store_imports(tmp_path: Path) -> None:
    receipt = prepare_catalog(FIXTURE, tmp_path, stores=("shopify", "woocommerce"))

    assert receipt["input_rows"] == 20
    assert receipt["ready_products"] == 20
    assert receipt["blocked_products"] == 0
    assert receipt["duplicate_skus"] == 0

    normalized = read_csv(tmp_path / "products.normalized.csv")
    shopify = read_csv(tmp_path / "shopify_import.csv")
    woocommerce = read_csv(tmp_path / "woocommerce_import.csv")

    assert len(normalized) == 20
    assert len(shopify) == 20
    assert len(woocommerce) == 20
    assert shopify[0]["Variant SKU"] == "YOGA-001"
    assert shopify[0]["Status"] == "draft"
    assert woocommerce[0]["SKU"] == "YOGA-001"
    assert woocommerce[0]["Published"] == "0"
    assert json.loads((tmp_path / "receipt.json").read_text())["ready_products"] == 20


def test_bad_rows_are_quarantined_and_duplicates_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    source.write_text(
        "name,sku,price,image\n"
        "Good product,A-1,10,https://example.com/a.jpg\n"
        "Duplicate product,a-1,12,https://example.com/b.jpg\n"
        "Missing sku,,8,https://example.com/c.jpg\n"
        "Bad price,A-4,free,https://example.com/d.jpg\n",
        encoding="utf-8",
    )

    receipt = prepare_catalog(source, tmp_path / "out", stores=("shopify",))
    issues = read_csv(tmp_path / "out" / "issues.csv")
    normalized = read_csv(tmp_path / "out" / "products.normalized.csv")

    assert receipt["input_rows"] == 4
    assert receipt["ready_products"] == 1
    assert receipt["blocked_products"] == 3
    assert receipt["duplicate_skus"] == 1
    assert len(normalized) == 1
    assert {row["code"] for row in issues} == {
        "duplicate_sku",
        "missing_sku",
        "invalid_price",
    }


def test_xlsx_input_uses_the_same_normalization_pipeline(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Product Name", "SKU", "Price", "Image URL"])
    sheet.append(["Spreadsheet product", "SHEET-1", "12,50", "https://example.com/1.jpg"])
    source = tmp_path / "products.xlsx"
    workbook.save(source)

    receipt = prepare_catalog(source, tmp_path / "out", stores=("woocommerce",))
    rows = read_csv(tmp_path / "out" / "woocommerce_import.csv")

    assert receipt["ready_products"] == 1
    assert rows[0]["Regular price"] == "12.50"


def test_woocommerce_variable_parent_can_have_no_price_and_keeps_variation_link(tmp_path: Path) -> None:
    source = tmp_path / "variables.csv"
    source.write_text(
        "Type,SKU,Name,Regular price,Parent,Categories,Images\n"
        "variable,SHIRT,Shirt,,,Clothing,https://example.com/shirt.jpg\n"
        "variation,SHIRT-BLUE,Shirt - Blue,25,SHIRT,,https://example.com/blue.jpg\n",
        encoding="utf-8",
    )

    receipt = prepare_catalog(source, tmp_path / "out", stores=("woocommerce",))
    rows = read_csv(tmp_path / "out" / "woocommerce_import.csv")

    assert receipt["ready_products"] == 2
    assert receipt["blocked_products"] == 0
    assert rows[0]["Type"] == "variable"
    assert rows[0]["Regular price"] == ""
    assert rows[1]["Type"] == "variation"
    assert rows[1]["Parent"] == "SHIRT"
