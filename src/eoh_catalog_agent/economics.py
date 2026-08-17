from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Any, Iterable


MONEY_QUANTUM = Decimal("0.000001")
BROWSER_USE_SESSION_USD_PER_HOUR = Decimal("0.06")
BROWSER_USE_PROXY_USD_PER_GB = Decimal("10")
_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class InsufficientFunds(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def money(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid USD amount: {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("USD amount must be finite and non-negative")
    return parsed.quantize(MONEY_QUANTUM)


def money_text(value: Decimal | str | int | float) -> str:
    return f"{money(value):.6f}"


def signed_money_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("USD amount must be finite")
    return f"{value.quantize(MONEY_QUANTUM):.6f}"


@dataclass(frozen=True)
class WalletStatus:
    cash_balance_usd: str
    reserved_usd: str
    available_usd: str
    total_income_usd: str
    total_spent_usd: str
    active_reservations: int
    unpriced_steps: int
    entry_count: int


@dataclass(frozen=True)
class BrowserQuote:
    provider: str
    minutes: int
    proxy_mb: int
    browser_cost_usd: str
    proxy_cost_usd: str
    estimated_cost_usd: str
    pricing_source: str


def quote_browser_use(*, minutes: int, proxy_mb: int) -> BrowserQuote:
    if minutes < 1 or minutes > 240:
        raise ValueError("minutes must be between 1 and 240")
    if proxy_mb < 0:
        raise ValueError("proxy_mb must be non-negative")
    browser = (
        Decimal(minutes) * BROWSER_USE_SESSION_USD_PER_HOUR / Decimal(60)
    ).quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)
    proxy = (
        Decimal(proxy_mb) * BROWSER_USE_PROXY_USD_PER_GB / Decimal(1024)
    ).quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)
    total = (browser + proxy).quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)
    return BrowserQuote(
        provider="browser-use",
        minutes=minutes,
        proxy_mb=proxy_mb,
        browser_cost_usd=money_text(browser),
        proxy_cost_usd=money_text(proxy),
        estimated_cost_usd=money_text(total),
        pricing_source="browser-use-payg-2026-08",
    )


def minimum_reserve_usd() -> Decimal:
    """Read the deterministic post-purchase operating reserve."""
    try:
        return money(os.environ.get("EOH_MINIMUM_RESERVE_USD", "0"))
    except ValueError:
        return Decimal("0")


def browser_affordability(*, available_usd: Any, estimated_cost_usd: Any) -> dict[str, Any]:
    """Calculate affordability and remainder with Decimal arithmetic only."""
    available = Decimal(str(available_usd))
    estimate = money(estimated_cost_usd)
    reserve = minimum_reserve_usd()
    remaining = available - estimate
    return {
        "available_usd": signed_money_text(available),
        "minimum_reserve_usd": money_text(reserve),
        "can_afford": remaining >= reserve,
        "projected_remaining_usd": signed_money_text(remaining),
    }


