from decimal import Decimal

import pytest

from eoh_catalog_agent.cli import main
from eoh_catalog_agent.economics import (
    InsufficientFunds,
    WalletLedger,
    quote_browser_use,
)


def test_reservation_and_settlement_recalculate_remaining_money(tmp_path) -> None:
    wallet = WalletLedger(tmp_path)
    wallet.initialize("1.00")

    planned = wallet.plan_step(
        "browser-1",
        label="10 minute paid browser",
        estimated_cost_usd="0.30",
        reserve=True,
    )
    assert planned["available_before_usd"] == "1.000000"
    assert planned["available_after_reservation_usd"] == "0.700000"

    settled = wallet.settle_step("browser-1", actual_cost_usd="0.20")
    assert settled["estimated_cost_usd"] == "0.300000"
    assert settled["actual_cost_usd"] == "0.200000"
    assert settled["variance_usd"] == "-0.100000"
    assert settled["remaining_usd"] == "0.800000"
    assert wallet.status().unpriced_steps == 0


def test_wallet_refuses_purchase_it_cannot_afford(tmp_path) -> None:
    wallet = WalletLedger(tmp_path)
    wallet.initialize("0.05")

    with pytest.raises(InsufficientFunds, match="available"):
        wallet.plan_step(
            "too-expensive",
            label="paid browser",
            estimated_cost_usd="0.06",
            reserve=True,
        )


def test_browser_use_quote_is_decimal_math_without_an_llm() -> None:
    quote = quote_browser_use(minutes=10, proxy_mb=10)

    assert Decimal(quote.browser_cost_usd) == Decimal("0.010000")
    assert Decimal(quote.proxy_cost_usd) == Decimal("0.097657")
    assert Decimal(quote.estimated_cost_usd) == Decimal("0.107657")


def test_every_step_keeps_estimate_and_actual_in_append_only_history(tmp_path) -> None:
    wallet = WalletLedger(tmp_path)
    wallet.initialize("2")
    wallet.plan_step("search-1", label="search marketplace", estimated_cost_usd="0.01")
    wallet.settle_step("search-1", actual_cost_usd="0.008", actual_status="actual")

    history = wallet.entries()
    assert [entry["kind"] for entry in history] == ["credit", "plan", "settle"]
    assert history[1]["estimated_cost_usd"] == "0.010000"
    assert history[2]["actual_cost_usd"] == "0.008000"


def test_cli_reports_affordability_and_projected_remaining(tmp_path, capsys, monkeypatch) -> None:
    assert main(["wallet", "--root", str(tmp_path), "init", "--balance-usd", "1"]) == 0
    capsys.readouterr()

    monkeypatch.setenv("EOH_MINIMUM_RESERVE_USD", "0.95")
    assert main(["browser", "--root", str(tmp_path), "quote", "--minutes", "10", "--proxy-mb", "10"]) == 0
    output = capsys.readouterr().out
    assert '"minimum_reserve_usd": "0.950000"' in output
    assert '"can_afford": false' in output
    assert '"projected_remaining_usd": "0.892343"' in output


def test_verified_income_requires_a_source_receipt(tmp_path) -> None:
    wallet = WalletLedger(tmp_path)
    wallet.initialize("0")

    with pytest.raises(ValueError, match="source_id"):
        wallet.credit("5", label="claimed payment")


def test_unknown_provider_cost_is_not_reported_as_known_zero(tmp_path) -> None:
    wallet = WalletLedger(tmp_path)
    wallet.plan_step("unknown-llm", label="LLM", estimated_cost_usd="0")
    wallet.settle_step("unknown-llm", actual_cost_usd="0", actual_status="unknown")

    assert wallet.status().unpriced_steps == 1
