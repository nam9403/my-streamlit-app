from __future__ import annotations

import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable

from core import forecast_repository


def get_forecast_portfolio_dashboard(*, conn_factory: Callable[[], Any], parse_ts: Callable[[str], datetime | None], user_id: str, lookback_days: int = 720) -> dict[str, Any]:
    uid = str(user_id or "default_user")
    since = (datetime.now(timezone.utc) - timedelta(days=max(60, int(lookback_days)))).isoformat()
    rows = forecast_repository.fetch_resolved_rows_for_dashboard(
        conn_factory=conn_factory,
        user_id=uid,
        since_iso=since,
        limit=5000,
    )
    items = [dict(r) for r in rows]
    if not items:
        return {"weekly": {}, "monthly": {}, "overall": {"samples": 0}}

    def _agg(window_days: int) -> dict[str, Any]:
        since_dt = datetime.now(timezone.utc) - timedelta(days=window_days)
        group = [x for x in items if (parse_ts(str(x.get("created_at") or "")) or datetime.min.replace(tzinfo=timezone.utc)) >= since_dt]
        if not group:
            return {"samples": 0, "hit_rate_pct": None, "mape_pct": None, "alpha_pct": None}
        n = len(group)
        hit = sum(int(x.get("direction_hit") or 0) for x in group) / n * 100.0
        mape = sum(float(x.get("abs_error_pct") or 0.0) for x in group) / n
        exp_avg = sum(float(x.get("expected_return_pct") or 0.0) for x in group) / n
        real_avg = sum(float(x.get("realized_return_pct") or 0.0) for x in group) / n
        return {"samples": int(n), "hit_rate_pct": round(hit, 2), "mape_pct": round(mape, 2), "alpha_pct": round(real_avg - exp_avg, 2)}

    return {"weekly": _agg(7), "monthly": _agg(30), "overall": _agg(3650)}


def get_forecast_regime_dashboard(*, conn_factory: Callable[[], Any], user_id: str, lookback_days: int = 720) -> dict[str, Any]:
    uid = str(user_id or "default_user")
    since = (datetime.now(timezone.utc) - timedelta(days=max(60, int(lookback_days)))).isoformat()
    rows = forecast_repository.fetch_resolved_rows_for_dashboard(
        conn_factory=conn_factory,
        user_id=uid,
        since_iso=since,
        limit=5000,
    )
    items = [dict(r) for r in rows]
    if not items:
        return {"bull": {"samples": 0}, "sideway": {"samples": 0}, "bear": {"samples": 0}}

    buckets: dict[str, list[dict[str, Any]]] = {"bull": [], "sideway": [], "bear": []}
    for x in items:
        rr = float(x.get("realized_return_pct") or 0.0)
        if rr >= 5.0:
            buckets["bull"].append(x)
        elif rr <= -5.0:
            buckets["bear"].append(x)
        else:
            buckets["sideway"].append(x)

    def _agg(group: list[dict[str, Any]]) -> dict[str, Any]:
        if not group:
            return {"samples": 0, "hit_rate_pct": None, "mape_pct": None, "alpha_pct": None}
        n = len(group)
        hit = sum(int(x.get("direction_hit") or 0) for x in group) / n * 100.0
        mape = sum(float(x.get("abs_error_pct") or 0.0) for x in group) / n
        exp_avg = sum(float(x.get("expected_return_pct") or 0.0) for x in group) / n
        real_avg = sum(float(x.get("realized_return_pct") or 0.0) for x in group) / n
        return {"samples": int(n), "hit_rate_pct": round(hit, 2), "mape_pct": round(mape, 2), "alpha_pct": round(real_avg - exp_avg, 2)}

    return {"bull": _agg(buckets["bull"]), "sideway": _agg(buckets["sideway"]), "bear": _agg(buckets["bear"])}


