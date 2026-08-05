"""
Walk-forward / OOS evaluation for decision playbook (Wave 1 — expert roadmap).

Design:
- Replay once per symbol (no look-ahead inside replay).
- Split by signal date into expanding or rolling folds with embargo gap.
- ``locked``: apply production pit_quality on each test fold (honest OOS of fixed rule).
- ``train_select``: sweep filters on train window only, apply winner to test (no peek).

Gate (default): ≥ half of test folds with enough samples beat WATCH on avg@primary_horizon
OR have positive excess@primary_horizon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from core.decision_playbook_backtest import (
    DEFAULT_HORIZONS,
    PlaybookBacktestConfig,
    compare_avoid_vs_watch,
    compare_entry_vs_watch,
    filter_trade_pool,
    summarize_playbook_trades,
    sweep_entry_filter_variants,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WalkForwardConfig:
    mode: str = "locked"  # locked | train_select
    fold_months: int = 6
    min_train_months: int = 18
    embargo_days: int = 10
    rolling: bool = False  # False = expanding train
    primary_horizon: int = 60
    min_test_samples: int = 8
    entry_style: str = "pit_quality"
    horizons: tuple[int, ...] = (20, 40, 60, 90)

    def normalize(self) -> WalkForwardConfig:
        mode = str(self.mode or "locked").strip().lower()
        if mode not in ("locked", "train_select"):
            mode = "locked"
        return WalkForwardConfig(
            mode=mode,
            fold_months=max(3, min(24, int(self.fold_months or 6))),
            min_train_months=max(6, min(60, int(self.min_train_months or 18))),
            embargo_days=max(0, min(60, int(self.embargo_days or 10))),
            rolling=bool(self.rolling),
            primary_horizon=max(5, int(self.primary_horizon or 60)),
            min_test_samples=max(3, int(self.min_test_samples or 8)),
            entry_style=str(self.entry_style or "pit_quality"),
            horizons=tuple(sorted({max(1, int(h)) for h in (self.horizons or DEFAULT_HORIZONS)})),
        )


def _parse_date(v: Any) -> pd.Timestamp | None:
    if v is None:
        return None
    try:
        ts = pd.Timestamp(v)
        if pd.isna(ts):
            return None
        return ts.normalize()
    except Exception:
        return None


def _filter_by_date(
    rows: list[dict[str, Any]],
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _parse_date(r.get("date"))
        if d is None:
            continue
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        out.append(r)
    return out


def build_walk_forward_folds(
    min_date: pd.Timestamp,
    max_date: pd.Timestamp,
    *,
    fold_months: int = 6,
    min_train_months: int = 18,
    embargo_days: int = 10,
    rolling: bool = False,
) -> list[dict[str, Any]]:
    """
    Build expanding (default) or rolling folds.

    Train ends at T; embargo (T, T+embargo]; test (T+embargo, T+embargo+fold].
    """
    if max_date <= min_date:
        return []
    folds: list[dict[str, Any]] = []
    train_end = min_date + pd.DateOffset(months=int(min_train_months))
    fold_i = 0
    while True:
        embargo_end = train_end + pd.Timedelta(days=int(embargo_days))
        test_end = embargo_end + pd.DateOffset(months=int(fold_months))
        if embargo_end >= max_date:
            break
        test_end = min(test_end, max_date)
        if rolling:
            train_start = train_end - pd.DateOffset(months=int(min_train_months))
            if train_start < min_date:
                train_start = min_date
        else:
            train_start = min_date
        if test_end <= embargo_end:
            break
        folds.append(
            {
                "fold": fold_i,
                "train_start": train_start.strftime("%Y-%m-%d"),
                "train_end": train_end.strftime("%Y-%m-%d"),
                "embargo_end": embargo_end.strftime("%Y-%m-%d"),
                "test_start": (embargo_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                "test_end": test_end.strftime("%Y-%m-%d"),
            }
        )
        fold_i += 1
        train_end = test_end
        if train_end >= max_date:
            break
        if fold_i > 40:
            break
    return folds


def _horizon_stat(summary: dict[str, Any], horizon: int, key: str) -> float | None:
    by_h = (summary or {}).get("by_horizon") or {}
    row = by_h.get(str(horizon)) or {}
    v = row.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate_fold_window(
    *,
    entry_rows: list[dict[str, Any]],
    watch_rows: list[dict[str, Any]],
    avoid_rows: list[dict[str, Any]] | None = None,
    horizons: tuple[int, ...],
    primary_horizon: int,
    min_test_samples: int,
) -> dict[str, Any]:
    entry_sum = summarize_playbook_trades(entry_rows, horizons=horizons)
    watch_sum = summarize_playbook_trades(watch_rows, horizons=horizons)
    avoid_sum = summarize_playbook_trades(avoid_rows or [], horizons=horizons)
    vs_watch = compare_entry_vs_watch(entry_sum, watch_sum, horizons=horizons)
    vs_avoid = compare_avoid_vs_watch(avoid_sum, watch_sum, horizons=horizons)
    e_avg = _horizon_stat(entry_sum, primary_horizon, "avg_return_pct")
    w_avg = _horizon_stat(watch_sum, primary_horizon, "avg_return_pct")
    e_ex = _horizon_stat(entry_sum, primary_horizon, "avg_excess_vs_bench_pct")
    n = int((entry_sum.get("by_horizon") or {}).get(str(primary_horizon), {}).get("samples") or 0)
    enough = n >= int(min_test_samples)
    beat_watch = bool(enough and e_avg is not None and w_avg is not None and e_avg > w_avg)
    pos_excess = bool(enough and e_ex is not None and e_ex > 0)
    fold_pass = bool(enough and (beat_watch or pos_excess))
    return {
        "n_entry": len(entry_rows),
        "n_watch": len(watch_rows),
        "primary_horizon": primary_horizon,
        "primary_samples": n,
        "enough_samples": enough,
        "entry_avg_primary": e_avg,
        "watch_avg_primary": w_avg,
        "entry_excess_primary": e_ex,
        "beats_watch_primary": beat_watch,
        "positive_excess_primary": pos_excess,
        "fold_pass": fold_pass,
        "entry_summary": entry_sum,
        "watch_summary": watch_sum,
        "entry_vs_watch": vs_watch,
        "avoid_vs_watch": vs_avoid,
    }


def run_walk_forward_on_pools(
    *,
    armed_pool: list[dict[str, Any]],
    watch_control: list[dict[str, Any]],
    avoid_control: list[dict[str, Any]] | None = None,
    config: WalkForwardConfig | None = None,
    locked_cfg: PlaybookBacktestConfig | None = None,
) -> dict[str, Any]:
    """Offline WF on already-replayed pools (fast)."""
    cfg = (config or WalkForwardConfig()).normalize()
    locked = (locked_cfg or PlaybookBacktestConfig(entry_style=cfg.entry_style)).normalize()
    avoid_control = avoid_control or []

    all_dates = [_parse_date(r.get("date")) for r in (armed_pool + watch_control)]
    all_dates = [d for d in all_dates if d is not None]
    if len(all_dates) < 50:
        return {
            "ok": False,
            "reason": "insufficient_dated_rows",
            "folds": [],
            "gate_pass": False,
        }
    min_d, max_d = min(all_dates), max(all_dates)
    folds_meta = build_walk_forward_folds(
        min_d,
        max_d,
        fold_months=cfg.fold_months,
        min_train_months=cfg.min_train_months,
        embargo_days=cfg.embargo_days,
        rolling=cfg.rolling,
    )
    fold_reports: list[dict[str, Any]] = []
    for meta in folds_meta:
        tr_start = pd.Timestamp(meta["train_start"])
        tr_end = pd.Timestamp(meta["train_end"])
        te_start = pd.Timestamp(meta["test_start"])
        te_end = pd.Timestamp(meta["test_end"])

        train_armed = _filter_by_date(armed_pool, start=tr_start, end=tr_end)
        test_armed = _filter_by_date(armed_pool, start=te_start, end=te_end)
        test_watch = _filter_by_date(watch_control, start=te_start, end=te_end)
        test_avoid = _filter_by_date(avoid_control, start=te_start, end=te_end)

        selected_cfg = locked
        selected_label = f"locked:{locked.entry_style}"
        if cfg.mode == "train_select":
            train_watch = _filter_by_date(watch_control, start=tr_start, end=tr_end)
            train_watch_sum = summarize_playbook_trades(train_watch, horizons=cfg.horizons)
            sweep = sweep_entry_filter_variants(train_armed, train_watch_sum, horizons=cfg.horizons)
            best = sweep.get("best") or {}
            best_cfg_raw = best.get("config") or {}
            selected_cfg = PlaybookBacktestConfig(
                entry_style=str(best_cfg_raw.get("entry_style") or "pit_quality"),
                buy_only=bool(best_cfg_raw.get("buy_only")),
                require_pit_ok=bool(best_cfg_raw.get("require_pit_ok", True)),
                require_both_growth_positive=bool(best_cfg_raw.get("require_both_growth_positive", True)),
                max_entry_rsi=float(best_cfg_raw.get("max_entry_rsi") or 72.0),
                min_mos_proxy=float(best_cfg_raw.get("min_mos_proxy") or 8.0),
                min_rev_yoy=best_cfg_raw.get("min_rev_yoy"),
                min_profit_yoy=best_cfg_raw.get("min_profit_yoy"),
                block_risk_off=bool(best_cfg_raw.get("block_risk_off")),
                min_rs_20d=best_cfg_raw.get("min_rs_20d"),
            ).normalize()
            selected_label = str(best.get("label") or selected_label)

        test_entry = filter_trade_pool(test_armed, selected_cfg)
        ev = evaluate_fold_window(
            entry_rows=test_entry,
            watch_rows=test_watch,
            avoid_rows=test_avoid,
            horizons=cfg.horizons,
            primary_horizon=cfg.primary_horizon,
            min_test_samples=cfg.min_test_samples,
        )
        fold_reports.append(
            {
                **meta,
                "selected_label": selected_label,
                "selected_config": {
                    "entry_style": selected_cfg.entry_style,
                    "buy_only": selected_cfg.buy_only,
                    "require_pit_ok": selected_cfg.require_pit_ok,
                    "require_both_growth_positive": selected_cfg.require_both_growth_positive,
                    "max_entry_rsi": selected_cfg.max_entry_rsi,
                    "min_mos_proxy": selected_cfg.min_mos_proxy,
                    "min_rs_20d": selected_cfg.min_rs_20d,
                    "block_risk_off": selected_cfg.block_risk_off,
                },
                "train_armed": len(train_armed),
                "test_armed": len(test_armed),
                **{k: v for k, v in ev.items() if k not in ("entry_summary", "watch_summary")},
                "entry_summary": ev.get("entry_summary"),
                "watch_summary": ev.get("watch_summary"),
            }
        )

    scored = [f for f in fold_reports if f.get("enough_samples")]
    passes = [f for f in scored if f.get("fold_pass")]
    gate_pass = bool(scored) and len(passes) >= max(1, (len(scored) + 1) // 2)

    # Pooled OOS (concat all test entries under each fold's selected filter)
    oos_entries: list[dict[str, Any]] = []
    oos_watch: list[dict[str, Any]] = []
    for meta, fr in zip(folds_meta, fold_reports):
        te_start = pd.Timestamp(meta["test_start"])
        te_end = pd.Timestamp(meta["test_end"])
        sc = fr.get("selected_config") or {}
        cfg_f = PlaybookBacktestConfig(
            entry_style=str(sc.get("entry_style") or "pit_quality"),
            buy_only=bool(sc.get("buy_only")),
            require_pit_ok=bool(sc.get("require_pit_ok", True)),
            require_both_growth_positive=bool(sc.get("require_both_growth_positive", True)),
            max_entry_rsi=float(sc.get("max_entry_rsi") or 72.0),
            min_mos_proxy=float(sc.get("min_mos_proxy") or 8.0),
            min_rs_20d=sc.get("min_rs_20d"),
            block_risk_off=bool(sc.get("block_risk_off")),
        ).normalize()
        oos_entries.extend(
            filter_trade_pool(_filter_by_date(armed_pool, start=te_start, end=te_end), cfg_f)
        )
        oos_watch.extend(_filter_by_date(watch_control, start=te_start, end=te_end))

    oos_sum = summarize_playbook_trades(oos_entries, horizons=cfg.horizons)
    oos_watch_sum = summarize_playbook_trades(oos_watch, horizons=cfg.horizons)
    oos_verdict = compare_entry_vs_watch(oos_sum, oos_watch_sum, horizons=cfg.horizons)

    return {
        "ok": True,
        "mode": cfg.mode,
        "config": {
            "fold_months": cfg.fold_months,
            "min_train_months": cfg.min_train_months,
            "embargo_days": cfg.embargo_days,
            "rolling": cfg.rolling,
            "primary_horizon": cfg.primary_horizon,
            "min_test_samples": cfg.min_test_samples,
            "entry_style": cfg.entry_style,
            "horizons": list(cfg.horizons),
        },
        "date_range": {"min": min_d.strftime("%Y-%m-%d"), "max": max_d.strftime("%Y-%m-%d")},
        "n_folds": len(fold_reports),
        "n_folds_scored": len(scored),
        "n_folds_pass": len(passes),
        "gate_pass": gate_pass,
        "gate_rule_vi": (
            f"PASS nếu ≥ nửa fold test (≥{cfg.min_test_samples} samples @ {cfg.primary_horizon}d) "
            f"thắng WATCH avg hoặc excess@{cfg.primary_horizon}d > 0."
        ),
        "folds": fold_reports,
        "oos_pooled_trades": len(oos_entries),
        "oos_pooled_summary": oos_sum,
        "oos_watch_summary": oos_watch_sum,
        "oos_entry_vs_watch": oos_verdict,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "disclaimer_vi": (
            "Walk-forward học tập — không cam kết lợi nhuận tương lai. "
            "Embargo tách train/test; train_select không được xem test."
        ),
    }


def format_walk_forward_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Walk-forward playbook OOS (Wave 1)",
        "",
        f"Generated: `{report.get('generated_at_utc')}`",
        "",
        str(report.get("disclaimer_vi") or ""),
        "",
        f"- Mode: **{report.get('mode')}**",
        f"- Date range: `{((report.get('date_range') or {}).get('min'))}` → "
        f"`{((report.get('date_range') or {}).get('max'))}`",
        f"- Folds: **{report.get('n_folds_pass')}/{report.get('n_folds_scored')}** pass "
        f"(total {report.get('n_folds')})",
        f"- Gate PASS: **{report.get('gate_pass')}**",
        f"- {report.get('gate_rule_vi')}",
        f"- OOS pooled entry trades: **{report.get('oos_pooled_trades')}**",
        "",
        "## OOS pooled entry",
        "",
    ]
    by_h = ((report.get("oos_pooled_summary") or {}).get("by_horizon") or {})
    lines.extend(
        [
            "| Horizon | Samples | Hit% | Avg% | Excess% |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for h in sorted(by_h.keys(), key=lambda x: int(x)):
        r = by_h[h] or {}
        lines.append(
            f"| {h}d | {r.get('samples')} | {r.get('hit_rate_pct')} | "
            f"{r.get('avg_return_pct')} | {r.get('avg_excess_vs_bench_pct')} |"
        )
    verdict = report.get("oos_entry_vs_watch") or {}
    lines.extend(
        [
            "",
            f"- OOS entry beats WATCH: **{verdict.get('entry_beats_watch')}** "
            f"({verdict.get('wins_avg')}/{verdict.get('compared')})",
            "",
            "## Per fold (test)",
            "",
            "| Fold | Test window | n | Avg60 | Ex60 | vsWATCH | PASS | Selected |",
            "|---:|---|---:|---:|---:|---|---|---|",
        ]
    )
    for f in report.get("folds") or []:
        lines.append(
            f"| {f.get('fold')} | {f.get('test_start')}→{f.get('test_end')} | "
            f"{f.get('primary_samples')} | {f.get('entry_avg_primary')} | "
            f"{f.get('entry_excess_primary')} | {f.get('beats_watch_primary')} | "
            f"{f.get('fold_pass')} | `{str(f.get('selected_label') or '')[:48]}` |"
        )
    lines.append("")
    return "\n".join(lines)
