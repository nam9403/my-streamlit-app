"""
Public trust page (markdown) — paper hit-rate + anonymized samples + disclaimer (P2).

  python scripts/export_public_trust_page.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass

_DISCLAIMER = (
    "Disclaimer: Hệ thống hỗ trợ quyết định, không phải lời khuyên đầu tư cá nhân. "
    "Lịch sử gợi ý / paper-trade mang tính tham chiếu, có thể lệch thực tế. "
    "Bạn tự chịu trách nhiệm khi giao dịch."
)


def _read_json(rel: str) -> dict:
    p = ROOT / rel
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def build_trust_markdown() -> str:
    from core.paper_trade_ledger import format_hitrate_markdown, hitrate_report_extended, recent_closed_trades

    ext = hitrate_report_extended(horizons=(30, 90, 365))
    vn30 = _read_json("artifacts/operations/vn30_completeness_audit.json")
    slo = _read_json("artifacts/operations/slo_snapshot.json")
    health = slo.get("nightly_health") or _read_json("artifacts/operations/autopilot_nightly_board_health.json")

    lines = [
        "# Trust & minh bạch hiệu quả (public)",
        "",
        _DISCLAIMER,
        "",
        "## Paper-trade (ẩn danh, hệ thống)",
        "",
    ]
    lines.append(format_hitrate_markdown(ext).strip())

    # Forecast accountability (aggregate only — no tickers)
    lines.extend(["", "## Forecast accountability (ẩn danh)", ""])
    forecast_block = _forecast_accountability_section()
    lines.extend(forecast_block)

    lines.extend(["", "## VN30 data completeness (audit)", ""])
    if vn30.get("rows"):
        lines.append(
            f"- Symbols audited: **{vn30.get('audited_ok')}** / {vn30.get('symbols_total')} "
            f"| with gaps: **{vn30.get('symbols_with_missing')}** "
            f"| avg missing: **{vn30.get('avg_missing_count')}**"
        )
        freq = vn30.get("missing_frequency") or {}
        if freq:
            lines.append("- Top gaps: " + ", ".join(f"{k} ({v})" for k, v in list(freq.items())[:6]))
    else:
        lines.append("_Chưa có audit VN30 — chạy `python scripts/audit_vn30_completeness.py`._")

    lines.extend(["", "## Vận hành nightly / SLO", ""])
    if health:
        lines.append(
            f"- Board OK: **{health.get('ok')}** | coverage **{health.get('coverage_pct')}%** "
            f"| fail **{health.get('fail_count')}** | age **{health.get('age_hours')}h**"
        )
    else:
        lines.append("_Chưa có health snapshot._")
    if slo.get("fail_rate_pct") is not None:
        lines.append(f"- Nightly fail rate: **{slo.get('fail_rate_pct')}%**")
    ap_t = slo.get("autopilot_timing") or {}
    if ap_t:
        p95 = ap_t.get("p95_ms") or ap_t.get("p95") or ap_t.get("p95_sec")
        lines.append(f"- Autopilot serve p95: **{p95}** (SLO mục tiêu ≤3000ms khi đơn vị ms)")

    lines.extend(["", "## Mẫu lệnh đóng (ẩn danh)", ""])
    recent = recent_closed_trades(limit=15, anonymize=True)
    if recent:
        lines.extend(["| Label | Action | Realized % | Hit |", "|---|---|---:|---:|"])
        for row in recent:
            lines.append(
                f"| {row.get('symbol_label')} | {row.get('action') or '—'} "
                f"| {row.get('realized_pct')} | {row.get('direction_hit')} |"
            )
    else:
        lines.append("_Chưa có lệnh paper đóng._")

    lines.extend(
        [
            "",
            "---",
            "",
            "Cập nhật tự động qua nightly jobs. Không cam kết lợi nhuận.",
            "Playbook P1: Thesis / Setup / Trigger → BUY hoặc CONDITIONAL_BUY có invalidation.",
        ]
    )
    return "\n".join(lines) + "\n"


def _forecast_accountability_section() -> list[str]:
    """Best-effort aggregate forecast metrics without leaking tickers."""
    # Prefer precomputed artifact if present
    for rel in (
        "artifacts/operations/forecast_accountability_summary.json",
        "artifacts/performance/pilot_kpi_snapshot_latest.json",
    ):
        blob = _read_json(rel)
        overall = blob.get("overall") if isinstance(blob.get("overall"), dict) else None
        if not overall and isinstance(blob.get("forecast"), dict):
            overall = blob["forecast"].get("overall") if isinstance(blob["forecast"].get("overall"), dict) else blob.get("forecast")
        if isinstance(overall, dict) and (overall.get("samples") or overall.get("hit_rate_pct") is not None):
            return [
                f"- Samples: **{overall.get('samples') or 0}**",
                f"- Hit-rate: **{overall.get('hit_rate_pct') if overall.get('hit_rate_pct') is not None else '—'}%**",
                f"- Alpha: **{overall.get('alpha_pct') if overall.get('alpha_pct') is not None else '—'}%**",
                f"- Nguồn artifact: `{rel}`",
            ]
    try:
        from core.product_layer import get_forecast_portfolio_dashboard

        dash = get_forecast_portfolio_dashboard(user_id="system", lookback_days=365)
        overall = (dash or {}).get("overall") or {}
        if int(overall.get("samples") or 0) > 0:
            return [
                f"- Samples: **{overall.get('samples')}**",
                f"- Hit-rate: **{overall.get('hit_rate_pct')}%**",
                f"- Alpha: **{overall.get('alpha_pct')}%**",
                "- Nguồn: forecast portfolio dashboard (user `system`, ẩn mã).",
            ]
    except Exception:
        pass
    return [
        "_Chưa đủ forecast đã nghiệm thu. Chạy nightly seed + `refresh_matured_forecasts` rồi export lại._"
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Export public trust page markdown.")
    ap.add_argument("--out", default="artifacts/operations/public_trust_page.md")
    ap.add_argument("--json-out", default="artifacts/operations/public_trust_page.json")
    args = ap.parse_args()

    md = build_trust_markdown()
    md_out = ROOT / str(args.out)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(md, encoding="utf-8")

    payload = {"markdown_path": str(md_out), "disclaimer": _DISCLAIMER, "generated": True}
    json_out = ROOT / str(args.json_out)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
