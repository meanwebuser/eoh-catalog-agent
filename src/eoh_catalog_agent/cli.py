from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .pipeline import prepare_catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eoh-catalog-agent",
        description="Prepare checked Shopify and WooCommerce catalog imports.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="Normalize a supplier CSV/XLSX catalog")
    prepare.add_argument("input", type=Path, help="Supplier .csv or .xlsx file")
    prepare.add_argument("--out", type=Path, required=True, help="Output directory")
    prepare.add_argument(
        "--store",
        choices=("shopify", "woocommerce", "both"),
        default="both",
        help="Import format to produce (default: both)",
    )
    prepare.add_argument("--limit", type=int, help="Process only the first N rows for a paid test batch")
    prepare.add_argument("--job-id", default="", help="Marketplace or Arena job identifier")
    prepare.add_argument("--revenue-usd", help="Revenue attributed to this completed batch")
    prepare.add_argument("--expense-usd", help="Compute/API expense attributed to this batch")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stores = ("shopify", "woocommerce") if args.store == "both" else (args.store,)
    try:
        receipt = prepare_catalog(
            args.input,
            args.out,
            stores=stores,
            limit=args.limit,
            job_id=args.job_id,
            revenue_usd=args.revenue_usd,
            expense_usd=args.expense_usd,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if not receipt["ready_products"]:
        return 3
    if receipt["blocked_products"]:
        return 4
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
