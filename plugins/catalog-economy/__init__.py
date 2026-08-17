from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests


def get_hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home as runtime_home

        return runtime_home()
    except ImportError:
        configured = os.environ.get("HERMES_HOME", "").strip()
        return Path(configured).expanduser() if configured else Path.home() / ".hermes"


def _load_economics():
    try:
        from eoh_catalog_agent.economics import (  # type: ignore
            browser_affordability,
            InsufficientFunds,
            WalletLedger,
            money,
            money_text,
            quote_browser_use,
            status_dict,
        )
        return browser_affordability, InsufficientFunds, WalletLedger, money, money_text, quote_browser_use, status_dict
    except ImportError:
        plugin_root = Path(__file__).resolve().parent
        candidates = [
            plugin_root / "src",
            plugin_root.parent / "src",
            plugin_root.parent.parent / "src",
        ]
        for candidate in candidates:
            if (candidate / "eoh_catalog_agent" / "economics.py").is_file():
                sys.path.insert(0, str(candidate))
                break
        from eoh_catalog_agent.economics import (  # type: ignore
            browser_affordability,
            InsufficientFunds,
            WalletLedger,
            money,
            money_text,
            quote_browser_use,
            status_dict,
        )
        return browser_affordability, InsufficientFunds, WalletLedger, money, money_text, quote_browser_use, status_dict


browser_affordability, InsufficientFunds, WalletLedger, money, money_text, quote_browser_use, status_dict = _load_economics()
_BASE_URL = "https://api.browser-use.com/api/v3"


def _minimum_reserve_usd() -> Decimal:
    try:
        return money(os.environ.get("EOH_MINIMUM_RESERVE_USD", "0"))
    except ValueError:
        return Decimal("0")


def _affordability(estimate: Decimal) -> tuple[Decimal, Decimal, bool]:
    available = Decimal(_ledger().status().available_usd)
    result = browser_affordability(
        available_usd=available,
        estimated_cost_usd=estimate,
    )
    return available, Decimal(result["minimum_reserve_usd"]), bool(result["can_afford"])


def _ledger() -> Any:
    configured = os.environ.get("EOH_ECONOMY_ROOT", "").strip()
    root = Path(configured).expanduser() if configured else get_hermes_home() / "economy"
    return WalletLedger(root)


def _sessions_path() -> Path:
    path = _ledger().root / "paid-browser-sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_sessions() -> dict[str, dict[str, Any]]:
    path = _sessions_path()
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_sessions(sessions: dict[str, dict[str, Any]]) -> None:
    path = _sessions_path()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _api_key() -> str:
    try:
        from hermes_cli.config import get_env_value

        value = get_env_value("BROWSER_USE_API_KEY") or ""
    except Exception:
        value = os.environ.get("BROWSER_USE_API_KEY", "")
    return str(value).strip()


def _headers() -> dict[str, str]:
    key = _api_key()
    if not key:
        raise ValueError(
            "BROWSER_USE_API_KEY is not configured. Add it through Hermes setup/SSS; "
            "no paid browser session was created."
        )
    return {"X-Browser-Use-API-Key": key, "Content-Type": "application/json"}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _wallet_status(_args: dict[str, Any], **_kwargs: Any) -> str:
    return _json({"ok": True, **status_dict(_ledger().status())})