class WalletLedger:
    """Append-only USD ledger with deterministic reservations and settlement."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "ledger.jsonl"
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(self.path, threading.RLock())

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read_entries())

    def _read_entries(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return []
        result: list[dict[str, Any]] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid ledger entry at line {number}") from exc
            if not isinstance(entry, dict):
                raise ValueError(f"Invalid ledger entry at line {number}")
            result.append(entry)
        return result

    def _append(self, entry: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "entry_id": uuid.uuid4().hex,
            "created_at": now_iso(),
            **entry,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return payload

    @staticmethod
    def _derive(entries: Iterable[dict[str, Any]]) -> tuple[WalletStatus, dict[str, dict[str, Any]]]:
        income = Decimal("0")
        spent = Decimal("0")
        plans: dict[str, dict[str, Any]] = {}
        settled: set[str] = set()
        unpriced_steps = 0
        count = 0
        for entry in entries:
            count += 1
            kind = entry.get("kind")
            if kind == "credit":
                income += money(entry.get("amount_usd", "0"))
            elif kind == "debit":
                spent += money(entry.get("amount_usd", "0"))
            elif kind == "plan":
                plans[str(entry["step_id"])] = entry
            elif kind == "settle":
                step_id = str(entry["step_id"])
                settled.add(step_id)
                spent += money(entry.get("actual_cost_usd", "0"))
                if entry.get("actual_status") == "unknown":
                    unpriced_steps += 1

        active = {
            step_id: entry
            for step_id, entry in plans.items()
            if step_id not in settled and bool(entry.get("reserve"))
        }
        reserved = sum(
            (money(entry.get("estimated_cost_usd", "0")) for entry in active.values()),
            Decimal("0"),
        )
        cash = income - spent
        available = cash - reserved
        status = WalletStatus(
            cash_balance_usd=signed_money_text(cash),
            reserved_usd=money_text(reserved),
            available_usd=signed_money_text(available),
            total_income_usd=money_text(income),
            total_spent_usd=money_text(spent),
            active_reservations=len(active),
            unpriced_steps=unpriced_steps,
            entry_count=count,
        )
        return status, active

    def status(self) -> WalletStatus:
        with self._lock:
            status, _ = self._derive(self._read_entries())
            return status

    def initialize(self, opening_balance_usd: Any) -> WalletStatus:
        amount = money(opening_balance_usd)
        with self._lock:
            entries = list(self._read_entries())
            if entries:
                raise FileExistsError("Wallet is already initialized")
            self._append({"kind": "credit", "amount_usd": money_text(amount), "label": "opening-balance"})
            return self.status()

    def credit(self, amount_usd: Any, *, label: str, source_id: str = "") -> WalletStatus:
        amount = money(amount_usd)
        if amount == 0:
            raise ValueError("Credit must be greater than zero")
        if not source_id.strip():
            raise ValueError("source_id is required for verified income")
        with self._lock:
            self._append({
                "kind": "credit",
                "amount_usd": money_text(amount),
                "label": label.strip() or "income",
                "source_id": source_id,
            })
            return self.status()

    def debit(self, amount_usd: Any, *, label: str, source_id: str = "") -> WalletStatus:
        amount = money(amount_usd)
        with self._lock:
            status = self.status()
            available = money(status.available_usd)
            if amount > available:
                raise InsufficientFunds(
                    f"Need ${money_text(amount)}, available ${status.available_usd}"
                )
            self._append({
                "kind": "debit",
                "amount_usd": money_text(amount),
                "label": label.strip() or "expense",
                "source_id": source_id,
            })
            return self.status()

    def plan_step(
        self,
        step_id: str,
        *,
        label: str,
        estimated_cost_usd: Any,
        reserve: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        step_id = step_id.strip()
        if not step_id:
            raise ValueError("step_id is required")
        estimate = money(estimated_cost_usd)
        with self._lock:
            entries = list(self._read_entries())
            if any(str(item.get("step_id")) == step_id for item in entries):
                raise FileExistsError(f"Step already exists: {step_id}")
            before, _ = self._derive(entries)
            available = money(before.available_usd)
            if reserve and estimate > available:
                raise InsufficientFunds(
                    f"Need ${money_text(estimate)}, available ${before.available_usd}"
                )
            projected = available - estimate
            self._append({
                "kind": "plan",
                "step_id": step_id,
                "label": label.strip() or step_id,
                "estimated_cost_usd": money_text(estimate),
                "reserve": bool(reserve),
                "metadata": metadata or {},
                "available_before_usd": before.available_usd,
                "projected_remaining_usd": signed_money_text(projected),
            })
            after = self.status()
            return {
                "step_id": step_id,
                "estimated_cost_usd": money_text(estimate),
                "reserved": bool(reserve),
                "available_before_usd": before.available_usd,
                "projected_remaining_usd": signed_money_text(projected),
                "available_after_reservation_usd": after.available_usd,
            }

    def settle_step(
        self,
        step_id: str,
        *,
        actual_cost_usd: Any,
        actual_status: str = "actual",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actual = money(actual_cost_usd)
        with self._lock:
            entries = list(self._read_entries())
            plans = [item for item in entries if item.get("kind") == "plan" and str(item.get("step_id")) == step_id]
            if not plans:
                raise FileNotFoundError(f"Planned step not found: {step_id}")
            if any(item.get("kind") == "settle" and str(item.get("step_id")) == step_id for item in entries):
                raise FileExistsError(f"Step already settled: {step_id}")
            estimate = money(plans[-1].get("estimated_cost_usd", "0"))
            self._append({
                "kind": "settle",
                "step_id": step_id,
                "estimated_cost_usd": money_text(estimate),
                "actual_cost_usd": money_text(actual),
                "variance_usd": str((actual - estimate).quantize(MONEY_QUANTUM)),
                "actual_status": actual_status,
                "metadata": metadata or {},
            })
            status = self.status()
            return {
                "step_id": step_id,
                "estimated_cost_usd": money_text(estimate),
                "actual_cost_usd": money_text(actual),
                "variance_usd": str((actual - estimate).quantize(MONEY_QUANTUM)),
                "actual_status": actual_status,
                "remaining_usd": status.available_usd,
                "cash_balance_usd": status.cash_balance_usd,
            }

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        return self.entries()[-limit:]


def status_dict(status: WalletStatus) -> dict[str, Any]:
    return asdict(status)


def quote_dict(quote: BrowserQuote) -> dict[str, Any]:
    return asdict(quote)
