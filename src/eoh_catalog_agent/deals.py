from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEAL_STAGES = {
    "discovered",
    "qualified",
    "drafted",
    "applied",
    "negotiating",
    "won",
    "delivering",
    "completed",
    "lost",
    "walked-away",
}


@dataclass
class Deal:
    id: str
    title: str
    url: str
    marketplace: str
    stage: str = "discovered"
    budget: str = ""
    client: str = ""
    required_phrase: str = ""
    fit_score: int = 0
    connects_cost: int = 0
    source_format: str = "unknown"
    store: str = "unknown"
    paid_test: bool = False
    requirements_confirmed: bool = False
    missing: list[str] = field(default_factory=list)
    next_action: str = "qualify"
    next_action_at: str = ""
    last_message_at: str = ""
    no_reply_count: int = 0
    walk_away_reason: str = ""
    notes: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:64] or "deal"


class DealStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, deal_id: str) -> Path:
        return self.root / f"{slugify(deal_id)}.json"

    def load(self, deal_id: str) -> Deal:
        path = self.path_for(deal_id)
        if not path.is_file():
            raise FileNotFoundError(f"Deal not found: {deal_id}")
        return Deal(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, deal: Deal) -> Deal:
        if deal.stage not in DEAL_STAGES:
            raise ValueError(f"Unknown deal stage: {deal.stage}")
        deal.updated_at = now_iso()
        if not deal.created_at:
            deal.created_at = deal.updated_at
        self.path_for(deal.id).write_text(
            json.dumps(asdict(deal), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return deal

    def create(self, values: Mapping[str, Any]) -> Deal:
        deal_id = str(values.get("id") or slugify(str(values.get("title") or "deal")))
        if self.path_for(deal_id).exists():
            raise FileExistsError(f"Deal already exists: {deal_id}")
        return self.save(Deal(id=deal_id, **{key: value for key, value in values.items() if key != "id"}))

    def update(self, deal_id: str, values: Mapping[str, Any]) -> Deal:
        deal = self.load(deal_id)
        for key, value in values.items():
            if not hasattr(deal, key):
                raise ValueError(f"Unknown deal field: {key}")
            setattr(deal, key, value)
        return self.save(deal)

    def list(self, *, active_only: bool = False) -> list[Deal]:
        deals = [Deal(**json.loads(path.read_text(encoding="utf-8"))) for path in sorted(self.root.glob("*.json"))]
        if active_only:
            deals = [deal for deal in deals if deal.stage not in {"completed", "lost", "walked-away"}]
        return deals


def qualify(deal: Deal) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0
    if deal.source_format in {"csv", "xlsx", "excel", "erp-export", "supplier-links"}:
        score += 25
    else:
        reasons.append("No structured or link-based source data confirmed")
    if deal.store in {"shopify", "woocommerce", "both"}:
        score += 20
    else:
        reasons.append("Target store is not confirmed")
    if deal.paid_test:
        score += 25
    else:
        reasons.append("No paid test offered")
    if deal.budget:
        score += 15
    else:
        reasons.append("Budget or rate is missing")
    if deal.requirements_confirmed and not deal.missing:
        score += 15
    elif deal.missing:
        reasons.extend(f"Missing: {item}" for item in deal.missing)
    else:
        reasons.append("Requirements are not confirmed")

    decision = "apply" if score >= 70 else "clarify" if score >= 40 else "skip"
    return {"fit_score": score, "decision": decision, "reasons": reasons}


def render_proposal(deal: Deal) -> str:
    if deal.fit_score < 70:
        raise ValueError("Deal must score at least 70 before drafting a proposal")
    store = "Shopify and WooCommerce" if deal.store == "both" else deal.store.title()
    source = deal.source_format.upper()
    prefix = f"{deal.required_phrase.strip()}\n\n" if deal.required_phrase.strip() else ""
    return prefix + (
        f"I can start with a paid test batch of 20 products for your {store} catalog. "
        f"I will process the supplied {source} data into a clean master catalog, store-ready draft import, "
        "and a separate issues report for missing, duplicate, or conflicting fields.\n\n"
        "For the test, please send:\n"
        "1. The raw 20–50 product export or supplier links.\n"
        "2. One correctly completed product example.\n"
        "3. Required fields, categories, and variant rules.\n"
        "4. The target store import template, if customized.\n\n"
        "I will return the first checked batch within 24 hours. Nothing needs to be published before your review.\n\n"
        "Relevant implementation and reproducible test: https://github.com/meanwebuser/eoh-catalog-agent"
    )


def should_walk_away(deal: Deal) -> tuple[bool, str]:
    if deal.no_reply_count >= 2:
        return True, "No reply after two follow-ups"
    if deal.walk_away_reason:
        return True, deal.walk_away_reason
    if deal.stage in {"lost", "walked-away"}:
        return True, deal.walk_away_reason or deal.stage
    return False, ""