def _wallet_history(args: dict[str, Any], **_kwargs: Any) -> str:
    try:
        limit = int(args.get("limit", 20))
        return _json({
            "ok": True,
            "entries": _ledger().latest(limit),
            "status": status_dict(_ledger().status()),
        })
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def _wallet_credit(args: dict[str, Any], **_kwargs: Any) -> str:
    try:
        status = _ledger().credit(
            args.get("amount_usd"),
            label=str(args.get("label") or "verified-income"),
            source_id=str(args.get("source_id") or ""),
        )
        return _json({"ok": True, **status_dict(status)})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def _step_plan(args: dict[str, Any], **_kwargs: Any) -> str:
    try:
        result = _ledger().plan_step(
            str(args.get("step_id") or ""),
            label=str(args.get("label") or ""),
            estimated_cost_usd=args.get("estimated_cost_usd"),
            reserve=bool(args.get("reserve", False)),
            metadata={"source": "hermes-tool"},
        )
        return _json({"ok": True, **result})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def _step_settle(args: dict[str, Any], **_kwargs: Any) -> str:
    try:
        result = _ledger().settle_step(
            str(args.get("step_id") or ""),
            actual_cost_usd=args.get("actual_cost_usd"),
            actual_status=str(args.get("actual_status") or "actual"),
            metadata={"source": "hermes-tool"},
        )
        return _json({"ok": True, **result})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def _paid_browser_quote(args: dict[str, Any], **_kwargs: Any) -> str:
    try:
        quote = quote_browser_use(
            minutes=int(args.get("minutes", 10)),
            proxy_mb=int(args.get("proxy_mb", 10)),
        )
        estimate = Decimal(quote.estimated_cost_usd)
        available, minimum_reserve, can_afford = _affordability(estimate)
        return _json({
            "ok": True,
            **asdict(quote),
            "available_usd": f"{available:.6f}",
            "minimum_reserve_usd": f"{minimum_reserve:.6f}",
            "can_afford": can_afford,
            "projected_remaining_usd": f"{available - estimate:.6f}",
            "provider_configured": bool(_api_key()),
            "captcha_solving": True,
            "residential_proxy": True,
        })
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def _attach_paid_session(task_id: str, remote: dict[str, Any]) -> None:
    """Bind this task's Hermes native browser tools to the paid CDP session."""
    if not task_id:
        return
    from tools import browser_tool

    with browser_tool._cleanup_lock:
        browser_tool._active_sessions[task_id] = {
            "session_name": f"eoh_paid_{str(remote['id'])[:12]}",
            "bb_session_id": None,
            "cdp_url": str(remote["cdpUrl"]),
            "features": {
                "browser_use": True,
                "captcha_solving": True,
                "residential_proxy": True,
            },
            "session_key": task_id,
            "owner_task_id": task_id,
        }
        browser_tool._last_active_session_key.pop(task_id, None)


def _detach_paid_session(task_id: str) -> None:
    if not task_id:
        return
    try:
        from tools import browser_tool

        browser_tool._stop_cdp_supervisor(task_id)
        with browser_tool._cleanup_lock:
            browser_tool._active_sessions.pop(task_id, None)
            browser_tool._session_last_activity.pop(task_id, None)
            browser_tool._last_active_session_key.pop(task_id, None)
    except Exception:
        return


def _paid_browser_start(args: dict[str, Any], *, task_id: str = "", **_kwargs: Any) -> str:
    step_id = str(args.get("step_id") or f"paid-browser-{uuid.uuid4().hex[:12]}")
    minutes = int(args.get("minutes", 10))
    proxy_mb = int(args.get("proxy_mb", 10))
    country = str(args.get("proxy_country_code") or "us").lower()
    quote = quote_browser_use(minutes=minutes, proxy_mb=proxy_mb)
    available, minimum_reserve, can_afford = _affordability(Decimal(quote.estimated_cost_usd))
    if not can_afford:
        return _json({
            "ok": False,
            "error": (
                f"Need ${quote.estimated_cost_usd} plus minimum reserve "
                f"${minimum_reserve:.6f}; available ${available:.6f}"
            ),
            "session_created": False,
        })
    try:
        reservation = _ledger().plan_step(
            step_id,
            label="Browser Use cloud session with CAPTCHA solving and residential proxy",
            estimated_cost_usd=quote.estimated_cost_usd,
            reserve=True,
            metadata={
                "provider": "browser-use",
                "minutes": minutes,
                "proxy_mb_estimate": proxy_mb,
                "proxy_country_code": country,
                "task_id": task_id,
            },
        )
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "session_created": False})

    try:
        response = requests.post(
            f"{_BASE_URL}/browsers",
            headers=_headers(),
            json={"timeout": minutes, "proxyCountryCode": country, "enableRecording": False},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"Browser Use create failed: HTTP {response.status_code}")
        remote = response.json()
        cdp_url = str(remote.get("cdpUrl") or "")
        if not cdp_url:
            raise RuntimeError("Browser Use did not return a CDP URL")
        sessions = _read_sessions()
        sessions[step_id] = {
            "provider": "browser-use",
            "remote_session_id": str(remote["id"]),
            "task_id": task_id,
            "estimated_cost_usd": quote.estimated_cost_usd,
        }
        _write_sessions(sessions)
        _attach_paid_session(task_id, remote)
        return _json({
            "ok": True,
            "step_id": step_id,
            "provider": "browser-use",
            "live_url": remote.get("liveUrl"),
            "browser_tools_attached": bool(task_id),
            "captcha_solving": True,
            "residential_proxy": True,
            "proxy_country_code": country,
            **reservation,
            "instruction": (
                "Hermes native browser tools are attached to the paid CDP for this task. Use "
                "browser_navigate -> accessibility snapshot refs -> browser_click/browser_type. "
                "Call paid_browser_stop as soon as the paid task is complete."
            ),
        })
    except Exception as exc:
        _ledger().settle_step(
            step_id,
            actual_cost_usd="0",
            actual_status="not-spent",
            metadata={"create_error": str(exc)},
        )
        return _json({"ok": False, "error": str(exc), "session_created": False})


