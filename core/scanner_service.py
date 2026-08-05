from __future__ import annotations

import logging
import os
from concurrent.futures import as_completed
from datetime import date
from time import perf_counter
from typing import Any

import pandas as pd
import streamlit as st

from core.analysis_runtime_service import load_ohlcv_cached, load_snapshot_cached, load_strategic_report_cached
from core.liquid_universe import resolve_scan_universe
from core.observability import log_timing
from core.streamlit_executor import streamlit_thread_pool_executor
from scrapers.financial_data import list_universe_symbols

logger = logging.getLogger(__name__)

# Meta cửa sổ universe lần quét Autopilot gần nhất (cho UI caption).
_LAST_AUTOPILOT_UNIVERSE_META: dict[str, Any] = {}


def get_last_autopilot_universe_meta() -> dict[str, Any]:
    return dict(_LAST_AUTOPILOT_UNIVERSE_META)

_SCAN_RESULT_COLUMNS = (
    "Mã",
    "Giá",
    "Tiểu ngành",
    "Pha",
    "Khuyến nghị",
    "Khung thời gian",
    "MOS%",
    "F-Score",
    "Rev YoY%",
    "Avg Vol20",
    "Dữ liệu kỹ thuật",
    "Expected Return %",
    "Risk % (ước tính)",
    "Trạng thái",
)

_AUTOPILOT_KEEP_COLUMNS = (
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
    "News/Macro Bias",  # chỉ hiện khi II_SCANNER_NEWS_MACRO_BOOST=1
)


