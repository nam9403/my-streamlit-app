"""
SLO / ops snapshot panel — reads existing artifacts + nightly health (P2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_json(rel: str) -> dict[str, Any] | None:
    p = _project_root() / rel
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def _autopilot_timing_from_dashboard(dash: dict[str, Any] | None) -> dict[str, Any]:
    if not dash:
        return {}
    # Common shapes: {"rows":[...]} or {"metrics":{name:{p50,p95}}} or list under keys
    for key in ("metrics", "by_name", "timings"):
        block = dash.get(key)
        if isinstance(block, dict):
            for name, stats in block.items():
                if "load_autopilot_board" in str(name) and isinstance(stats, dict):
                    return {"name": name, **stats}
    rows = dash.get("rows") or dash.get("items") or []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and "load_autopilot_board" in str(row.get("name") or row.get("op") or ""):
                return row
    return {}


def collect_slo_snapshot() -> dict[str, Any]:
    timing = _read_json("artifacts/performance/timing_dashboard.json")
    ap_timing = _autopilot_timing_from_dashboard(timing)
    health: dict[str, Any] = {}
    try:
        from core.autopilot_nightly_board import board_health_report

        health = board_health_report()
    except Exception as exc:
        health = {"ok": False, "severity": "critical", "reason": exc.__class__.__name__}
    health_file = _read_json("artifacts/operations/autopilot_nightly_board_health.json") or {}
    go_live = _read_json("artifacts/operations/go_live_gate_summary.json") or {}
    paper = _read_json("artifacts/operations/paper_trade_hitrate.json") or {}
    accountability = _read_json("artifacts/operations/paper_trade_accountability.json") or {}
    # Live fallback when artifacts empty
    if not (accountability.get("windows") or (isinstance(paper.get("hitrate"), dict) and paper["hitrate"].get("samples"))):
        try:
            from core.paper_trade_ledger import hitrate_report, hitrate_report_extended

            live_ext = hitrate_report_extended(horizons=(40, 30, 90, 365))
            accountability = {"windows": live_ext.get("windows") or {}, "open_count": live_ext.get("open_count")}
            hr30 = hitrate_report(lookback_days=40)
            paper = {"hitrate": hr30}
        except Exception:
            pass
    fail_rate_pct = None
    scanned = health.get("scanned_count") or health.get("symbols_count")
    fail_n = health.get("fail_count")
    if scanned and fail_n is not None:
        try:
            fail_rate_pct = round(float(fail_n) / max(1, float(scanned)) * 100.0, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            fail_rate_pct = None
    return {
        "autopilot_timing": ap_timing,
        "nightly_health": health or health_file,
        "go_live": go_live,
        "paper_hitrate": paper.get("hitrate") if isinstance(paper.get("hitrate"), dict) else paper,
        "paper_accountability": accountability.get("accountability")
        if isinstance(accountability.get("accountability"), dict)
        else accountability,
        "fail_rate_pct": fail_rate_pct,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }


def render_slo_ops_panel() -> None:
    with st.expander("📈 SLO / vận hành (Autopilot + nightly)", expanded=False):
        snap = collect_slo_snapshot()
        health = snap.get("nightly_health") or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Nightly OK", "YES" if health.get("ok") else "NO")
        c2.metric("Coverage %", health.get("coverage_pct") if health.get("coverage_pct") is not None else "—")
        c3.metric("Ready", health.get("ready_count") if health.get("ready_count") is not None else "—")
        age = health.get("age_hours")
        c4.metric("Board age h", round(float(age), 1) if age is not None else "—")

        c5, c6, c7, c8 = st.columns(4)
        fail_rate = snap.get("fail_rate_pct")
        c5.metric("Fail rate %", fail_rate if fail_rate is not None else "—")
        fail_n = health.get("fail_count")
        c6.metric("Fail count", int(fail_n) if fail_n is not None else "—")
        hr30 = (snap.get("paper_accountability") or {}).get("windows") or {}
        hr40_block = hr30.get("40") if isinstance(hr30, dict) else {}
        if not hr40_block and isinstance(hr30, dict):
            hr40_block = hr30.get("30") or {}
        c7.metric("Paper 40d hit %", hr40_block.get("hit_rate_pct") if hr40_block.get("hit_rate_pct") is not None else "—")
        c8.metric("Paper 40d n", int(hr40_block.get("samples") or 0) if isinstance(hr40_block, dict) else "—")
        try:
            weekly = _read_json("artifacts/operations/paper_weekly_latest.json") or {}
            ks = weekly.get("kill_switch") or {}
            if ks:
                st.caption(
                    f"Paper kill-switch: halt={ks.get('halt_new_opens')} · "
                    f"consec_loss={ks.get('consecutive_losses')} · "
                    f"reasons={', '.join(ks.get('reasons') or []) or '—'}"
                )
        except Exception:
            pass

        ap = snap.get("autopilot_timing") or {}
        if ap:
            p95 = ap.get("p95_ms") or ap.get("p95") or ap.get("p95_sec")
            p50 = ap.get("p50_ms") or ap.get("p50") or ap.get("p50_sec")
            try:
                p95_val = float(p95) if p95 is not None else None
            except (TypeError, ValueError):
                p95_val = None
            slo_ok = p95_val is not None and p95_val <= 3000
            st.caption(
                f"Timing `load_autopilot_board`: p50={p50} | p95={p95} "
                f"({'✅ SLO ≤3s' if slo_ok else '⚠️ vượt SLO 3s' if p95_val else '—'})"
            )
        else:
            st.caption(
                "Chưa có p95 Autopilot trong timing dashboard — chạy "
                "`python scripts/build_timing_dashboard.py`."
            )

        gl = snap.get("go_live") or {}
        if gl:
            st.caption(f"Go-live gate: decision={gl.get('decision') or gl.get('Decision') or '—'}")

        hr = snap.get("paper_hitrate") or {}
        if hr.get("samples"):
            st.caption(
                f"Paper hit-rate: {hr.get('hit_rate_pct')}% (n={hr.get('samples')})."
            )
        sev = str(health.get("severity") or "")
        if sev == "critical":
            st.error("Nightly board CRITICAL — kiểm tra job quét đêm.")
        elif sev == "warn":
            st.warning("Nightly board WARN — coverage/tuổi board cần chú ý.")
        elif health.get("ok"):
            st.success("Nightly board healthy.")