def get_forecast_backtesting_report(*, conn_factory: Callable[[], Any], user_id: str, lookback_days: int = 365) -> dict[str, Any]:
    """
    Báo cáo backtesting theo hướng commercial:
    - Trong 1 năm qua, các forecast tăng đã diễn biến thế nào?
    - Win/Loss minh bạch + breakdown theo horizon.
    """
    uid = str(user_id or "default_user")
    since = (datetime.now(timezone.utc) - timedelta(days=max(30, int(lookback_days)))).isoformat()
    rows = forecast_repository.fetch_resolved_rows_for_commercial_report(
        conn_factory=conn_factory,
        user_id=uid,
        since_iso=since,
        limit=6000,
    )
    items = [dict(r) for r in rows]
    if not items:
        return {
            "samples": 0,
            "predicted_up_samples": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate_pct": None,
            "avg_realized_return_predicted_up_pct": None,
            "avg_abs_error_pct": None,
            "by_horizon": [],
            "summary_vi": "Chưa có dữ liệu forecast resolved để kiểm chứng.",
        }

    predicted_up = [x for x in items if float(x.get("expected_return_pct") or 0.0) > 0]
    wins = [x for x in predicted_up if float(x.get("realized_return_pct") or 0.0) > 0]
    losses = [x for x in predicted_up if float(x.get("realized_return_pct") or 0.0) <= 0]
    n_up = len(predicted_up)
    win_rate = (len(wins) / n_up * 100.0) if n_up > 0 else None
    avg_realized = (
        sum(float(x.get("realized_return_pct") or 0.0) for x in predicted_up) / n_up
        if n_up > 0
        else None
    )
    avg_abs_error = (
        sum(float(x.get("abs_error_pct") or 0.0) for x in predicted_up) / n_up
        if n_up > 0
        else None
    )

    horizons = sorted({int(x.get("horizon_days") or 0) for x in predicted_up if int(x.get("horizon_days") or 0) > 0})
    by_horizon: list[dict[str, Any]] = []
    for h in horizons:
        grp = [x for x in predicted_up if int(x.get("horizon_days") or 0) == h]
        if not grp:
            continue
        gn = len(grp)
        gw = sum(1 for x in grp if float(x.get("realized_return_pct") or 0.0) > 0)
        gr = sum(float(x.get("realized_return_pct") or 0.0) for x in grp) / gn
        ge = sum(float(x.get("abs_error_pct") or 0.0) for x in grp) / gn
        by_horizon.append(
            {
                "horizon_days": h,
                "samples": gn,
                "win_rate_pct": round(gw / gn * 100.0, 2),
                "avg_realized_return_pct": round(gr, 2),
                "avg_abs_error_pct": round(ge, 2),
            }
        )

    if isinstance(win_rate, (float, int)):
        summary = (
            f"Trong {lookback_days} ngày, hệ thống có {n_up} dự báo tăng; "
            f"win rate đạt {float(win_rate):.2f}% "
            f"({len(wins)} thắng / {len(losses)} thua)."
        )
    else:
        summary = "Trong kỳ hiện tại chưa có đủ mẫu dự báo tăng để kết luận."
    return {
        "samples": len(items),
        "predicted_up_samples": n_up,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": None if win_rate is None else round(float(win_rate), 2),
        "avg_realized_return_predicted_up_pct": None if avg_realized is None else round(float(avg_realized), 2),
        "avg_abs_error_pct": None if avg_abs_error is None else round(float(avg_abs_error), 2),
        "by_horizon": by_horizon,
        "summary_vi": summary,
    }


def export_forecast_health_report(
    *,
    root: Path,
    utcnow_iso: Callable[[], str],
    user_id: str,
    get_forecast_portfolio_dashboard_func: Callable[[str], dict[str, Any]],
    get_forecast_regime_dashboard_func: Callable[[str], dict[str, Any]],
    get_forecast_leaderboard_func: Callable[[str, int], list[dict[str, Any]]],
) -> str:
    uid = str(user_id or "default_user")
    report_dir = root / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "user_id": uid,
        "generated_at_utc": utcnow_iso(),
        "portfolio_dashboard": get_forecast_portfolio_dashboard_func(uid),
        "regime_dashboard": get_forecast_regime_dashboard_func(uid),
        "leaderboard_top10": get_forecast_leaderboard_func(uid, 10),
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"forecast_health_{uid}_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return str(out)


def export_model_accountability_report(
    *,
    root: Path,
    utcnow_iso: Callable[[], str],
    user_id: str,
    get_forecast_portfolio_dashboard_func: Callable[[str], dict[str, Any]],
    get_forecast_regime_dashboard_func: Callable[[str], dict[str, Any]],
    get_forecast_leaderboard_func: Callable[[str, int], list[dict[str, Any]]],
    get_kpi_dashboard_func: Callable[[str, int], dict[str, Any]],
    proof_of_value_report_func: Callable[[str], dict[str, Any]],
) -> str:
    uid = str(user_id or "default_user")
    report_dir = root / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "user_id": uid,
        "generated_at_utc": utcnow_iso(),
        "portfolio_dashboard": get_forecast_portfolio_dashboard_func(uid),
        "regime_dashboard": get_forecast_regime_dashboard_func(uid),
        "leaderboard_top20": get_forecast_leaderboard_func(uid, 20),
        "kpi_30d": get_kpi_dashboard_func(uid, 30),
        "proof_of_value": proof_of_value_report_func(uid),
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"model_accountability_{uid}_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return str(out)