def _paid_browser_stop(args: dict[str, Any], **_kwargs: Any) -> str:
    step_id = str(args.get("step_id") or "")
    sessions = _read_sessions()
    session = sessions.get(step_id)
    if not session:
        return _json({"ok": False, "error": f"Unknown paid browser step: {step_id}"})
    try:
        remote_id = session["remote_session_id"]
        response = requests.patch(
            f"{_BASE_URL}/browsers/{remote_id}",
            headers=_headers(),
            json={"action": "stop"},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"Browser Use stop failed: HTTP {response.status_code}")
        remote = response.json()
        actual = money(remote.get("browserCost", "0")) + money(remote.get("proxyCost", "0"))
        settlement = _ledger().settle_step(
            step_id,
            actual_cost_usd=actual,
            actual_status="provider-actual",
            metadata={
                "browser_cost_usd": money_text(remote.get("browserCost", "0")),
                "proxy_cost_usd": money_text(remote.get("proxyCost", "0")),
                "proxy_used_mb": str(remote.get("proxyUsedMb", "0")),
            },
        )
        _detach_paid_session(str(session.get("task_id") or ""))
        sessions.pop(step_id, None)
        _write_sessions(sessions)
        return _json({"ok": True, "provider": "browser-use", **settlement})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "reservation_kept": True})


_ECONOMY_TOOL_PREFIXES = ("wallet_", "economy_", "paid_browser_")


def _tool_step_id(tool_name: str, tool_call_id: str, task_id: str) -> str:
    suffix = tool_call_id or uuid.uuid4().hex
    return f"tool:{task_id or 'default'}:{tool_name}:{suffix}"


def _on_pre_tool_call(
    tool_name: str = "",
    tool_call_id: str = "",
    task_id: str = "",
    **_kwargs: Any,
) -> None:
    if tool_name.startswith(_ECONOMY_TOOL_PREFIXES):
        return None
    step_id = _tool_step_id(tool_name, tool_call_id, task_id)
    try:
        _ledger().plan_step(
            step_id,
            label=f"Hermes tool: {tool_name}",
            estimated_cost_usd="0",
            metadata={"tool_name": tool_name, "cost_status": "included-or-unmetered"},
        )
    except FileExistsError:
        pass
    return None


def _on_post_tool_call(
    tool_name: str = "",
    tool_call_id: str = "",
    task_id: str = "",
    **_kwargs: Any,
) -> None:
    if tool_name.startswith(_ECONOMY_TOOL_PREFIXES):
        return None
    step_id = _tool_step_id(tool_name, tool_call_id, task_id)
    try:
        _ledger().settle_step(
            step_id,
            actual_cost_usd="0",
            actual_status="included",
            metadata={"tool_name": tool_name},
        )
    except (FileNotFoundError, FileExistsError):
        pass
    return None


def _api_step_id(session_id: str, api_request_id: str, api_call_count: Any) -> str:
    suffix = api_request_id or str(api_call_count or uuid.uuid4().hex)
    return f"llm:{session_id or 'default'}:{suffix}"


def _estimate_llm_cost(kwargs: dict[str, Any], *, actual: bool) -> tuple[str, str, dict[str, Any]]:
    try:
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost, normalize_usage

        provider = str(kwargs.get("provider") or "")
        model = str(kwargs.get("response_model") or kwargs.get("model") or "")
        base_url = str(kwargs.get("base_url") or "")
        if actual:
            usage = normalize_usage(
                kwargs.get("usage") or {},
                provider=provider,
                api_mode=str(kwargs.get("api_mode") or ""),
            )
        else:
            usage = CanonicalUsage(
                input_tokens=max(int(kwargs.get("approx_input_tokens") or 0), 0),
                output_tokens=max(int(kwargs.get("max_tokens") or 0), 0),
            )
        result = estimate_usage_cost(model, usage, provider=provider, base_url=base_url, api_key="")
        amount = result.amount_usd if result.amount_usd is not None else Decimal("0")
        metadata = {
            "provider": provider,
            "model": model,
            "pricing_status": result.status,
            "pricing_source": result.source,
        }
        return money_text(amount), result.status, metadata
    except Exception as exc:
        return "0.000000", "unknown", {"pricing_error": str(exc)}


def _on_pre_api_request(**kwargs: Any) -> None:
    step_id = _api_step_id(
        str(kwargs.get("session_id") or ""),
        str(kwargs.get("api_request_id") or ""),
        kwargs.get("api_call_count"),
    )
    estimate, status, metadata = _estimate_llm_cost(kwargs, actual=False)
    try:
        _ledger().plan_step(
            step_id,
            label="Hermes LLM call",
            estimated_cost_usd=estimate,
            metadata={**metadata, "estimate_status": status},
        )
    except FileExistsError:
        pass
    return None


