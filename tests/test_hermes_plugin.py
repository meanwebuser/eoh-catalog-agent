from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_plugin():
    path = Path(__file__).resolve().parents[1] / "plugins" / "catalog-economy" / "__init__.py"
    spec = importlib.util.spec_from_file_location("catalog_economy_plugin_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_paid_browser_start_does_not_call_provider_when_wallet_is_empty(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    module._ledger().initialize("0.05")
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider should not be called")

    monkeypatch.setattr(module.requests, "post", forbidden)
    result = json.loads(module._paid_browser_start({
        "step_id": "browser-too-expensive",
        "minutes": 10,
        "proxy_mb": 10,
        "proxy_country_code": "us",
    }))

    assert result["ok"] is False
    assert result["session_created"] is False
    assert called is False


def test_paid_browser_start_releases_reservation_when_key_is_missing(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    module._ledger().initialize("1")
    monkeypatch.setattr(module, "_api_key", lambda: "")

    result = json.loads(module._paid_browser_start({
        "step_id": "missing-key",
        "minutes": 10,
        "proxy_mb": 10,
    }))

    assert result["ok"] is False
    assert module._ledger().status().reserved_usd == "0.000000"
    assert module._ledger().status().available_usd == "1.000000"


def test_stop_uses_provider_actual_cost_and_releases_unused_reserve(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    module._ledger().initialize("1")
    module._ledger().plan_step("browser-actual", label="browser", estimated_cost_usd="0.20", reserve=True)
    module._write_sessions({"browser-actual": {"remote_session_id": "remote-1"}})
    monkeypatch.setattr(module, "_headers", lambda: {})

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"browserCost": "0.01", "proxyCost": "0.02", "proxyUsedMb": "2"}

    monkeypatch.setattr(module.requests, "patch", lambda *_args, **_kwargs: Response())
    result = json.loads(module._paid_browser_stop({"step_id": "browser-actual"}))

    assert result["ok"] is True
    assert result["actual_cost_usd"] == "0.030000"
    assert result["remaining_usd"] == "0.970000"


def test_plugin_registers_all_economy_tools_and_cost_hook() -> None:
    module = _load_plugin()
    tools = []
    hooks = []

    class Context:
        def register_tool(self, **kwargs):
            tools.append(kwargs["name"])

        def register_hook(self, name, handler):
            hooks.append((name, handler))

    module.register(Context())

    assert "paid_browser_start" in tools
    assert "economy_history" in tools
    assert "economy_step_plan" in tools
    assert [name for name, _ in hooks] == [
        "pre_tool_call",
        "post_tool_call",
        "transform_tool_result",
        "pre_api_request",
        "post_api_request",
        "transform_llm_output",
        "on_session_end",
    ]


def test_hooks_automatically_write_expected_and_actual_step_cost(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    module._ledger().initialize("1")

    module._on_pre_tool_call(tool_name="browser_snapshot", tool_call_id="call-1", task_id="task-1")
    module._on_post_tool_call(tool_name="browser_snapshot", tool_call_id="call-1", task_id="task-1")
    footer = module._cost_footer(
        tool_name="browser_snapshot",
        tool_call_id="call-1",
        task_id="task-1",
        result='{"success": true}',
    )

    history = module._ledger().entries()
    assert [entry["kind"] for entry in history] == ["credit", "plan", "settle"]
    assert "expected=$0.000000 actual=$0.000000" in footer
    assert "remaining=$1.000000" in footer


def test_paid_browser_start_attaches_native_browser_without_returning_cdp_secret(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    module._ledger().initialize("1")
    monkeypatch.setattr(module, "_headers", lambda: {})
    attached = {}

    class Response:
        ok = True
        status_code = 201

        @staticmethod
        def json():
            return {"id": "remote-1", "cdpUrl": "wss://secret.example/cdp?token=secret", "liveUrl": "https://live.example"}

    monkeypatch.setattr(module.requests, "post", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(module, "_attach_paid_session", lambda task_id, remote: attached.update(task_id=task_id, remote=remote))
    result = json.loads(module._paid_browser_start({
        "step_id": "browser-attached",
        "minutes": 10,
        "proxy_mb": 10,
    }, task_id="task-live"))

    assert result["ok"] is True
    assert result["browser_tools_attached"] is True
    assert "cdp_url" not in result
    assert attached["task_id"] == "task-live"


def test_session_end_stops_owned_paid_browser(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    module._write_sessions({
        "owned": {"task_id": "session-1", "remote_session_id": "r1"},
        "other": {"task_id": "session-2", "remote_session_id": "r2"},
    })
    stopped = []
    monkeypatch.setattr(module, "_paid_browser_stop", lambda args: stopped.append(args["step_id"]))

    module._on_session_end(session_id="session-1")

    assert stopped == ["owned"]


def test_paid_browser_preserves_configured_operating_reserve(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    monkeypatch.setenv("EOH_MINIMUM_RESERVE_USD", "0.95")
    module._ledger().initialize("1")
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider should not be called")

    monkeypatch.setattr(module.requests, "post", forbidden)
    result = json.loads(module._paid_browser_start({
        "step_id": "protect-reserve",
        "minutes": 10,
        "proxy_mb": 10,
    }))

    assert result["ok"] is False
    assert "minimum reserve" in result["error"]
    assert called is False


def test_economy_history_returns_recent_machine_ledger(tmp_path, monkeypatch) -> None:
    module = _load_plugin()
    monkeypatch.setenv("EOH_ECONOMY_ROOT", str(tmp_path))
    module._ledger().initialize("1")
    module._ledger().plan_step("search-1", label="search", estimated_cost_usd="0")

    result = json.loads(module._wallet_history({"limit": 1}))

    assert result["ok"] is True
    assert result["entries"][0]["step_id"] == "search-1"
    assert result["status"]["available_usd"] == "1.000000"
