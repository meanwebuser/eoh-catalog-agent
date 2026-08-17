from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .pipeline import prepare_catalog
from .deals import DealStore, qualify, render_proposal, should_walk_away
from .economics import (
    InsufficientFunds,
    WalletLedger,
    browser_affordability,
    quote_browser_use,
    quote_dict,
    status_dict,
)


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

    deals = subparsers.add_parser("deal", help="Persist and operate marketplace deal state")
    deals.add_argument("--root", dest="deal_root", type=Path, default=Path(".eoh/deals"), help="Deal-state directory")
    deal_commands = deals.add_subparsers(dest="deal_command", required=True)

    def allow_trailing_root(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--root",
            dest="trailing_deal_root",
            type=Path,
            help="Deal-state directory (also accepted immediately after 'deal')",
        )

    create = deal_commands.add_parser("create", help="Create a deal card")
    allow_trailing_root(create)
    create.add_argument("--id", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--url", required=True)
    create.add_argument("--marketplace", required=True)
    create.add_argument("--budget", default="")
    create.add_argument("--client", default="")
    create.add_argument("--required-phrase", default="")
    create.add_argument("--connects-cost", type=int, default=0)
    create.add_argument("--source-format", default="unknown")
    create.add_argument("--store", default="unknown")
    create.add_argument("--paid-test", action="store_true")
    create.add_argument("--requirements-confirmed", action="store_true")
    create.add_argument("--missing", action="append", default=[])

    show = deal_commands.add_parser("show", help="Show one deal card")
    allow_trailing_root(show)
    show.add_argument("id")

    list_command = deal_commands.add_parser("list", help="List deal cards")
    allow_trailing_root(list_command)
    list_command.add_argument("--active", action="store_true")

    qualify_command = deal_commands.add_parser("qualify", help="Score a deal and persist the decision")
    allow_trailing_root(qualify_command)
    qualify_command.add_argument("id")

    draft = deal_commands.add_parser("draft", help="Render a proposal without sending it")
    allow_trailing_root(draft)
    draft.add_argument("id")

    update = deal_commands.add_parser("update", help="Update verified deal and communication state")
    allow_trailing_root(update)
    update.add_argument("id")
    update.add_argument("--stage", choices=(
        "discovered", "qualified", "drafted", "applied", "negotiating", "won",
        "delivering", "completed", "lost", "walked-away",
    ))
    update.add_argument("--next-action")
    update.add_argument("--next-action-at")
    update.add_argument("--last-message-at")
    update.add_argument("--no-reply-count", type=int)
    update.add_argument("--walk-away-reason")
    update.add_argument("--budget")
    update.add_argument("--client")
    update.add_argument("--required-phrase")
    update.add_argument("--connects-cost", type=int)
    update.add_argument("--source-format")
    update.add_argument("--store")
    update.add_argument("--paid-test", action=argparse.BooleanOptionalAction, default=None)
    update.add_argument("--requirements-confirmed", action=argparse.BooleanOptionalAction, default=None)
    update.add_argument("--clear-missing", action="store_true")
    update.add_argument("--missing", action="append", default=[])
    update.add_argument("--note", action="append", default=[])

    wallet = subparsers.add_parser("wallet", help="Deterministic USD wallet and ledger")
    wallet.add_argument("--root", type=Path, default=Path(".eoh/economy"))
    wallet_commands = wallet.add_subparsers(dest="wallet_command", required=True)
    wallet_init = wallet_commands.add_parser("init", help="Initialize the wallet once")
    wallet_init.add_argument("--balance-usd", required=True)
    wallet_credit = wallet_commands.add_parser("credit", help="Record verified income")
    wallet_credit.add_argument("--amount-usd", required=True)
    wallet_credit.add_argument("--label", required=True)
    wallet_credit.add_argument("--source-id", required=True)
    wallet_commands.add_parser("status", help="Show balance, reservations, and spend")
    wallet_history = wallet_commands.add_parser("history", help="Show append-only ledger entries")
    wallet_history.add_argument("--limit", type=int, default=20)

    step = subparsers.add_parser("step", help="Plan and settle one priced action")
    step.add_argument("--root", type=Path, default=Path(".eoh/economy"))
    step_commands = step.add_subparsers(dest="step_command", required=True)
    step_plan = step_commands.add_parser("plan", help="Write expected cost before acting")
    step_plan.add_argument("--id", required=True)
    step_plan.add_argument("--label", required=True)
    step_plan.add_argument("--estimated-cost-usd", required=True)
    step_plan.add_argument("--reserve", action="store_true")
    step_settle = step_commands.add_parser("settle", help="Write actual cost after acting")
    step_settle.add_argument("--id", required=True)
    step_settle.add_argument("--actual-cost-usd", required=True)
    step_settle.add_argument("--status", default="actual")

    browser = subparsers.add_parser("browser", help="Quote paid Browser Use sessions")
    browser.add_argument("--root", type=Path, default=Path(".eoh/economy"))
    browser_commands = browser.add_subparsers(dest="browser_command", required=True)
    browser_quote = browser_commands.add_parser("quote", help="Calculate browser + proxy cost without an LLM")
    browser_quote.add_argument("--minutes", type=int, default=10)
    browser_quote.add_argument("--proxy-mb", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"wallet", "step", "browser"}:
        ledger = WalletLedger(args.root)
        try:
            if args.command == "wallet":
                if args.wallet_command == "init":
                    result = status_dict(ledger.initialize(args.balance_usd))
                elif args.wallet_command == "credit":
                    result = status_dict(ledger.credit(args.amount_usd, label=args.label, source_id=args.source_id))
                elif args.wallet_command == "status":
                    result = status_dict(ledger.status())
                else:
                    result = {"entries": ledger.latest(args.limit), "status": status_dict(ledger.status())}
            elif args.command == "step":
                if args.step_command == "plan":
                    result = ledger.plan_step(
                        args.id,
                        label=args.label,
                        estimated_cost_usd=args.estimated_cost_usd,
                        reserve=args.reserve,
                    )
                else:
                    result = ledger.settle_step(
                        args.id,
                        actual_cost_usd=args.actual_cost_usd,
                        actual_status=args.status,
                    )
            else:
                quote = quote_dict(quote_browser_use(minutes=args.minutes, proxy_mb=args.proxy_mb))
                quote.update(browser_affordability(
                    available_usd=ledger.status().available_usd,
                    estimated_cost_usd=quote["estimated_cost_usd"],
                ))
                result = quote
        except (FileExistsError, FileNotFoundError, InsufficientFunds, ValueError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "deal":
        store = DealStore(args.trailing_deal_root or args.deal_root)
        try:
            if args.deal_command == "create":
                deal = store.create({
                    "id": args.id,
                    "title": args.title,
                    "url": args.url,
                    "marketplace": args.marketplace,
                    "budget": args.budget,
                    "client": args.client,
                    "required_phrase": args.required_phrase,
                    "connects_cost": args.connects_cost,
                    "source_format": args.source_format,
                    "store": args.store,
                    "paid_test": args.paid_test,
                    "requirements_confirmed": args.requirements_confirmed,
                    "missing": args.missing,
                })
                result = asdict(deal)
            elif args.deal_command == "show":
                result = asdict(store.load(args.id))
            elif args.deal_command == "list":
                result = [asdict(deal) for deal in store.list(active_only=args.active)]
            elif args.deal_command == "qualify":
                deal = store.load(args.id)
                assessment = qualify(deal)
                deal = store.update(args.id, {
                    "fit_score": assessment["fit_score"],
                    "stage": "qualified" if assessment["decision"] == "apply" else deal.stage,
                    "next_action": "draft-proposal" if assessment["decision"] == "apply" else assessment["decision"],
                })
                result = {**assessment, "deal": asdict(deal)}
            elif args.deal_command == "draft":
                deal = store.load(args.id)
                proposal = render_proposal(deal)
                deal = store.update(args.id, {"stage": "drafted", "next_action": "request-user-approval"})
                result = {"deal": asdict(deal), "proposal": proposal, "sent": False}
            else:
                deal = store.load(args.id)
                updates = {
                    key: value
                    for key, value in {
                        "stage": args.stage,
                        "next_action": args.next_action,
                        "next_action_at": args.next_action_at,
                        "last_message_at": args.last_message_at,
                        "no_reply_count": args.no_reply_count,
                        "walk_away_reason": args.walk_away_reason,
                        "budget": args.budget,
                        "client": args.client,
                        "required_phrase": args.required_phrase,
                        "connects_cost": args.connects_cost,
                        "source_format": args.source_format,
                        "store": args.store,
                        "paid_test": args.paid_test,
                        "requirements_confirmed": args.requirements_confirmed,
                    }.items()
                    if value is not None
                }
                if args.note:
                    updates["notes"] = deal.notes + args.note
                if args.clear_missing or args.missing:
                    updates["missing"] = args.missing
                deal = store.update(args.id, updates)
                walk, reason = should_walk_away(deal)
                result = {"deal": asdict(deal), "walk_away": walk, "walk_away_reason": reason}
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

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
