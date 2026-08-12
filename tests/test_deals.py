from __future__ import annotations

from eoh_catalog_agent.cli import main
from eoh_catalog_agent.deals import Deal, DealStore, qualify, render_proposal, should_walk_away


def test_paid_structured_catalog_job_is_worth_applying_to(tmp_path) -> None:
    deal = Deal(
        id="upwork-2500",
        title="Ecommerce Product Data & Catalog Specialist",
        url="https://example.com/job",
        marketplace="upwork",
        budget="hourly",
        source_format="erp-export",
        store="shopify",
        paid_test=True,
        requirements_confirmed=True,
    )

    assessment = qualify(deal)

    assert assessment["decision"] == "apply"
    assert assessment["fit_score"] == 100


def test_low_information_unpaid_job_is_skipped() -> None:
    deal = Deal(id="bad", title="Upload products", url="https://example.com", marketplace="unknown")

    assessment = qualify(deal)

    assert assessment["decision"] == "skip"
    assert assessment["fit_score"] == 0


def test_proposal_is_draft_and_asks_for_required_inputs(tmp_path) -> None:
    store = DealStore(tmp_path)
    deal = store.create({
        "id": "paid-test",
        "title": "Catalog test",
        "url": "https://example.com",
        "marketplace": "upwork",
        "budget": "$25 test",
        "source_format": "xlsx",
        "store": "shopify",
        "paid_test": True,
        "requirements_confirmed": True,
        "fit_score": 100,
        "required_phrase": "Purple.",
    })

    proposal = render_proposal(deal)

    assert "paid test batch of 20 products" in proposal
    assert proposal.startswith("Purple.\n\n")
    assert "One correctly completed product example" in proposal
    assert "github.com/meanwebuser/eoh-catalog-agent" in proposal


def test_generic_proposal_has_no_job_specific_phrase(tmp_path) -> None:
    deal = Deal(
        id="generic",
        title="Catalog test",
        url="https://example.com",
        marketplace="direct",
        fit_score=100,
        source_format="csv",
        store="woocommerce",
        paid_test=True,
        requirements_confirmed=True,
    )

    assert render_proposal(deal).startswith("I can start")


def test_verified_business_facts_can_be_updated(tmp_path) -> None:
    store = DealStore(tmp_path)
    store.create({
        "id": "verify-me",
        "title": "Catalog test",
        "url": "https://example.com",
        "marketplace": "upwork",
    })

    deal = store.update("verify-me", {
        "budget": "$25 paid test",
        "connects_cost": 8,
        "required_phrase": "Blue.",
        "missing": [],
    })

    assert deal.budget == "$25 paid test"
    assert deal.connects_cost == 8
    assert deal.required_phrase == "Blue."
    assert deal.missing == []


def test_two_unanswered_followups_trigger_walk_away() -> None:
    walk, reason = should_walk_away(
        Deal(id="stale", title="Stale", url="https://example.com", marketplace="upwork", no_reply_count=2)
    )

    assert walk is True
    assert "two follow-ups" in reason


def test_cli_accepts_deal_root_after_action(tmp_path, capsys) -> None:
    DealStore(tmp_path).create({
        "id": "root-order",
        "title": "Catalog test",
        "url": "https://example.com",
        "marketplace": "direct",
    })

    assert main(["deal", "show", "root-order", "--root", str(tmp_path)]) == 0
    assert '"id": "root-order"' in capsys.readouterr().out