def _on_post_api_request(**kwargs: Any) -> None:
    step_id = _api_step_id(
        str(kwargs.get("session_id") or ""),
        str(kwargs.get("api_request_id") or ""),
        kwargs.get("api_call_count"),
    )
    actual, status, metadata = _estimate_llm_cost(kwargs, actual=True)
    try:
        _ledger().settle_step(
            step_id,
            actual_cost_usd=actual,
            actual_status=status,
            metadata=metadata,
        )
    except (FileNotFoundError, FileExistsError):
        pass
    return None


def _cost_footer(
    tool_name: str = "",
    result: Any = None,
    tool_call_id: str = "",
    task_id: str = "",
    **_kwargs: Any,
) -> str | None:
    if tool_name.startswith(("wallet_", "economy_", "paid_browser_")):
        return None
    status = _ledger().status()
    original = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    step_id = _tool_step_id(tool_name, tool_call_id, task_id)
    return (
        original
        + f"\n\n[ECONOMY] step={step_id} expected=$0.000000 actual=$0.000000 "
        f"status=included cash=${status.cash_balance_usd} reserved=${status.reserved_usd} "
        f"remaining=${status.available_usd} unpriced_steps={status.unpriced_steps}."
    )


def _cost_final(response_text: str = "", **_kwargs: Any) -> str:
    status = _ledger().status()
    return (
        response_text
        + f"\n\n[ECONOMY] cash=${status.cash_balance_usd} reserved=${status.reserved_usd} "
        f"remaining=${status.available_usd} spent=${status.total_spent_usd} "
        f"unpriced_steps={status.unpriced_steps}."
    )


def _on_session_end(session_id: str = "", task_id: str = "", **_kwargs: Any) -> None:
    """Stop paid sessions owned by the ending Hermes task and settle actual cost."""
    sessions = _read_sessions()
    owners = {value for value in (session_id, task_id) if value}
    for step_id, session in list(sessions.items()):
        if str(session.get("task_id") or "") in owners:
            _paid_browser_stop({"step_id": step_id})
    return None


_TOOLS = [
    ("wallet_status", "Return machine-calculated cash, reservations, spend, and available USD.", {}, [], _wallet_status),
    ("economy_history", "Return recent append-only expected/actual cost entries and deterministic wallet status.", {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}, [], _wallet_history),
    ("wallet_credit", "Record verified received income. Never record hypothetical revenue; source_id is mandatory.", {"amount_usd": {"type": "string"}, "label": {"type": "string"}, "source_id": {"type": "string"}}, ["amount_usd", "label", "source_id"], _wallet_credit),
    ("economy_step_plan", "Before every external/tool step, record expected USD cost and optionally reserve it.", {"step_id": {"type": "string"}, "label": {"type": "string"}, "estimated_cost_usd": {"type": "string"}, "reserve": {"type": "boolean", "default": False}}, ["step_id", "label", "estimated_cost_usd"], _step_plan),
    ("economy_step_settle", "After every external/tool step, record actual or measured USD cost and remaining money.", {"step_id": {"type": "string"}, "actual_cost_usd": {"type": "string"}, "actual_status": {"type": "string", "enum": ["actual", "estimated", "included", "not-spent", "provider-actual", "unknown"]}}, ["step_id", "actual_cost_usd"], _step_settle),
    ("paid_browser_quote", "Calculate Browser Use session plus residential proxy cost without an LLM.", {"minutes": {"type": "integer", "minimum": 1, "maximum": 240}, "proxy_mb": {"type": "integer", "minimum": 0}}, [], _paid_browser_quote),
    ("paid_browser_start", "Reserve funds then buy a Browser Use cloud browser with CAPTCHA solving and residential proxy. Fails before purchase when money or credentials are missing.", {"step_id": {"type": "string"}, "minutes": {"type": "integer", "minimum": 1, "maximum": 240}, "proxy_mb": {"type": "integer", "minimum": 0}, "proxy_country_code": {"type": "string"}}, ["step_id"], _paid_browser_start),
    ("paid_browser_stop", "Stop the paid browser immediately and settle provider-reported browser and proxy cost.", {"step_id": {"type": "string"}}, ["step_id"], _paid_browser_stop),
]


def register(ctx: Any) -> None:
    for name, description, properties, required, handler in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="catalog_economy",
            schema={
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
            handler=handler,
        )
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("transform_tool_result", _cost_footer)
    ctx.register_hook("pre_api_request", _on_pre_api_request)
    ctx.register_hook("post_api_request", _on_post_api_request)
    ctx.register_hook("transform_llm_output", _cost_final)
    ctx.register_hook("on_session_end", _on_session_end)