def _scan_int_env(name: str, default: int, lo: int, hi: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        v = default
    else:
        try:
            v = int(raw)
        except ValueError:
            v = default
    return max(lo, min(hi, v))


def _scan_ohlcv_sessions() -> int:
    """Sessions ngắn cho scan — khớp disk cache, tránh ép live vnstock khi thiếu depth dài."""
    return _scan_int_env("II_SCAN_OHLCV_SESSIONS", 80, 50, 400)


def _scan_bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _load_scan_ohlcv(sym: str):
    """OHLCV dành cho scanner/autopilot (không dùng II_OHLCV_RUNTIME_SESSIONS lớn của chart).

    Ưu tiên disk/cache khi II_SCAN_OHLCV_DISK_FIRST hoặc II_OHLCV_DISK_FIRST — tránh
    thread pool scan gọi live HTTP khi pytest/offline đã có mock hoặc cache đủ.
    """
    sessions = _scan_ohlcv_sessions()
    prefer_disk = _scan_bool_env("II_SCAN_OHLCV_DISK_FIRST") or _scan_bool_env("II_OHLCV_DISK_FIRST")
    if prefer_disk:
        try:
            cached = load_ohlcv_cached(sym)
            if cached is not None and len(cached) >= 20:
                return cached
        except Exception:
            pass
    try:
        from scrapers.portal import fetch_ohlcv_history

        return fetch_ohlcv_history(sym, sessions=sessions)
    except Exception:
        return load_ohlcv_cached(sym)


@st.cache_data(ttl=300)
def scan_potential_stocks(
    universe: tuple[str, ...],
    profile: str,
    min_avg_volume_20: float,
) -> pd.DataFrame:
    started_at = perf_counter()
    rows: list[dict] = []
    preselect_cap = _scan_int_env("II_SCAN_PRESELECT_LIMIT_CAP", 350, 50, 800)
    preselect_limit = min(max(120, int(st.session_state.get("scan_preselect_limit") or 350)), preselect_cap)

    def classify_recommendation(expected_return_pct: float, risk_pct: float, ph: str) -> str:
        if expected_return_pct >= 12 and risk_pct <= 18 and ph in ("accumulation", "breakout"):
            return "BUY"
        if expected_return_pct >= 6 and risk_pct <= 24:
            return "HOLD"
        return "AVOID"

    def estimate_horizon(ph: str, vol_mult: float, expected_return_pct: float) -> str:
        if ph == "breakout" and vol_mult >= 1.4:
            return "Ngắn hạn (2-6 tuần)"
        if ph in ("accumulation", "neutral") and expected_return_pct >= 6:
            return "Trung hạn (2-6 tháng)"
        return "Quan sát thêm"

    def _one_symbol(sym: str) -> dict | None:
        try:
            snap = load_snapshot_cached(sym)
            if snap is None:
                return {"Mã": sym, "Giá": None, "Trạng thái": "Không có snapshot", "Khuyến nghị": "AVOID"}
            try:
                rep = load_strategic_report_cached(sym, snap, profile, 100_000_000.0, quick_mode=True)
                try:
                    ohlcv = _load_scan_ohlcv(sym)
                except Exception as e:
                    logger.warning("scan ohlcv failed for %s: %s", sym, e)
                    ohlcv = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            except Exception as e:
                logger.warning("scan analysis failed for %s: %s", sym, e)
                return {
                    "Mã": sym,
                    "Giá": float(snap.get("price") or 0),
                    "Trạng thái": "Lỗi phân tích",
                    "Khuyến nghị": "AVOID",
                }
            avg_vol20 = (
                float(ohlcv.tail(20)["volume"].mean())
                if not ohlcv.empty and len(ohlcv) >= 20
                else (float(ohlcv["volume"].mean()) if not ohlcv.empty else 0.0)
            )
            if avg_vol20 < min_avg_volume_20:
                return {
                    "Mã": sym,
                    "Giá": float((rep.get("valuation") or {}).get("price") or snap.get("price") or 0),
                    "Trạng thái": "Không đạt lọc thanh khoản",
                    "Avg Vol20": int(avg_vol20),
                    "Khuyến nghị": "AVOID",
                }
            val = rep.get("valuation", {})
            fin = rep.get("financials", {})
            phase = rep.get("phase", {})
            price = float(val.get("price") or 0)
            mos = float(val.get("margin_of_safety_composite_pct") or 0)
            fscore = int(val.get("piotroski_score") or 0)
            rev = float(fin.get("revenue_growth_yoy") or 0)
            vol_mult = float((phase.get("metrics") or {}).get("vol_multiple") or 0)
            expected_return = max(mos * 0.6 + rev * 0.2 + fscore * 1.2, 0.0)
            risk_score = max(3.0, min(35.0, 12.0 + max(0.0, (1.2 - vol_mult) * 6.0) + (9 - fscore)))
            ph = str(phase.get("phase", "neutral"))
            # Align with decision_action_gate (+ CFO / completeness restriction flags)
            try:
                from core.decision_action_gate import apply_gate_fields_to_scan_row

                gate_row = apply_gate_fields_to_scan_row(
                    {},
                    rep,
                    snapshot=snap,
                    valuation=val,
                    financials=fin,
                )
                recommendation = str(gate_row.get("gate_action") or "WATCH").upper()
            except Exception:
                fa = str(rep.get("final_action") or "").strip().upper()
                if fa in ("BUY", "CONDITIONAL_BUY", "HOLD", "AVOID", "WATCH"):
                    recommendation = fa
                else:
                    recommendation = classify_recommendation(expected_return, risk_score, ph)
                gate_row = {
                    "cfo_status": "UNKNOWN",
                    "gate_action": recommendation,
                    "is_gate_restricted": False,
                    "score_penalty_mult": 1.0,
                }
            horizon = estimate_horizon(ph, vol_mult, expected_return)
            out_row = {
                "Mã": sym,
                "Giá": round(price, 2),
                "Tiểu ngành": str(val.get("industry_subtype_label_vi") or "Khác"),
                "Pha": ph,
                "Khuyến nghị": recommendation,
                "gate_action": recommendation,
                "cfo_status": str(gate_row.get("cfo_status") or "UNKNOWN"),
                "is_gate_restricted": bool(gate_row.get("is_gate_restricted")),
                "score_penalty_mult": float(gate_row.get("score_penalty_mult") or 1.0),
                "analysis_verdict": str(rep.get("analysis_verdict") or ""),
                "Readiness": gate_row.get("Readiness") or str(rep.get("decision_readiness") or ""),
                "Thiếu DL": gate_row.get("Thiếu DL") or "—",
                "Ghi chú Legend": gate_row.get("Ghi chú Legend") or "—",
                "Khung thời gian": horizon,
                "MOS%": round(mos, 2),
                "F-Score": fscore,
                "Rev YoY%": round(rev, 2),
                "Avg Vol20": int(avg_vol20),
                "Dữ liệu kỹ thuật": "Đủ" if not ohlcv.empty else "Thiếu (fallback)",
                "Expected Return %": round(expected_return, 2),
                "Risk % (ước tính)": round(risk_score, 2),
                "Trạng thái": "Sẵn sàng",
            }
            try:
                from core.decision_playbook import compact_playbook_fields

                out_row.update(compact_playbook_fields(rep))
            except Exception:
                pass
            try:
                from core.proprietary_signal import compute_blend_signal

                rep_for_sig = dict(rep) if isinstance(rep, dict) else {}
                rep_for_sig.setdefault("ticker", sym)
                sig = rep_for_sig.get("proprietary_signal") if isinstance(rep_for_sig.get("proprietary_signal"), dict) else None
                if not sig:
                    sig = compute_blend_signal(
                        rep_for_sig,
                        ohlcv=ohlcv if ohlcv is not None and not ohlcv.empty else None,
                    )
                out_row["proprietary_signal"] = sig
                out_row["Proprietary Score"] = sig.get("blend_score")
            except Exception:
                pass
            return out_row
        except Exception as e:
            logger.warning("scan symbol skipped due to error %s: %s", sym, e)
            return {"Mã": sym, "Giá": None, "Trạng thái": "Lỗi hệ thống", "Khuyến nghị": "AVOID"}

    def _prefilter_symbol(sym: str) -> tuple[str, float]:
        try:
            snap = load_snapshot_cached(sym)
            if snap is None:
                return sym, -1.0
            try:
                ohlcv = _load_scan_ohlcv(sym)
                if ohlcv is None or ohlcv.empty:
                    return sym, -1.0
                avg_vol20 = (
                    float(ohlcv.tail(20)["volume"].mean())
                    if len(ohlcv) >= 20
                    else float(ohlcv["volume"].mean())
                )
                return sym, avg_vol20
            except Exception as e:
                logger.warning("scan prefilter ohlcv failed for %s: %s", sym, e)
                return sym, -1.0
        except Exception as e:
            logger.warning("scan prefilter skipped for %s: %s", sym, e)
            return sym, -1.0

    deep_universe = list(universe)
    if len(deep_universe) > preselect_limit:
        prelim: list[tuple[str, float]] = []
        # Lower default concurrency to reduce Vietcap / vnstock read-timeouts.
        pre_cap = _scan_int_env("II_SCAN_PREFILTER_MAX_WORKERS", 4, 2, 8)
        pre_workers = min(pre_cap, max(2, len(deep_universe) // 100))
        pre_workers = max(2, pre_workers)
        with streamlit_thread_pool_executor(max_workers=pre_workers) as ex:
            pre_futs = {ex.submit(_prefilter_symbol, sym): sym for sym in deep_universe}
            for pre_fut in as_completed(pre_futs):
                try:
                    prelim.append(pre_fut.result())
                except Exception as e:
                    logger.warning("scan prefilter future failed: %s", e)
                    continue
        prelim = [x for x in prelim if x[1] >= max(0.0, float(min_avg_volume_20))]
        prelim.sort(key=lambda x: x[1], reverse=True)
        deep_universe = [sym for sym, _ in prelim[:preselect_limit]]

    batch_size = _scan_int_env("II_SCAN_SYMBOL_BATCH_SIZE", 32, 4, 200)
    # Default 4 (was 8) — Vietcap guest/community rate limits under parallel load.
    scan_worker_cap = _scan_int_env("II_SCAN_MAX_WORKERS", 4, 2, 8)
    st.session_state["scan_full_universe_count"] = int(len(universe))
    st.session_state["scan_deep_universe_count"] = int(len(deep_universe))
    for offset in range(0, len(deep_universe), batch_size):
        chunk = deep_universe[offset : offset + batch_size]
        pool = min(scan_worker_cap, max(2, len(chunk)))
        with streamlit_thread_pool_executor(max_workers=pool) as ex:
            scan_futs = {ex.submit(_one_symbol, sym): sym for sym in chunk}
            for scan_fut in as_completed(scan_futs):
                sym = scan_futs[scan_fut]
                try:
                    row = scan_fut.result()
                    if row:
                        rows.append(row)
                except Exception as e:
                    logger.warning("scan future failed for %s: %s", sym, e)
                    rows.append({"Mã": sym, "Giá": None, "Trạng thái": "Lỗi hệ thống", "Khuyến nghị": "AVOID"})
    if not rows:
        out = pd.DataFrame(columns=list(_SCAN_RESULT_COLUMNS))
    else:
        df = pd.DataFrame(rows)
        for col in _SCAN_RESULT_COLUMNS:
            if col not in df.columns:
                if col == "Khuyến nghị":
                    df[col] = "AVOID"
                elif col in ("Expected Return %", "MOS%", "Risk % (ước tính)", "Rev YoY%", "Giá"):
                    df[col] = 0.0
                elif col in ("F-Score", "Avg Vol20"):
                    df[col] = 0
                else:
                    df[col] = ""
        if "Trạng thái" not in df.columns:
            df["Trạng thái"] = "Sẵn sàng"
        df["__ready"] = (df["Trạng thái"] == "Sẵn sàng").astype(int)
        out = (
            df.sort_values(["__ready", "Expected Return %", "F-Score"], ascending=[False, False, False])
            .drop(columns=["__ready"])
            .reset_index(drop=True)
        )

    ready_count = int((out["Trạng thái"] == "Sẵn sàng").sum()) if "Trạng thái" in out.columns else 0
    log_timing(
        "scanner.scan_potential_stocks",
        (perf_counter() - started_at) * 1000.0,
        symbols=len(universe),
        deep_symbols=len(deep_universe),
        rows=len(out),
        ready=ready_count,
        profile=str(profile or ""),
        min_avg_volume_20=float(min_avg_volume_20),
        symbol_batch_size=int(batch_size),
        scan_max_workers=int(scan_worker_cap),
        preselect_limit_cap=int(preselect_cap),
    )
    return out


@st.cache_data(ttl=300)
def load_autopilot_board(
    profile: str,
    universe_limit: int = 30,
    min_avg_volume_20: float = 300_000.0,
    *,
    _rotation_day: int | None = None,
    _force_live: bool = False,
) -> pd.DataFrame:
    started_at = perf_counter()
    global _LAST_AUTOPILOT_UNIVERSE_META

    # Prefer overnight liquid board (Top 10 over ~400) when fresh.
    try:
        from core.autopilot_nightly_board import try_serve_top_board

        nightly_df, nightly_meta = try_serve_top_board(
            profile=str(profile or "growth"),
            top_n=10,
            force_live=bool(_force_live),
        )
        if nightly_df is not None and not nightly_df.empty:
            _LAST_AUTOPILOT_UNIVERSE_META = {
                **nightly_meta,
                "symbols_sample": [str(x) for x in nightly_df["Mã"].head(12).tolist()]
                if "Mã" in nightly_df.columns
                else [],
            }
            out = nightly_df[[c for c in _AUTOPILOT_KEEP_COLUMNS if c in nightly_df.columns]]
            log_timing(
                "scanner.load_autopilot_board",
                (perf_counter() - started_at) * 1000.0,
                profile=str(profile or ""),
                universe_size=int(nightly_meta.get("scanned_count") or 0),
                universe_total_listed=int(nightly_meta.get("target_count") or 0),
                rotation_offset=0,
                universe_mode="nightly_board",
                out_rows=len(out),
                board_coverage_pct=float(nightly_meta.get("coverage_pct") or 0.0),
            )
            return out
    except Exception as exc:
        logger.warning("autopilot_nightly_board_serve_skipped error=%s", exc.__class__.__name__)

    rd = date.today().toordinal() if _rotation_day is None else int(_rotation_day)
    lim = max(10, min(int(universe_limit or 30), 120))
    # Disk-first listing — tránh refresh API treo khi Vietcap chậm.
    try:
        from scrapers.vn_listing import list_tradable_vn_symbols

        full = list(list_tradable_vn_symbols(use_api=False) or [])
    except Exception:
        full = []
    if not full:
        full = list_universe_symbols(limit=None)
    symbols, uni_meta = resolve_scan_universe(
        lim,
        full_listing=full,
        rotation_day=rd,
        rotation_key="autopilot",
    )
    universe = tuple(symbols)
    off = int(uni_meta.get("offset") or 0)
    _LAST_AUTOPILOT_UNIVERSE_META = {
        **uni_meta,
        "symbols_sample": list(universe[:12]),
        "symbols_count": len(universe),
        "listing_total": len(full),
        "window_start": int(off) + 1,
        "window_end": int(off) + len(universe),
        "source": "live_rotation",
    }
    df = scan_potential_stocks(universe, profile, float(min_avg_volume_20))
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        out = pd.DataFrame(columns=list(_AUTOPILOT_KEEP_COLUMNS))
    else:
        ready = df[df["Trạng thái"] == "Sẵn sàng"].copy() if "Trạng thái" in df.columns else df.copy()
        base = ready if not ready.empty else df.copy()
        if "Khuyến nghị" not in base.columns:
            base = base.copy()
            base["Khuyến nghị"] = "AVOID"
        for col, default in (
            ("Expected Return %", 0.0),
            ("MOS%", 0.0),
            ("Risk % (ước tính)", 0.0),
        ):
            if col not in base.columns:
                base[col] = default
        # P3: reuse nightly score_rows (CONDITIONAL_BUY rank + Proprietary Score boost)
        try:
            from core.autopilot_nightly_board import score_rows

            scored = score_rows(base.to_dict(orient="records"))
            if scored.empty:
                ranked = scored
            else:
                kn = scored["Khuyến nghị"].astype(str).str.upper()
                verdict = (
                    scored["analysis_verdict"].astype(str).str.upper()
                    if "analysis_verdict" in scored.columns
                    else pd.Series([""] * len(scored), index=scored.index)
                )
                restricted = (
                    scored["is_gate_restricted"].fillna(False).astype(bool)
                    if "is_gate_restricted" in scored.columns
                    else pd.Series([False] * len(scored), index=scored.index)
                )
                eligible = scored.loc[(kn != "AVOID") & (verdict != "NO-GO") & (~restricted)].copy()
                if eligible.empty:
                    eligible = scored.loc[(kn != "AVOID") & (verdict != "NO-GO")].copy()
                if eligible.empty:
                    eligible = scored.copy()
                ranked = (
                    eligible.drop(columns=["__rank", "__score", "score_penalty_mult"], errors="ignore")
                    .head(10)
                    .reset_index(drop=True)
                )
        except Exception as exc:
            logger.warning("autopilot_live_score_rows_fallback error=%s", exc.__class__.__name__)
            rank_map = {"BUY": 4, "CONDITIONAL_BUY": 3, "HOLD": 2, "WATCH": 1, "AVOID": 0}
            if "gate_action" in base.columns:
                ga = base["gate_action"].astype(str).str.upper()
                use_ga = ga.isin(["BUY", "CONDITIONAL_BUY", "HOLD", "WATCH", "AVOID"])
                base.loc[use_ga, "Khuyến nghị"] = ga[use_ga]
            base["__rank"] = base["Khuyến nghị"].map(rank_map).fillna(0)
            base["__score"] = (
                base["__rank"] * 20
                + base["Expected Return %"].fillna(0) * 0.7
                + base["MOS%"].fillna(0) * 0.3
                - base["Risk % (ước tính)"].fillna(0) * 0.2
            )
            if "is_gate_restricted" not in base.columns:
                base["is_gate_restricted"] = False
            else:
                base["is_gate_restricted"] = base["is_gate_restricted"].fillna(False).astype(bool)
            try:
                from core.proprietary_signal import proprietary_score_from_row

                base["Proprietary Score"] = base.apply(lambda r: proprietary_score_from_row(dict(r)), axis=1)
                base["__score"] = base["__score"] + base["Proprietary Score"].fillna(0) * 0.12
            except Exception:
                pass
            ranked = (
                base.sort_values(["__score", "MOS%"], ascending=[False, False])
                .drop(columns=["__rank", "__score"], errors="ignore")
                .head(10)
                .reset_index(drop=True)
            )
        try:
            from core.autopilot_nightly_board import board_title_for_ranked

            _LAST_AUTOPILOT_UNIVERSE_META["board_title_vi"] = board_title_for_ranked(ranked)
        except Exception:
            _LAST_AUTOPILOT_UNIVERSE_META["board_title_vi"] = "Top 10 Thanh Khoản / Theo Dõi"
        out = ranked[[c for c in _AUTOPILOT_KEEP_COLUMNS if c in ranked.columns]]
    log_timing(
        "scanner.load_autopilot_board",
        (perf_counter() - started_at) * 1000.0,
        profile=str(profile or ""),
        universe_size=len(universe),
        universe_total_listed=len(full),
        rotation_offset=int(off),
        universe_mode=str(uni_meta.get("mode") or ""),
        out_rows=len(out),
    )
    return out


@st.cache_data(ttl=240)
def build_autopilot_simple_view(
    symbols: tuple[str, ...],
    profile: str,
    total_capital_vnd: float,
    quick_mode: bool = True,
    llm_live: bool = True,
) -> pd.DataFrame:
    rows: list[dict] = []
    for sym in symbols:
        snap = load_snapshot_cached(sym)
        if snap is None:
            continue
        try:
            rep = load_strategic_report_cached(
                sym,
                snap,
                profile,
                float(total_capital_vnd),
                quick_mode=quick_mode,
                llm_live=llm_live,
            )
        except Exception:
            continue
        rp = rep.get("risk_plan") or {}
        val = rep.get("valuation") or {}
        try:
            from core.decision_action_gate import resolve_display_action

            gate = resolve_display_action(rep)
            action = str(gate.get("display_action") or "WATCH").upper()
            show_plan = bool(gate.get("show_trade_plan"))
            readiness = gate.get("decision_readiness")
            legend_note = gate.get("note_vi") or "—"
            missing_summary = gate.get("missing_summary") or "—"
        except Exception:
            action = str(rep.get("final_action") or "WATCH").upper()
            show_plan = action in ("BUY", "HOLD")
            readiness = str(rep.get("decision_readiness") or "LOW")
            legend_note = "—"
            missing_summary = "—"
        price_now = float(val.get("price") or snap.get("price") or 0)
        intrinsic = float(val.get("composite_target_price") or val.get("intrinsic_value_graham") or 0)
        mos = val.get("margin_of_safety_composite_pct")
        rows.append(
            {
                "Mã": sym,
                "Hành động": action,
                "Decision readiness": readiness,
                "Thiếu DL": missing_summary,
                "Legend vs action": legend_note,
                "Giá hiện tại": round(price_now, 2) if price_now > 0 else None,
                "Giá trị nội tại": round(intrinsic, 2) if intrinsic > 0 else None,
                "Biên an toàn %": round(float(mos), 1) if mos is not None else None,
                "Giá vào": round(float(rp.get("entry_price") or 0), 2) if show_plan and float(rp.get("entry_price") or 0) > 0 else None,
                "SL": round(float(rp.get("stop_loss_price") or 0), 2) if show_plan and float(rp.get("stop_loss_price") or 0) > 0 else None,
                "TP": round(float(rp.get("take_profit_price") or 0), 2) if show_plan and float(rp.get("take_profit_price") or 0) > 0 else None,
                "Tỷ trọng %": round(float(rp.get("max_position_pct") or 0), 1),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "Mã",
                "Hành động",
                "Decision readiness",
                "Thiếu DL",
                "Legend vs action",
                "Giá hiện tại",
                "Giá trị nội tại",
                "Biên an toàn %",
                "Giá vào",
                "SL",
                "TP",
                "Tỷ trọng %",
            ]
        )
    df = pd.DataFrame(rows)
    rank = {"BUY": 3, "HOLD": 2, "WATCH": 1, "AVOID": 0}
    df["__r"] = df["Hành động"].map(rank).fillna(0)
    df = df.sort_values(["__r", "Tỷ trọng %"], ascending=[False, False]).drop(columns=["__r"]).reset_index(drop=True)
    return df


@st.cache_data(ttl=240)
def build_profit_focus_board(
    symbols: tuple[str, ...],
    profile: str,
    total_capital_vnd: float,
    quick_mode: bool = True,
    llm_live: bool = True,
) -> pd.DataFrame:
    rows: list[dict] = []
    for sym in symbols:
        snap = load_snapshot_cached(sym)
        if snap is None:
            continue
        try:
            rep = load_strategic_report_cached(
                sym,
                snap,
                profile,
                float(total_capital_vnd),
                quick_mode=quick_mode,
                llm_live=llm_live,
            )
        except Exception:
            continue
        act = str(rep.get("final_action") or "WATCH").upper()
        gate_ok = bool(rep.get("gate_passed"))
        out_ok = bool(rep.get("output_gate_passed", True))
        conf = float(rep.get("confidence_score") or 0)
        rp = rep.get("risk_plan") or {}
        entry = float(rp.get("entry_price") or 0)
        sl = float(rp.get("stop_loss_price") or 0)
        tp = float(rp.get("take_profit_price") or 0)
        rr = ((tp - entry) / max(entry - sl, 1e-6)) if entry > sl > 0 and tp > entry else 0.0
        if act not in ("BUY", "HOLD"):
            continue
        if not gate_ok or not out_ok:
            continue
        if rr < 2.0:
            continue
        val = rep.get("valuation") or {}
        mos = float(val.get("margin_of_safety_composite_pct") or 0)
        score = conf * 0.7 + mos * 0.4 + rr * 10.0
        rows.append(
            {
                "Mã": sym,
                "Hành động": act,
                "Entry": round(entry, 2),
                "SL": round(sl, 2),
                "TP": round(tp, 2),
                "RR": round(rr, 2),
                "Confidence %": round(conf, 1),
                "MOS %": round(mos, 1),
                "Điểm ưu tiên": round(score, 2),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["Mã", "Hành động", "Entry", "SL", "TP", "RR", "Confidence %", "MOS %", "Điểm ưu tiên"])
    return pd.DataFrame(rows).sort_values("Điểm ưu tiên", ascending=False).head(8).reset_index(drop=True)


@st.cache_data(ttl=240)
def build_daily_action_list(
    universe: tuple[str, ...],
    profile: str,
    total_capital_vnd: float,
    held_symbols: tuple[str, ...],
    quick_mode: bool = True,
    llm_live: bool = True,
) -> pd.DataFrame:
    held = {str(x).upper() for x in held_symbols}
    rows: list[dict] = []
    for sym in universe:
        snap = load_snapshot_cached(sym)
        if snap is None:
            continue
        try:
            rep = load_strategic_report_cached(
                sym,
                snap,
                profile,
                float(total_capital_vnd),
                quick_mode=quick_mode,
                llm_live=llm_live,
            )
        except Exception:
            continue
        val = rep.get("valuation") or {}
        rp = rep.get("risk_plan") or {}
        phase = rep.get("phase") or {}
        conf = float(rep.get("confidence_score") or 0)
        gate = bool(rep.get("gate_passed"))
        out_gate = bool(rep.get("output_gate_passed", True))
        act = str(rep.get("final_action") or "WATCH").upper()
        mos = float(val.get("margin_of_safety_composite_pct") or 0)
        fscore = int(val.get("piotroski_score") or 0)
        ph = str(phase.get("phase") or "neutral")
        price = float(val.get("price") or snap.get("price") or 0)
        entry = float(rp.get("entry_price") or 0)
        sl = float(rp.get("stop_loss_price") or 0)
        tp = float(rp.get("take_profit_price") or 0)

        if sym in held:
            if act == "AVOID" or (ph == "distribution" and conf < 55):
                action_today = "SELL"
                reason = "Vị thế đang rủi ro cao (pha phân phối/độ tin cậy thấp), ưu tiên bảo toàn vốn."
            else:
                action_today = "HOLD"
                reason = "Đang có vị thế và cấu trúc chưa xấu, tiếp tục giữ kỷ luật theo kế hoạch."
        else:
            if act == "BUY" and gate and out_gate:
                action_today = "BUY"
                reason = "Đạt chuẩn xuống tiền: gate pass + output pass + cấu trúc kế hoạch hợp lệ."
            elif act == "HOLD":
                action_today = "WATCH"
                reason = "Tín hiệu trung tính, chờ điểm vào đẹp hơn trước khi giải ngân."
            else:
                action_today = "WATCH"
                reason = "Chưa đạt chuẩn hành động, theo dõi thêm để tránh quyết định sớm."

        rows.append(
            {
                "Mã": sym,
                "Hành động hôm nay": action_today,
                "Giá hiện tại": round(price, 2) if price > 0 else None,
                "Entry": round(entry, 2) if entry > 0 else None,
                "SL": round(sl, 2) if sl > 0 else None,
                "TP": round(tp, 2) if tp > 0 else None,
                "Confidence %": round(conf, 1),
                "MOS %": round(mos, 1),
                "F-Score": fscore,
                "Pha": ph,
                "Lý do ngắn": reason,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["Mã", "Hành động hôm nay", "Giá hiện tại", "Entry", "SL", "TP", "Confidence %", "MOS %", "F-Score", "Pha", "Lý do ngắn"]
        )
    df = pd.DataFrame(rows)
    rank = {"BUY": 3, "HOLD": 2, "WATCH": 1, "SELL": 0}
    df["__r"] = df["Hành động hôm nay"].map(rank).fillna(0)
    df = df.sort_values(["__r", "Confidence %", "MOS %"], ascending=[False, False, False]).drop(columns=["__r"]).reset_index(drop=True)
    return df


def simple_view_for_plan(df: pd.DataFrame, plan_id: str) -> pd.DataFrame:
    pid = str(plan_id or "free").strip().lower()
    if df.empty:
        return df
    if pid in ("pro", "expert"):
        return df
    # Free: keep decision trust columns; drop Entry/SL/TP only.
    cols = [
        c
        for c in [
            "Mã",
            "Hành động",
            "Khuyến nghị",
            "Decision readiness",
            "Readiness",
            "Thiếu DL",
            "Ghi chú Legend",
            "Legend vs action",
            "Thesis",
            "Setup",
            "Trigger",
            "Giá hiện tại",
            "Giá",
            "Giá trị nội tại",
            "Biên an toàn %",
            "MOS%",
            "Tỷ trọng %",
            "Playbook",
        ]
        if c in df.columns
    ]
    if not cols:
        return df
    return df[cols].copy()
