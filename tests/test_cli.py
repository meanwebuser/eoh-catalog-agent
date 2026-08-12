from __future__ import annotations

import json
from pathlib import Path

from eoh_catalog_agent.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "catalog-20.csv"


def test_cli_prints_machine_readable_receipt(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "prepare",
            str(FIXTURE),
            "--out",
            str(tmp_path),
            "--store",
            "both",
            "--limit",
            "20",
            "--job-id",
            "arena-canary-20",
            "--revenue-usd",
            "20",
            "--expense-usd",
            "0.05",
        ]
    )

    assert exit_code == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ready_products"] == 20
    assert receipt["publish_mode"] == "draft"
    assert receipt["job_id"] == "arena-canary-20"
    assert receipt["economics"]["net_profit_usd"] == "19.95"


def test_cli_does_not_report_a_partially_blocked_batch_as_complete(tmp_path: Path, capsys) -> None:
    source = tmp_path / "partial.csv"
    source.write_text("name,sku,price\nReady,A-1,10\nBlocked,,12\n", encoding="utf-8")

    exit_code = main(["prepare", str(source), "--out", str(tmp_path / "out")])
    receipt = json.loads(capsys.readouterr().out)

    assert exit_code == 4
    assert receipt["ready_products"] == 1
    assert receipt["blocked_products"] == 1