def export_monthly_accountability_markdown(
    *,
    root: Path,
    utcnow_iso: Callable[[], str],
    user_id: str,
    get_forecast_portfolio_dashboard_func: Callable[[str, int], dict[str, Any]],
    get_forecast_regime_dashboard_func: Callable[[str, int], dict[str, Any]],
    get_kpi_dashboard_func: Callable[[str, int], dict[str, Any]],
    proof_of_value_report_func: Callable[[str], dict[str, Any]],
    get_forecast_leaderboard_func: Callable[[str, int], list[dict[str, Any]]],
) -> str:
    uid = str(user_id or "default_user")
    report_dir = root / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"monthly_accountability_{uid}_{ts}.md"
    pf = get_forecast_portfolio_dashboard_func(uid, 720)
    rg = get_forecast_regime_dashboard_func(uid, 720)
    kpi = get_kpi_dashboard_func(uid, 30)
    pov = proof_of_value_report_func(uid)
    top = get_forecast_leaderboard_func(uid, 10)

    def _line(metric: dict[str, Any]) -> str:
        if not metric:
            return "samples=0 | hit=N/A | mape=N/A | alpha=N/A"
        hit = metric.get("hit_rate_pct")
        mape = metric.get("mape_pct")
        alpha = metric.get("alpha_pct")
        return (f"samples={int(metric.get('samples') or 0)} | " + (f"hit={float(hit):.2f}% " if isinstance(hit, (float, int)) else "hit=N/A ")) + (f"| mape={float(mape):.2f}% " if isinstance(mape, (float, int)) else "| mape=N/A ") + (f"| alpha={float(alpha):+.2f}% " if isinstance(alpha, (float, int)) else "| alpha=N/A ")

    lines = [
        "# Monthly Model Accountability Report",
        "",
        f"- User: `{uid}`",
        f"- Generated (UTC): `{utcnow_iso()}`",
        "",
        "## Portfolio Dashboard",
        f"- Weekly: {_line(pf.get('weekly') or {})}",
        f"- Monthly: {_line(pf.get('monthly') or {})}",
        f"- Overall: {_line(pf.get('overall') or {})}",
        "",
        "## Regime Dashboard",
        f"- Bull: {_line(rg.get('bull') or {})}",
        f"- Sideway: {_line(rg.get('sideway') or {})}",
        f"- Bear: {_line(rg.get('bear') or {})}",
        "",
        "## KPI 30D",
        f"- Events total: {int(kpi.get('events_total') or 0)}",
        f"- Alerts total: {int(kpi.get('alerts_total') or 0)}",
        f"- Holdings total: {int(kpi.get('holdings_total') or 0)}",
        "",
        "## Proof of Value Snapshot",
        f"- Value score: {float(pov.get('value_score') or 0):.2f}",
        f"- Maturity score: {float(pov.get('maturity_score') or 0):.2f}",
        "",
        "## Top 10 Leaderboard",
    ]
    if not top:
        lines.append("- No resolved forecast records yet.")
    else:
        for r in top:
            lines.append(
                f"- {str(r.get('symbol') or '')}: score={float(r.get('score') or 0):.2f}, hit={float(r.get('hit_rate_pct') or 0):.2f}%, mape={float(r.get('mape_pct') or 0):.2f}%, alpha={float(r.get('alpha_pct') or 0):+.2f}%"
            )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


def send_monthly_accountability_email(
    *,
    user_id: str,
    email_to: str,
    smtp_host: str,
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = "",
    smtp_from: str = "",
    export_monthly_accountability_markdown_func: Callable[[str], str],
    short_error: Callable[[str, Exception], str],
    logger_warning: Callable[..., None],
) -> tuple[bool, str]:
    to_addr = str(email_to or "").strip()
    if not to_addr:
        return False, "Thiếu email nhận báo cáo."
    if not (smtp_host and smtp_user and smtp_password):
        return False, "Thiếu cấu hình SMTP."
    try:
        md_path = export_monthly_accountability_markdown_func(user_id)
        body = Path(md_path).read_text(encoding="utf-8")
        m = MIMEText(body, _charset="utf-8")
        m["Subject"] = "Monthly Model Accountability Report"
        m["From"] = smtp_from or smtp_user
        m["To"] = to_addr
        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(m["From"], [to_addr], m.as_string())
        return True, md_path
    except (OSError, smtplib.SMTPException, ValueError) as e:
        err = short_error("monthly_email", e)
        logger_warning("send_monthly_accountability_email failed user_id=%s error=%s", user_id, err)
        return False, err
