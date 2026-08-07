"""
Overnight Autopilot board: batch-scan liquid universe, persist rows, serve Top-N by day.

Design:
  - Night job writes/merges into ``data/runtime/autopilot_nightly_board.json``.
  - Morning Autopilot reads the board and returns Top 10 from *all* scanned symbols
    (not only the live rotation window of ~40).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_BOARD_REL = Path("data") / "runtime" / "autopilot_nightly_board.json"
_AUTOPILOT_COLUMNS = (
    "Mã",
    "Tiểu ngành",
    "Khuyến nghị",
    "Readiness",
    "Thiếu DL",
    "Ghi chú Legend",
    "Thesis",
    "Setup",
    "Trigger",
    "Proprietary Score",
    "Khung thời gian",
    "Giá",
    "MOS%",
    "Expected Return %",
    "Risk % (ước tính)",
    "Trạng thái",
    "News/Macro Bias",
)

STATUS_READY = "Sẵn sàng"
STATUS_LIQUIDITY = "Không đạt lọc thanh khoản"
STATUS_NO_SNAPSHOT = "Không có snapshot"
STATUS_ANALYSIS_ERROR = "Lỗi phân tích"
STATUS_SYSTEM_ERROR = "Lỗi hệ thống"

_LIQUIDITY_STATUSES = frozenset({STATUS_LIQUIDITY})
_DATA_ERROR_STATUSES = frozenset({STATUS_NO_SNAPSHOT, STATUS_ANALYSIS_ERROR, STATUS_SYSTEM_ERROR})


def classify_row_status(status: str | None) -> str:
    """Map row Trạng thái → ready | liquidity | data_error | unknown."""
    stt = str(status or "").strip()
    if stt == STATUS_READY:
        return "ready"
    if stt in _LIQUIDITY_STATUSES:
        return "liquidity"
    if stt in _DATA_ERROR_STATUSES:
        return "data_error"
    return "unknown"


def summarize_scan_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scan batch stats (ready vs liquidity filter vs data errors)."""
    stats = {
        "total": len(rows),
        "ok": 0,
        "fail": 0,
        "liquidity_filtered": 0,
        "data_error": 0,
        "unknown": 0,
    }
    for row in rows:
        if not isinstance(row, dict):
            stats["unknown"] += 1
            continue
        cat = classify_row_status(row.get("Trạng thái"))
        if cat == "ready":
            stats["ok"] += 1
        elif cat == "liquidity":
            stats["liquidity_filtered"] += 1
            stats["fail"] += 1
        elif cat == "data_error":
            stats["data_error"] += 1
            stats["fail"] += 1
        else:
            stats["unknown"] += 1
            stats["fail"] += 1
    total = int(stats["total"]) or 0
    stats["ready_rate_pct"] = round(100.0 * stats["ok"] / total, 2) if total else 0.0
    return stats


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def nightly_board_enabled() -> bool:
    raw = str(os.environ.get("II_AUTOPILOT_NIGHTLY_BOARD", "1") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def board_path() -> Path:
    raw = str(os.environ.get("II_AUTOPILOT_NIGHTLY_BOARD_PATH") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (project_root() / p)
    return project_root() / _DEFAULT_BOARD_REL


def max_age_hours() -> float:
    try:
        return max(1.0, min(168.0, float(os.environ.get("II_AUTOPILOT_NIGHTLY_MAX_AGE_HOURS", "36") or "36")))
    except ValueError:
        return 36.0


def empty_board(*, profile: str = "growth", universe_mode: str = "liquid") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile": str(profile or "growth"),
        "universe_mode": str(universe_mode or "liquid"),
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "target_symbols": [],
        "batches": [],
        "rows": {},
        "meta": {
            "target_count": 0,
            "scanned_count": 0,
            "ready_count": 0,
            "fail_count": 0,
            "liquidity_filtered_count": 0,
            "data_error_count": 0,
            "prefilter_skipped_count": 0,
            "ready_rate_pct": 0.0,
            "coverage_pct": 0.0,
        },
        "universe_meta": {},
    }


def load_board(path: Path | None = None) -> dict[str, Any] | None:
    p = path or board_path()
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("nightly_board_load_failed path=%s error=%s", p, exc.__class__.__name__)
        return None
    if not isinstance(raw, dict):
        return None
    rows = raw.get("rows")
    if rows is None:
        raw["rows"] = {}
    elif isinstance(rows, list):
        # tolerate list form
        mapped: dict[str, Any] = {}
        for item in rows:
            if isinstance(item, dict) and item.get("Mã"):
                mapped[str(item["Mã"]).upper()] = item
        raw["rows"] = mapped
    return raw


def save_board(board: dict[str, Any], path: Path | None = None) -> Path:
    p = path or board_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    board = dict(board or {})
    board["updated_at"] = _utc_now_iso()
    board["meta"] = compute_meta(board)
    payload = json.dumps(board, ensure_ascii=False, indent=2)
    # atomic write
    fd, tmp_name = tempfile.mkstemp(prefix="autopilot_board_", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        Path(tmp_name).replace(p)
    except Exception:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return p


def compute_meta(board: dict[str, Any]) -> dict[str, Any]:
    target = [str(s).upper() for s in (board.get("target_symbols") or []) if str(s).strip()]
    rows = board.get("rows") if isinstance(board.get("rows"), dict) else {}
    scanned = list(rows.keys())
    ready = 0
    liquidity_filtered = 0
    data_error = 0
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        cat = classify_row_status(row.get("Trạng thái"))
        if cat == "ready":
            ready += 1
        elif cat == "liquidity":
            liquidity_filtered += 1
        elif cat == "data_error":
            data_error += 1
    uni_meta = board.get("universe_meta") if isinstance(board.get("universe_meta"), dict) else {}
    prefilter_skipped = int(uni_meta.get("prefilter_skipped_count") or 0)
    fail = int(liquidity_filtered + data_error)
    target_count = max(len(target), len(scanned)) if target or scanned else 0
    coverage = (100.0 * len(scanned) / target_count) if target_count else 0.0
    scanned_n = int(len(scanned))
    ready_rate = (100.0 * ready / scanned_n) if scanned_n else 0.0
    return {
        "target_count": int(target_count),
        "scanned_count": scanned_n,
        "ready_count": int(ready),
        "fail_count": int(fail),
        "liquidity_filtered_count": int(liquidity_filtered),
        "data_error_count": int(data_error),
        "prefilter_skipped_count": prefilter_skipped,
        "ready_rate_pct": round(ready_rate, 2),
        "coverage_pct": round(coverage, 2),
        "batch_count": int(len(board.get("batches") or [])),
        "universe_mode": str(board.get("universe_mode") or uni_meta.get("mode") or ""),
    }


def board_age_hours(board: dict[str, Any] | None) -> float | None:
    if not board:
        return None
    ts = str(board.get("updated_at") or board.get("created_at") or "").strip()
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return None


def board_is_fresh(board: dict[str, Any] | None, *, max_hours: float | None = None) -> bool:
    age = board_age_hours(board)
    if age is None:
        return False
    return age <= float(max_hours if max_hours is not None else max_age_hours())


def score_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Rank scan rows with the same score used by live Autopilot (+ CFO/gate penalty)."""
    if not rows:
        return pd.DataFrame(columns=list(_AUTOPILOT_COLUMNS))
    base = pd.DataFrame(rows)
    if "Khuyến nghị" not in base.columns:
        base["Khuyến nghị"] = "AVOID"
    # Prefer gate_action when present (aligned with decision_action_gate)
    if "gate_action" in base.columns:
        ga = base["gate_action"].astype(str).str.upper().replace({"NAN": "", "NONE": ""})
        use_ga = ga.isin(["BUY", "CONDITIONAL_BUY", "HOLD", "WATCH", "AVOID"])
        base.loc[use_ga, "Khuyến nghị"] = ga[use_ga]
    for col, default in (
        ("Expected Return %", 0.0),
        ("MOS%", 0.0),
        ("Risk % (ước tính)", 0.0),
    ):
        if col not in base.columns:
            base[col] = default
        else:
            base[col] = pd.to_numeric(base[col], errors="coerce").fillna(default)
    if "is_gate_restricted" not in base.columns:
        base["is_gate_restricted"] = False
    else:
        base["is_gate_restricted"] = base["is_gate_restricted"].fillna(False).astype(bool)
    if "score_penalty_mult" not in base.columns:
        base["score_penalty_mult"] = base["is_gate_restricted"].map(lambda x: 0.5 if x else 1.0)
    else:
        base["score_penalty_mult"] = pd.to_numeric(base["score_penalty_mult"], errors="coerce").fillna(1.0)
        base.loc[base["is_gate_restricted"] & (base["score_penalty_mult"] >= 1.0), "score_penalty_mult"] = 0.5
    if "cfo_status" not in base.columns:
        base["cfo_status"] = "UNKNOWN"
    if "gate_action" not in base.columns:
        base["gate_action"] = base["Khuyến nghị"]

    rank_map = {"BUY": 4, "CONDITIONAL_BUY": 3, "HOLD": 2, "WATCH": 1, "AVOID": 0}
    base["__rank"] = base["Khuyến nghị"].map(rank_map).fillna(0)
    base["__score"] = (
        base["__rank"] * 20
        + base["Expected Return %"].fillna(0) * 0.7
        + base["MOS%"].fillna(0) * 0.3
        - base["Risk % (ước tính)"].fillna(0) * 0.2
    )
    try:
        from core.proprietary_signal import proprietary_score_from_row

        base["Proprietary Score"] = base.apply(lambda r: proprietary_score_from_row(dict(r)), axis=1)
        base["__score"] = base["__score"] + base["Proprietary Score"].fillna(0) * 0.12
    except Exception as exc:
        logger.warning("nightly_board_proprietary_boost_skipped error=%s", exc.__class__.__name__)
    try:
        from core.news_macro_service import apply_news_macro_boost

        base = apply_news_macro_boost(base, force=True)
    except Exception as exc:
        logger.warning("nightly_board_news_macro_boost_skipped error=%s", exc.__class__.__name__)

    # CFO / completeness / NO-GO / AVOID → cut score in half (or configured mult)
    base["__score"] = base["__score"] * base["score_penalty_mult"].clip(lower=0.0, upper=1.0)
    # Hard demote AVOID so MOS-high traps cannot outrank healthy WATCH/HOLD
    avoid_mask = base["Khuyến nghị"].astype(str).str.upper() == "AVOID"
    base.loc[avoid_mask, "__score"] = base.loc[avoid_mask, "__score"].clip(upper=5.0)

    return base.sort_values(
        ["is_gate_restricted", "__score", "MOS%", "Expected Return %"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def board_title_for_ranked(df: pd.DataFrame) -> str:
    """UI label: recommended buys vs liquidity/watch list."""
    if df is None or df.empty or "Khuyến nghị" not in df.columns:
        return "Top 10 Thanh Khoản / Theo Dõi"
    actions = df["Khuyến nghị"].astype(str).str.upper()
    if (actions == "BUY").any():
        return "Top 10 Khuyên Mua"
    if (actions == "CONDITIONAL_BUY").any():
        return "Top 10 Mua Có Điều Kiện"
    if (actions == "HOLD").any():
        return "Top 10 Giữ / Theo Dõi"
    return "Top 10 Thanh Khoản / Theo Dõi"


def top_n_from_board(
    board: dict[str, Any],
    *,
    top_n: int = 10,
    ready_only: bool = True,
    recommended_only: bool = True,
) -> pd.DataFrame:
    """
    Ranked Top-N for Autopilot.

    ``recommended_only=True`` (default): exclude AVOID / NO-GO / gate-restricted rows
    from the primary board so MOS traps (e.g. negative CFO) cannot occupy Top picks.
    """
    rows_map = board.get("rows") if isinstance(board.get("rows"), dict) else {}
    rows = [r for r in rows_map.values() if isinstance(r, dict)]
    if ready_only:
        ready = [r for r in rows if str(r.get("Trạng thái") or "") == "Sẵn sàng"]
        rows = ready if ready else rows
    ranked = score_rows(rows)
    if ranked.empty:
        out = pd.DataFrame(columns=list(_AUTOPILOT_COLUMNS))
        out.attrs["board_title_vi"] = board_title_for_ranked(out)
        return out

    if recommended_only:
        kn = ranked["Khuyến nghị"].astype(str).str.upper() if "Khuyến nghị" in ranked.columns else pd.Series([], dtype=str)
        verdict = (
            ranked["analysis_verdict"].astype(str).str.upper()
            if "analysis_verdict" in ranked.columns
            else pd.Series([""] * len(ranked))
        )
        restricted = (
            ranked["is_gate_restricted"].fillna(False).astype(bool)
            if "is_gate_restricted" in ranked.columns
            else pd.Series([False] * len(ranked))
        )
        eligible = ranked.loc[(kn != "AVOID") & (verdict != "NO-GO") & (~restricted)].copy()
        if eligible.empty:
            # Fallback: WATCH-only liquid watchlist (still not AVOID/NO-GO if possible)
            eligible = ranked.loc[(kn != "AVOID") & (verdict != "NO-GO")].copy()
        if eligible.empty:
            eligible = ranked.copy()
        ranked = eligible

    title = board_title_for_ranked(ranked.head(max(1, int(top_n))))
    ranked = ranked.drop(columns=["__rank", "__score", "__rank_penalty"], errors="ignore").head(max(1, int(top_n)))
    keep = [c for c in _AUTOPILOT_COLUMNS if c in ranked.columns]
    # Persist gate metadata columns when present
    for extra in ("cfo_status", "gate_action", "is_gate_restricted", "analysis_verdict"):
        if extra in ranked.columns and extra not in keep:
            keep.append(extra)
    out = ranked[keep].reset_index(drop=True)
    out.attrs["board_title_vi"] = title
    return out


def merge_batch_into_board(
    board: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    batch_id: str,
    symbols: list[str],
    seconds: float,
    ok: int,
    fail: int,
) -> dict[str, Any]:
    out = dict(board or empty_board())
    rows_map = dict(out.get("rows") if isinstance(out.get("rows"), dict) else {})
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("Mã") or "").strip().upper()
        if not sym:
            continue
        enriched = dict(row)
        enriched["Mã"] = sym
        enriched["scanned_at"] = _utc_now_iso()
        enriched["batch_id"] = batch_id
        rows_map[sym] = enriched
    out["rows"] = rows_map
    batches = list(out.get("batches") or [])
    batch_rec: dict[str, Any] = {
        "batch_id": batch_id,
        "symbols": [str(s).upper() for s in symbols],
        "seconds": round(float(seconds), 3),
        "ok": int(ok),
        "fail": int(fail),
        "finished_at": _utc_now_iso(),
    }
    if isinstance(rows, list):
        scan_stats = summarize_scan_rows(rows)
        batch_rec["liquidity_filtered"] = int(scan_stats.get("liquidity_filtered") or 0)
        batch_rec["data_error"] = int(scan_stats.get("data_error") or 0)
        batch_rec["ready_rate_pct"] = scan_stats.get("ready_rate_pct")
    batches.append(batch_rec)
    out["batches"] = batches[-200:]
    out["meta"] = compute_meta(out)
    out["updated_at"] = _utc_now_iso()
    return out


def init_board_for_universe(
    *,
    symbols: list[str],
    profile: str = "growth",
    universe_mode: str = "liquid",
    reset: bool = False,
    path: Path | None = None,
    universe_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = [str(s).strip().upper() for s in symbols if str(s).strip()]
    existing = None if reset else load_board(path)
    if existing and not reset:
        board = existing
        prev_targets = [str(s).strip().upper() for s in (board.get("target_symbols") or []) if str(s).strip()]
        board["target_symbols"] = list(dict.fromkeys(prev_targets + target))
        board["profile"] = str(profile or board.get("profile") or "growth")
        board["universe_mode"] = str(universe_mode or board.get("universe_mode") or "liquid")
        if universe_meta:
            prev_uni = board.get("universe_meta") if isinstance(board.get("universe_meta"), dict) else {}
            board["universe_meta"] = {
                **prev_uni,
                **dict(universe_meta),
                "prefilter_skipped_count": int(prev_uni.get("prefilter_skipped_count") or 0)
                + int(universe_meta.get("prefilter_skipped_count") or 0),
            }
    else:
        board = empty_board(profile=profile, universe_mode=universe_mode)
        board["target_symbols"] = target
        if universe_meta:
            board["universe_meta"] = dict(universe_meta)
    board["meta"] = compute_meta(board)
    save_board(board, path)
    return board


def scan_symbol_row(
    sym: str,
    *,
    profile: str = "growth",
    min_avg_volume_20: float = 200_000.0,
) -> dict[str, Any]:
    """One-symbol scan row without Streamlit cache (safe for night CLI / workers)."""
    from core.analysis_runtime_service import _snapshot_impl, _strategic_report_impl
    from core.scanner_service import _load_scan_ohlcv

    s = str(sym or "").strip().upper()
    if not s:
        return {"Mã": "", "Giá": None, "Trạng thái": "Lỗi hệ thống", "Khuyến nghị": "AVOID"}
    try:
        snap = _snapshot_impl(s)
        if snap is None:
            return {"Mã": s, "Giá": None, "Trạng thái": "Không có snapshot", "Khuyến nghị": "AVOID"}
        try:
            rep = _strategic_report_impl(
                s,
                snap,
                profile,
                100_000_000.0,
                quick_mode=True,
                llm_live=False,
            )
            try:
                ohlcv = _load_scan_ohlcv(s)
            except Exception:
                ohlcv = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        except Exception:
            return {
                "Mã": s,
                "Giá": float(snap.get("price") or 0),
                "Trạng thái": "Lỗi phân tích",
                "Khuyến nghị": "AVOID",
            }
        avg_vol20 = (
            float(ohlcv.tail(20)["volume"].mean())
            if ohlcv is not None and not ohlcv.empty and len(ohlcv) >= 20
            else (float(ohlcv["volume"].mean()) if ohlcv is not None and not ohlcv.empty else 0.0)
        )
        if avg_vol20 < float(min_avg_volume_20):
            return {
                "Mã": s,
                "Giá": float((rep.get("valuation") or {}).get("price") or snap.get("price") or 0),
                "Trạng thái": "Không đạt lọc thanh khoản",
                "Avg Vol20": int(avg_vol20),
                "Khuyến nghị": "AVOID",
            }
        val = rep.get("valuation", {}) or {}
        fin = rep.get("financials", {}) or {}
        phase = rep.get("phase", {}) or {}
        price = float(val.get("price") or 0)
        mos = float(val.get("margin_of_safety_composite_pct") or 0)
        fscore = int(val.get("piotroski_score") or 0)
        rev_raw = fin.get("revenue_growth_yoy")
        ni_raw = fin.get("profit_growth_yoy")
        try:
            rev = float(rev_raw) if rev_raw is not None else 0.0
        except (TypeError, ValueError):
            rev = 0.0
        try:
            ni = float(ni_raw) if ni_raw is not None else None
        except (TypeError, ValueError):
            ni = None
        vol_mult = float((phase.get("metrics") or {}).get("vol_multiple") or 0)
        expected_return = max(mos * 0.6 + rev * 0.2 + fscore * 1.2, 0.0)
        risk_score = max(3.0, min(35.0, 12.0 + max(0.0, (1.2 - vol_mult) * 6.0) + (9 - fscore)))
        ph = str(phase.get("phase", "neutral"))
        try:
            from core.decision_action_gate import apply_gate_fields_to_scan_row

            gate_row = apply_gate_fields_to_scan_row(
                {},
                rep,
                snapshot=snap,
                valuation=val,
                financials=fin,
            )
            recommendation = str(gate_row.get("gate_action") or gate_row.get("Khuyến nghị") or "WATCH").upper()
        except Exception:
            fa = str(rep.get("final_action") or "").strip().upper()
            if fa in ("BUY", "CONDITIONAL_BUY", "HOLD", "AVOID", "WATCH"):
                recommendation = fa
            elif expected_return >= 12 and risk_score <= 18 and ph in ("accumulation", "breakout"):
                recommendation = "BUY"
            elif expected_return >= 6 and risk_score <= 24:
                recommendation = "HOLD"
            else:
                recommendation = "WATCH" if mos >= 20 else "AVOID"
            gate_row = {
                "cfo_status": "UNKNOWN",
                "gate_action": recommendation,
                "is_gate_restricted": False,
                "score_penalty_mult": 1.0,
            }
        if ph == "breakout" and vol_mult >= 1.4:
            horizon = "Ngắn hạn (2-6 tuần)"
        elif ph in ("accumulation", "neutral") and expected_return >= 6:
            horizon = "Trung hạn (2-6 tháng)"
        else:
            horizon = "Quan sát thêm"
        row = {
            "Mã": s,
            "Giá": round(price, 2),
            "Tiểu ngành": str(val.get("industry_subtype_label_vi") or "Khác"),
            "Pha": ph,
            "Khuyến nghị": recommendation,
            "gate_action": recommendation,
            "cfo_status": str(gate_row.get("cfo_status") or "UNKNOWN"),
            "is_gate_restricted": bool(gate_row.get("is_gate_restricted")),
            "score_penalty_mult": float(gate_row.get("score_penalty_mult") or 1.0),
            "analysis_verdict": str(rep.get("analysis_verdict") or gate_row.get("analysis_verdict") or ""),
            "Khung thời gian": horizon,
            "MOS%": round(mos, 2),
            "Fair": None,
            "FairMethod": str(val.get("best_fair_label_vi") or val.get("best_fair_method") or ""),
            "Graham": None,
            "MOS_graham%": None,
            "F-Score": fscore,
            "Rev YoY%": round(rev, 2),
            "Profit YoY%": round(ni, 2) if ni is not None else None,
            "revenue_growth_yoy": rev_raw,
            "profit_growth_yoy": ni_raw,
            "Avg Vol20": int(avg_vol20),
            "Dữ liệu kỹ thuật": "Đủ" if ohlcv is not None and not ohlcv.empty else "Thiếu (fallback)",
            "Expected Return %": round(expected_return, 2),
            "Risk % (ước tính)": round(risk_score, 2),
            "Trạng thái": "Sẵn sàng",
            "missing_items": _missing_fundamentals(snap, val, fin),
            "decision_readiness": str(rep.get("decision_readiness") or gate_row.get("decision_readiness") or ""),
        }
        try:
            fair_v = val.get("best_fair_value") or val.get("composite_target_price")
            if fair_v not in (None, "") and float(fair_v) > 0:
                row["Fair"] = round(float(fair_v), 2)
        except (TypeError, ValueError):
            pass
        try:
            g_v = val.get("intrinsic_value_graham") or val.get("graham_number")
            if g_v not in (None, "") and float(g_v) > 0:
                row["Graham"] = round(float(g_v), 2)
        except (TypeError, ValueError):
            pass
        try:
            mos_g = val.get("margin_of_safety_pct")
            if mos_g not in (None, ""):
                row["MOS_graham%"] = round(float(mos_g), 2)
        except (TypeError, ValueError):
            pass
        if gate_row:
            for key in (
                "Readiness",
                "Thiếu DL",
                "Ghi chú Legend",
                "decision_alignment_note",
                "gate_restrict_reasons",
                "completeness_score",
            ):
                if gate_row.get(key) is not None:
                    row[key] = gate_row[key]
        try:
            from core.proprietary_signal import compute_blend_signal

            sig = compute_blend_signal(rep, ohlcv=ohlcv)
            row["proprietary_signal"] = sig
            row["Proprietary Score"] = sig.get("blend_score")
        except Exception:
            pass
        try:
            from core.decision_playbook import compact_playbook_fields

            row.update(compact_playbook_fields(rep))
        except Exception:
            pass
        return row
    except Exception as exc:
        logger.warning("nightly_scan_symbol_failed symbol=%s error=%s", s, exc.__class__.__name__)
        return {"Mã": s, "Giá": None, "Trạng thái": "Lỗi hệ thống", "Khuyến nghị": "AVOID"}


def scan_batch(
    symbols: list[str],
    *,
    profile: str = "growth",
    min_avg_volume_20: float = 200_000.0,
    max_workers: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    syms = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if max_workers is None:
        try:
            max_workers = max(1, min(6, int(os.environ.get("II_SCAN_MAX_WORKERS", "3") or "3")))
        except ValueError:
            max_workers = 3
    t0 = perf_counter()
    rows: list[dict[str, Any]] = []
    if not syms:
        return [], {"seconds": 0.0, "ok": 0, "fail": 0, "total": 0}
    workers = max(1, min(int(max_workers), len(syms)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_symbol_row, s, profile=profile, min_avg_volume_20=min_avg_volume_20): s for s in syms}
        for fut in as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception:
                s = futs[fut]
                rows.append({"Mã": s, "Giá": None, "Trạng thái": "Lỗi hệ thống", "Khuyến nghị": "AVOID"})
    stats = summarize_scan_rows(rows)
    stats["seconds"] = round(perf_counter() - t0, 3)
    return rows, stats


def _missing_fundamentals(snap: dict[str, Any], val: dict[str, Any], fin: dict[str, Any]) -> list[str]:
    try:
        from core.decision_completeness import assess_decision_completeness

        return list(assess_decision_completeness(snap, val, fin).get("missing_items") or [])
    except Exception:
        missing: list[str] = []
        ni = snap.get("net_income") or fin.get("net_income")
        cfo = snap.get("operating_cash_flow") or fin.get("operating_cash_flow")
        if ni in (None, ""):
            missing.append("net_income")
        if cfo is None or cfo == "":
            missing.append("cfo")
        if not (snap.get("roe") or val.get("roe_5y_avg") or fin.get("roe")):
            missing.append("roe")
        return missing


def _mos_from_fair(fair: float, price: float) -> float | None:
    if fair <= 0 or price <= 0:
        return None
    return (float(fair) - float(price)) / float(fair) * 100.0


def _recompute_expected_return(mos: float, rev: float, fscore: float) -> float:
    return max(float(mos) * 0.6 + float(rev) * 0.2 + float(fscore) * 1.2, 0.0)


def refresh_top_prices(
    df: pd.DataFrame,
    *,
    max_symbols: int = 10,
    revalue: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Morning freshness for Top-N:
    - luôn cập nhật Giá từ snapshot
    - đồng bộ MOS%/ER với định giá công bố (best fair) để khớp Decision Card
    """
    if df is None or df.empty or "Mã" not in df.columns:
        return df, {"refreshed": 0, "attempted": 0, "revalued": 0}
    out = df.copy()
    attempted = 0
    refreshed = 0
    revalued = 0
    try:
        from core.analysis_runtime_service import _snapshot_impl
    except Exception:
        return out, {"refreshed": 0, "attempted": 0, "revalued": 0, "error": "snapshot_unavailable"}

    do_revalue = bool(revalue)
    if do_revalue:
        env_flag = str(os.environ.get("II_AUTOPILOT_MORNING_REVALUE", "1") or "1").strip().lower()
        do_revalue = env_flag not in ("0", "false", "no", "off")

    for idx in out.head(max(1, int(max_symbols))).index:
        sym = str(out.at[idx, "Mã"] or "").strip().upper()
        if not sym:
            continue
        attempted += 1
        try:
            snap = _snapshot_impl(sym)
            price = float((snap or {}).get("price") or 0.0)
            if price > 0:
                out.at[idx, "Giá"] = round(price, 2)
                refreshed += 1

            mos_updated = False
            if do_revalue and isinstance(snap, dict) and price > 0:
                try:
                    from core.valuation import value_investing_summary

                    # Merge board fundamentals hints if snapshot thin.
                    merged = dict(snap)
                    if not merged.get("symbol"):
                        merged["symbol"] = sym
                    val = value_investing_summary(merged, include_extensions=False)
                    fair = val.get("best_fair_value") or val.get("composite_target_price")
                    mos = val.get("margin_of_safety_composite_pct")
                    if fair not in (None, "") and float(fair) > 0:
                        out.at[idx, "Fair"] = round(float(fair), 2)
                    if val.get("best_fair_label_vi"):
                        out.at[idx, "FairMethod"] = str(val.get("best_fair_label_vi"))
                    g_raw = val.get("intrinsic_value_graham") or val.get("graham_number")
                    if g_raw not in (None, "") and float(g_raw) > 0:
                        out.at[idx, "Graham"] = round(float(g_raw), 2)
                    if mos not in (None, ""):
                        out.at[idx, "MOS%"] = round(float(mos), 2)
                        mos_updated = True
                        revalued += 1
                        try:
                            rev = float(out.at[idx, "Rev YoY%"] or 0)
                        except (TypeError, ValueError):
                            rev = 0.0
                        try:
                            fscore = float(out.at[idx, "F-Score"] or 0)
                        except (TypeError, ValueError):
                            fscore = 0.0
                        out.at[idx, "Expected Return %"] = round(
                            _recompute_expected_return(float(mos), rev, fscore), 2
                        )
                except Exception:
                    mos_updated = False

            if not mos_updated and price > 0:
                # Fail-soft: recomputes MOS from stored Fair (board đêm / lần refresh trước).
                fair_stored = out.at[idx, "Fair"] if "Fair" in out.columns else None
                try:
                    fair_f = float(fair_stored) if fair_stored not in (None, "") else 0.0
                except (TypeError, ValueError):
                    fair_f = 0.0
                mos_f = _mos_from_fair(fair_f, price)
                if mos_f is not None:
                    out.at[idx, "MOS%"] = round(mos_f, 2)
                    try:
                        rev = float(out.at[idx, "Rev YoY%"] or 0)
                    except (TypeError, ValueError):
                        rev = 0.0
                    try:
                        fscore = float(out.at[idx, "F-Score"] or 0)
                    except (TypeError, ValueError):
                        fscore = 0.0
                    out.at[idx, "Expected Return %"] = round(
                        _recompute_expected_return(mos_f, rev, fscore), 2
                    )
        except Exception:
            continue
    return out, {
        "refreshed": refreshed,
        "attempted": attempted,
        "revalued": revalued,
        "morning_revalue": bool(do_revalue),
    }


def board_health_report(
    *,
    min_coverage_pct: float | None = None,
    max_hours: float | None = None,
) -> dict[str, Any]:
    """Operational health for nightly board (cron / guardian)."""
    board = load_board()
    min_cov = min_coverage_pct
    if min_cov is None:
        try:
            min_cov = float(os.environ.get("II_AUTOPILOT_NIGHTLY_MIN_COVERAGE_PCT", "25") or "25")
        except ValueError:
            min_cov = 25.0
    age_cap = float(max_hours if max_hours is not None else max_age_hours())
    if not board:
        return {
            "ok": False,
            "severity": "critical",
            "reason": "missing_board",
            "path": str(board_path()),
            "min_coverage_pct": min_cov,
            "max_age_hours": age_cap,
        }
    meta = compute_meta(board)
    age = board_age_hours(board)
    cov = float(meta.get("coverage_pct") or 0.0)
    reasons: list[str] = []
    if age is None:
        reasons.append("unknown_age")
    elif age > age_cap:
        reasons.append("stale")
    if cov < float(min_cov):
        reasons.append("low_coverage")
    if int(meta.get("ready_count") or 0) <= 0:
        reasons.append("no_ready_rows")
    ok = not reasons
    if not ok and ("missing_board" in reasons or "no_ready_rows" in reasons):
        severity = "critical"
    elif not ok:
        severity = "warn"
    else:
        severity = "ok"
    return {
        "ok": ok,
        "severity": severity,
        "reasons": reasons,
        "path": str(board_path()),
        "updated_at": board.get("updated_at"),
        "age_hours": age,
        "max_age_hours": age_cap,
        "min_coverage_pct": min_cov,
        **meta,
    }


def seed_top_forecast_records(
    top_df: pd.DataFrame,
    *,
    user_id: str = "autopilot_nightly",
    horizon_days: int = 90,
) -> dict[str, Any]:
    """Persist Top-N expected returns as pending forecasts for later accountability."""
    if top_df is None or top_df.empty:
        return {"seeded": 0, "skipped": 0}
    try:
        from core.product_layer import record_forecast_snapshot
    except Exception as exc:
        return {"seeded": 0, "skipped": 0, "error": exc.__class__.__name__}

    seeded = 0
    skipped = 0
    for _, row in top_df.iterrows():
        sym = str(row.get("Mã") or "").strip().upper()
        base = float(row.get("Giá") or 0.0)
        exp_ret = float(row.get("Expected Return %") or 0.0)
        if not sym or base <= 0 or exp_ret == 0.0:
            skipped += 1
            continue
        expected_price = round(base * (1.0 + exp_ret / 100.0), 2)
        try:
            record_forecast_snapshot(
                str(user_id or "autopilot_nightly"),
                sym,
                {
                    "valuation": {"price": base},
                    "probabilistic_forecast": {
                        "expected_price": expected_price,
                        "expected_return_pct": exp_ret,
                        "horizon_days": max(7, int(horizon_days)),
                    },
                },
            )
            seeded += 1
        except Exception:
            skipped += 1
    return {"seeded": seeded, "skipped": skipped, "horizon_days": int(horizon_days)}


def try_serve_top_board(
    *,
    profile: str,
    top_n: int = 10,
    min_coverage_pct: float | None = None,
    force_live: bool = False,
    refresh_prices: bool = True,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """
    Return (top_df, meta) when a fresh nightly board can serve Autopilot.
    top_df is None → caller should fall back to live rotation scan.
    """
    meta: dict[str, Any] = {"source": "nightly_board", "served": False}
    if force_live or not nightly_board_enabled():
        meta["reason"] = "disabled_or_force_live"
        return None, meta
    board = load_board()
    if not board:
        meta["reason"] = "missing_board"
        return None, meta
    if str(board.get("profile") or "growth").lower() != str(profile or "growth").lower():
        # still allow serve — profile mismatch is soft; note it
        meta["profile_mismatch"] = True
    if not board_is_fresh(board):
        meta["reason"] = "stale"
        meta["age_hours"] = board_age_hours(board)
        return None, meta
    board_meta = compute_meta(board)
    cov = float(board_meta.get("coverage_pct") or 0.0)
    min_cov = min_coverage_pct
    if min_cov is None:
        try:
            min_cov = float(os.environ.get("II_AUTOPILOT_NIGHTLY_MIN_COVERAGE_PCT", "25") or "25")
        except ValueError:
            min_cov = 25.0
    if cov < float(min_cov):
        meta["reason"] = "low_coverage"
        meta["coverage_pct"] = cov
        meta["min_coverage_pct"] = min_cov
        return None, meta
    df = top_n_from_board(board, top_n=top_n, ready_only=True)
    if df is None or df.empty:
        meta["reason"] = "empty_top"
        return None, meta
    price_meta: dict[str, Any] = {"refreshed": 0, "attempted": 0}
    if refresh_prices:
        prefer = str(os.environ.get("II_AUTOPILOT_NIGHTLY_REFRESH_PRICES", "1") or "1").strip().lower()
        if prefer not in ("0", "false", "no", "off"):
            df, price_meta = refresh_top_prices(df, max_symbols=int(top_n))
    meta.update(
        {
            "served": True,
            "updated_at": board.get("updated_at"),
            "age_hours": board_age_hours(board),
            "universe_mode": board.get("universe_mode"),
            "profile": board.get("profile"),
            **board_meta,
            "top_n": int(top_n),
            "mode": "nightly_board",
            "board_title_vi": str(getattr(df, "attrs", {}).get("board_title_vi") or board_title_for_ranked(df)),
            "pool_size": int(board_meta.get("target_count") or 0),
            "symbols_count": int(board_meta.get("scanned_count") or 0),
            "listing_total": int(board_meta.get("target_count") or 0),
            "window_start": 1,
            "window_end": int(board_meta.get("scanned_count") or 0),
            "price_refresh": price_meta,
        }
    )
    return df, meta


def nightly_universe_mode_default() -> str:
    """Default nightly scan universe (P0: dynamic liquid by avg volume)."""
    raw = str(os.environ.get("II_AUTOPILOT_NIGHTLY_UNIVERSE_MODE", "dynamic_liquid") or "dynamic_liquid").strip().lower()
    if raw in ("vn30", "vn-30", "index"):
        return "vn30"
    if raw in ("liquid", "hose", "legacy", "alphabet"):
        return "liquid"
    if raw in ("dynamic_liquid", "dynamic", "vol_rank"):
        return "dynamic_liquid"
    return "dynamic_liquid"


def _listing_symbols_disk_first() -> list[str]:
    try:
        from scrapers.vn_listing import list_tradable_vn_symbols

        return list(list_tradable_vn_symbols(use_api=False) or [])
    except Exception:
        return []


def _build_nightly_pool(universe_mode: str, full_listing: list[str]) -> list[str]:
    from core.liquid_universe import VN30_SYMBOLS, build_dynamic_liquid_pool, build_liquid_pool

    mode = str(universe_mode or nightly_universe_mode_default()).strip().lower()
    full = list(full_listing or [])
    if mode == "vn30":
        return list(VN30_SYMBOLS)
    if mode == "dynamic_liquid":
        pool = build_dynamic_liquid_pool(full, top_n=800)
        return pool if pool else build_liquid_pool(full) if full else list(VN30_SYMBOLS)
    pool = build_liquid_pool(full) if full else list(VN30_SYMBOLS)
    return pool if pool else list(VN30_SYMBOLS)


def prefilter_symbols_by_volume(
    symbols: list[str],
    min_avg_volume: float,
    *,
    always_include: list[str] | None = None,
    sessions: int = 20,
) -> tuple[list[str], list[str]]:
    """
    Drop illiquid symbols before scan (saves API/time).
    Symbols without OHLCV store volume are kept (fail-soft at scan time).
    """
    syms = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if not syms or float(min_avg_volume) <= 0:
        return syms, []
    pin = {str(s).strip().upper() for s in (always_include or []) if str(s).strip()}
    vol_map: dict[str, float] = {}
    try:
        from core.ohlcv_store import top_symbols_by_avg_volume

        ranked = top_symbols_by_avg_volume(
            limit=max(len(syms) + 100, 200),
            sessions=int(sessions),
            candidates=syms,
        )
        vol_map = {s: float(v) for s, v in ranked}
    except Exception as exc:
        logger.warning("nightly_prefilter_volume_skipped error=%s", exc.__class__.__name__)
    passed: list[str] = []
    skipped: list[str] = []
    for s in syms:
        if s in pin:
            passed.append(s)
            continue
        vol = vol_map.get(s)
        if vol is None:
            passed.append(s)
        elif vol >= float(min_avg_volume):
            passed.append(s)
        else:
            skipped.append(s)
    return passed, skipped


def resolve_nightly_target_symbols(
    *,
    limit: int | None = None,
    offset: int = 0,
    universe_mode: str | None = None,
    min_avg_volume_20: float = 200_000.0,
    prefilter_volume: bool = True,
) -> tuple[list[str], dict[str, Any]]:
    """
    Build nightly scan target list with optional volume prefilter.

    Returns (symbols_to_scan, universe_meta).
    """
    mode = str(universe_mode or nightly_universe_mode_default()).strip().lower()
    full = _listing_symbols_disk_first()
    pool = _build_nightly_pool(mode, full)
    from core.liquid_universe import VN30_SYMBOLS

    prefilter_on = bool(prefilter_volume) and float(min_avg_volume_20) > 0
    if prefilter_on:
        scan_pool, prefilter_skipped = prefilter_symbols_by_volume(
            pool,
            float(min_avg_volume_20),
            always_include=list(VN30_SYMBOLS),
        )
    else:
        scan_pool, prefilter_skipped = list(pool), []
    off = max(0, int(offset))
    lim = int(limit) if limit is not None and int(limit) > 0 else 0
    if lim > 0:
        target = scan_pool[off : off + lim]
    else:
        target = scan_pool[off:]
    meta: dict[str, Any] = {
        "mode": mode,
        "pool_size": len(pool),
        "scan_pool_size": len(scan_pool),
        "prefilter_volume": prefilter_on,
        "prefilter_skipped_count": len(prefilter_skipped),
        "prefilter_skipped_sample": prefilter_skipped[:25],
        "min_avg_volume_20": float(min_avg_volume_20),
        "offset": off,
        "limit": lim if lim > 0 else None,
        "target_count": len(target),
        "listing_total": len(full),
    }
    return target, meta


def resolve_liquid_target_symbols(*, limit: int | None = None) -> list[str]:
    """Backward-compatible wrapper — prefer ``resolve_nightly_target_symbols``."""
    syms, _meta = resolve_nightly_target_symbols(limit=limit)
    return syms


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
