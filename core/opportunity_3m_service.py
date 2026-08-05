from __future__ import annotations

import os
from concurrent.futures import as_completed
from typing import Any

import pandas as pd
import streamlit as st

from core import analysis_runtime_service as ars
from core.catalyst_engine import calculate_catalyst_score
from core.opportunity_finder import evaluate_stock_opportunity_3m
from core.strategy_backtest import fetch_vn_benchmark_series
from core.streamlit_executor import streamlit_thread_pool_executor
from scrapers.portal import fetch_ohlcv_history


def _finder_ohlcv_sessions() -> int:
    """Finder chỉ cần ~130+ nến cho data quality; tránh load_ohlcv_cached (1000+ phiên) × hàng chục mã → treo UI."""
    try:
        n = int(os.environ.get("II_FINDER_OHLCV_SESSIONS", "220") or "220")
    except ValueError:
        n = 220
    return max(130, min(500, n))


def _finder_parallel_enabled() -> bool:
    """Song song I/O qua ThreadPoolExecutor (impl không bọc st.cache_data — an toàn trong worker)."""
    v = str(os.environ.get("II_FINDER_PARALLEL", "1") or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def _finder_max_workers(num_symbols: int) -> int:
    try:
        w = int(os.environ.get("II_FINDER_MAX_WORKERS", "4") or "4")
    except ValueError:
        w = 4
    return max(1, min(12, w, max(1, num_symbols)))


def build_opportunity_3m_board_impl(
    universe: tuple[str, ...],
    profile: str,
    total_capital_vnd: float,
    quick_mode: bool = True,
    llm_live: bool = False,
    allowed_subtypes: tuple[str, ...] = (),
    min_avg_volume_20: float = 0.0,
    benchmark_return_3m_pct: float | None = None,
    min_data_quality_pct: float = 55.0,
    only_actionable: bool = False,
    min_catalyst_score: float = 0.0,
    dynamic_sector_calibration: bool = True,
    top_n: int = 25,
) -> pd.DataFrame:
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _sector_calibration(subtype_id: str) -> tuple[float, float, str]:
        sid = str(subtype_id or "other").strip().lower()
        table: dict[str, tuple[float, float, str]] = {
            "bank": (0.92, 1.08, "Ngân hàng: ưu tiên chất lượng tài sản và định giá."),
            "insurance": (0.94, 1.06, "Bảo hiểm: ưu tiên nền tảng tài chính ổn định."),
            "securities": (1.06, 0.94, "Chứng khoán: nhạy chu kỳ, ưu tiên tín hiệu giá/khối lượng."),
            "real_estate_residential": (1.03, 0.97, "BĐS dân dụng: tăng trọng số kỹ thuật để bắt nhịp chu kỳ."),
            "real_estate_kcn": (1.00, 1.00, "BĐS KCN: cân bằng kỹ thuật và cơ bản."),
            "consumer_staples": (0.96, 1.04, "Tiêu dùng thiết yếu: ưu tiên chất lượng lợi nhuận."),
            "consumer_retail": (1.02, 0.98, "Bán lẻ: thiên về động lượng khi nhu cầu cải thiện."),
            "oil_gas": (1.08, 0.92, "Dầu khí: biến động theo chu kỳ hàng hóa."),
            "steel_materials": (1.10, 0.90, "Thép & vật liệu: chu kỳ mạnh, ưu tiên xung lực."),
            "pharma_healthcare": (0.95, 1.05, "Dược & y tế: ưu tiên tính bền vững tài chính."),
            "technology_services": (1.04, 0.96, "Công nghệ: cân nhắc động lượng tăng trưởng."),
            "other": (1.00, 1.00, "Khác: dùng trọng số trung tính."),
        }
        return table.get(sid, table["other"])

    def _profile_reco(
        profile_key: str,
        score: float,
        prob: float,
        conf: float,
        wf: float,
        alpha: float | None,
        catalyst_pass: bool,
    ) -> str:
        a = float(alpha) if alpha is not None else 0.0
        conf_adj = conf + (4.0 if llm_live else 0.0)
        reco = "CHỜ"
        if profile_key == "safe_dividend":
            if score >= 75 and prob >= 72 and conf_adj >= 70 and wf >= 55 and a >= 0:
                reco = "MUA"
            elif score >= 62 and prob >= 62 and conf_adj >= 60:
                reco = "THEO DÕI"
        elif profile_key == "aggressive_trading":
            if score >= 65 and prob >= 65 and conf_adj >= 58:
                reco = "MUA"
            elif score >= 52 and prob >= 55:
                reco = "THEO DÕI"
        else:
            if score >= 70 and prob >= 68 and conf_adj >= 62 and wf >= 45:
                reco = "MUA"
            elif score >= 58 and prob >= 58 and conf_adj >= 55:
                reco = "THEO DÕI"

        if reco == "MUA" and not catalyst_pass:
            return "THEO DÕI THÊM - CHƯA NÊN MUA (CHỜ TÍN HIỆU)"
        return reco

    def _profile_priority(profile_key: str, row: dict[str, Any]) -> float:
        s = _as_float(row.get("Điểm cơ hội (hiệu chỉnh ngành)") or row.get("Điểm cơ hội"))
        p = _as_float(row.get("Xác suất tăng 3M %"))
        c = _as_float(row.get("Độ tin cậy %"))
        w = _as_float(row.get("Reliability WF %"))
        a = _as_float(row.get("Alpha 3M vs Benchmark %"))
        if profile_key == "safe_dividend":
            return s * 0.30 + p * 0.25 + c * 0.20 + w * 0.20 + a * 0.05
        if profile_key == "aggressive_trading":
            return s * 0.35 + p * 0.30 + c * 0.15 + w * 0.10 + a * 0.10
        return s * 0.33 + p * 0.28 + c * 0.18 + w * 0.15 + a * 0.06

    def _derive_dynamic_sector_multipliers(
        pool: list[dict[str, float | str]],
    ) -> dict[str, tuple[float, float, str]]:
        result: dict[str, tuple[float, float, str]] = {}
        grouped: dict[str, list[dict[str, float | str]]] = {}
        for row in pool:
            sid = str(row.get("subtype_id") or "other").strip().lower()
            grouped.setdefault(sid, []).append(row)
        for sid, rows_sid in grouped.items():
            if len(rows_sid) < 3:
                continue
            tech_hits = 0
            fund_hits = 0
            for r in rows_sid:
                ret = float(r.get("ret_3m") or 0.0)
                tech = float(r.get("tech") or 0.0)
                fund = float(r.get("fund") or 0.0)
                if ret >= 8.0 and tech >= 25.0:
                    tech_hits += 1
                if ret >= 8.0 and fund >= 25.0:
                    fund_hits += 1
            n = float(len(rows_sid))
            tech_hit_rate = tech_hits / n
            fund_hit_rate = fund_hits / n
            delta = max(-0.10, min(0.10, (tech_hit_rate - fund_hit_rate) * 0.20))
            tech_mult = max(0.90, min(1.10, 1.0 + delta))
            fund_mult = max(0.90, min(1.10, 1.0 - delta))
            result[sid] = (
                round(tech_mult, 2),
                round(fund_mult, 2),
                f"Động theo dữ liệu ngành ({int(n)} mã): tech_hit={tech_hit_rate*100:.0f}%, fund_hit={fund_hit_rate*100:.0f}%",
            )
        return result

    rows: list[dict[str, object]] = []
    staged_rows: list[dict[str, Any]] = []
    candidate_pool: list[dict[str, float | str]] = []
    allowed = {x.strip().lower() for x in allowed_subtypes if str(x).strip()}
    packs: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None, Any]] = []
    use_parallel = _finder_parallel_enabled() and len(universe) > 1

    def work_one(sym: str) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, Any]:
        snap = ars._snapshot_impl(sym)
        if snap is None:
            return sym, None, None, None
        try:
            rep = ars._strategic_report_impl(
                sym,
                snap,
                profile,
                float(total_capital_vnd),
                quick_mode=quick_mode,
                llm_live=llm_live,
            )
            try:
                ohlcv = fetch_ohlcv_history(sym, sessions=_finder_ohlcv_sessions())
                if ohlcv is None or getattr(ohlcv, "empty", True):
                    ohlcv = ars._ohlcv_impl(sym)
            except Exception:
                ohlcv = ars._ohlcv_impl(sym)
            return sym, snap, rep, ohlcv
        except Exception:
            return sym, None, None, None

    if use_parallel:

        workers = _finder_max_workers(len(universe))
        by_sym: dict[str, tuple[str, dict[str, Any] | None, dict[str, Any] | None, Any]] = {}
        with streamlit_thread_pool_executor(max_workers=workers) as ex:
            futs = {ex.submit(work_one, sym): sym for sym in universe}
            for fut in as_completed(futs):
                try:
                    tup = fut.result()
                except Exception:
                    continue
                by_sym[tup[0]] = tup
        for sym in universe:
            if sym in by_sym:
                packs.append(by_sym[sym])
    else:
        for sym in universe:
            tup = work_one(sym)
            if tup[1] is not None:
                packs.append(tup)

    for sym, snap, rep, ohlcv in packs:
        if snap is None or rep is None or ohlcv is None:
            continue
        val = rep.get("valuation") or {}
        fin = rep.get("financials") or {}
        news_items = rep.get("news") or []
        news_blob = " | ".join(str(x.get("title") or "") for x in news_items[:8])
        subtype_id = str(val.get("industry_subtype_id") or "other").strip().lower()
        if allowed and subtype_id not in allowed:
            continue
        out = evaluate_stock_opportunity_3m(
            sym,
            ohlcv,
            val,
            fin,
            benchmark_return_3m_pct=benchmark_return_3m_pct,
            news_items=news_items if isinstance(news_items, list) else None,
        )
        catalyst = calculate_catalyst_score(sym, ohlcv, val, news_text=news_blob)
        if float(out.avg_volume_20 or 0.0) < float(min_avg_volume_20 or 0.0):
            continue
        if float(out.data_quality_pct or 0.0) < float(min_data_quality_pct or 0.0):
            continue
        if float(catalyst.catalyst_score or 0.0) < float(min_catalyst_score or 0.0):
            continue
        if only_actionable and out.status not in ("CƠ HỘI CAO", "THEO DÕI"):
            continue
        candidate_pool.append(
            {
                "subtype_id": subtype_id,
                "tech": float(out.technical_score),
                "fund": float(out.fundamental_score),
                "ret_3m": float(out.return_3m_recent_pct),
            }
        )
        staged_rows.append(
            {
                "symbol": out.symbol,
                "status": out.status,
                "reco_reason": out.recommendation_reason,
                "subtype_id": subtype_id,
                "subtype_label": str(val.get("industry_subtype_label_vi") or "Khác"),
                "out": out,
                "catalyst": catalyst,
            }
        )

    dyn_map = _derive_dynamic_sector_multipliers(candidate_pool) if dynamic_sector_calibration else {}
    for srow in staged_rows:
        out = srow["out"]
        catalyst = srow["catalyst"]
        subtype_id = str(srow["subtype_id"])
        tech_mult, fund_mult, sector_note = _sector_calibration(subtype_id)
        dyn = dyn_map.get(subtype_id)
        if dyn is not None:
            tech_mult, fund_mult, sector_note = dyn
        adjusted_tech = max(0.0, min(50.0, float(out.technical_score) * tech_mult))
        adjusted_fund = max(0.0, min(50.0, float(out.fundamental_score) * fund_mult))
        sector_adjusted_score = round(max(0.0, min(100.0, adjusted_tech + adjusted_fund)), 2)
        rows.append(
            {
                "Mã": str(srow["symbol"]),
                "Trạng thái": str(srow["status"]),
                "Lý do khuyến nghị": str(srow["reco_reason"]),
                "Ngành con": str(srow["subtype_label"]),
                "Điểm cơ hội": out.score,
                "Điểm cơ hội (hiệu chỉnh ngành)": sector_adjusted_score,
                "Catalyst Score": catalyst.catalyst_score,
                "Catalyst Pass": "YES" if catalyst.passed else "NO",
                "Catalyst Lý do": " ; ".join(catalyst.reasons[:3]) if catalyst.reasons else "",
                "Pha thị trường": out.market_phase_label,
                "Smart money": out.smart_money_bias,
                "Smart money score": out.smart_money_score,
                "Điểm kỹ thuật": out.technical_score,
                "Điểm cơ bản": out.fundamental_score,
                "Hệ số ngành (KT/CB)": f"{tech_mult:.2f}/{fund_mult:.2f}",
                "Xác suất tăng 3M %": out.probability_up_3m_pct,
                "Bull %": out.bull_prob_pct,
                "Base %": out.base_prob_pct,
                "Bear %": out.bear_prob_pct,
                "Lợi nhuận kỳ vọng 3M %": out.expected_return_3m_pct,
                "Độ tin cậy %": out.confidence_pct,
                "Hit-rate 3M lịch sử %": out.historical_hit_rate_3m_pct,
                "Reliability WF %": out.walkforward_reliability_pct,
                "Return 3M gần nhất %": out.return_3m_recent_pct,
                "Alpha 3M vs Benchmark %": out.alpha_3m_vs_benchmark_pct,
                "KL TB20": round(out.avg_volume_20, 0),
                "Data Quality %": out.data_quality_pct,
                "Ghi chú hiệu chỉnh ngành": sector_note,
                "Luận điểm chính": out.thesis,
                "Rủi ro chính": out.risks,
                "Mốc vô hiệu": out.invalidation,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "Mã",
                "Trạng thái",
                "Lý do khuyến nghị",
                "Ngành con",
                "Điểm cơ hội",
                "Điểm cơ hội (hiệu chỉnh ngành)",
                "Catalyst Score",
                "Catalyst Pass",
                "Catalyst Lý do",
                "Pha thị trường",
                "Smart money",
                "Smart money score",
                "Điểm kỹ thuật",
                "Điểm cơ bản",
                "Hệ số ngành (KT/CB)",
                "Xác suất tăng 3M %",
                "Bull %",
                "Base %",
                "Bear %",
                "Lợi nhuận kỳ vọng 3M %",
                "Độ tin cậy %",
                "Hit-rate 3M lịch sử %",
                "Reliability WF %",
                "Return 3M gần nhất %",
                "Alpha 3M vs Benchmark %",
                "KL TB20",
                "Data Quality %",
                "Ghi chú hiệu chỉnh ngành",
                "Luận điểm chính",
                "Rủi ro chính",
                "Mốc vô hiệu",
            ]
        )
    out_df = pd.DataFrame(rows)
    out_df["Khuyến nghị theo profile"] = [
        _profile_reco(
            profile,
            float(r.get("Điểm cơ hội (hiệu chỉnh ngành)") or r.get("Điểm cơ hội") or 0),
            float(r.get("Xác suất tăng 3M %") or 0),
            float(r.get("Độ tin cậy %") or 0),
            float(r.get("Reliability WF %") or 0),
            r.get("Alpha 3M vs Benchmark %"),
            str(r.get("Catalyst Pass") or "").upper() == "YES",
        )
        for _, r in out_df.iterrows()
    ]
    _label_to_rank = {"Tích lũy": 3, "Breakout": 4, "Phân phối": 1, "Trung tính": 2}
    out_df["__phase_rank"] = [int(_label_to_rank.get(str(r.get("Pha thị trường") or ""), 2)) for _, r in out_df.iterrows()]
    out_df["__priority"] = [_profile_priority(profile, dict(r)) for _, r in out_df.iterrows()]
    out_df = out_df.sort_values(
        ["__priority", "__phase_rank", "Catalyst Score", "Smart money score", "Data Quality %", "Điểm cơ hội", "Xác suất tăng 3M %"],
        ascending=[False, False, False, False, False, False, False],
    )
    return out_df.head(max(1, int(top_n))).drop(columns=["__priority", "__phase_rank"]).reset_index(drop=True)


@st.cache_data(ttl=240)
def build_opportunity_3m_board(
    universe: tuple[str, ...],
    profile: str,
    total_capital_vnd: float,
    quick_mode: bool = True,
    llm_live: bool = False,
    allowed_subtypes: tuple[str, ...] = (),
    min_avg_volume_20: float = 0.0,
    benchmark_return_3m_pct: float | None = None,
    min_data_quality_pct: float = 55.0,
    only_actionable: bool = False,
    min_catalyst_score: float = 0.0,
    dynamic_sector_calibration: bool = True,
    top_n: int = 25,
) -> pd.DataFrame:
    return build_opportunity_3m_board_impl(
        universe,
        profile,
        total_capital_vnd,
        quick_mode=quick_mode,
        llm_live=llm_live,
        allowed_subtypes=allowed_subtypes,
        min_avg_volume_20=min_avg_volume_20,
        benchmark_return_3m_pct=benchmark_return_3m_pct,
        min_data_quality_pct=min_data_quality_pct,
        only_actionable=only_actionable,
        min_catalyst_score=min_catalyst_score,
        dynamic_sector_calibration=dynamic_sector_calibration,
        top_n=top_n,
    )


@st.cache_data(ttl=600)
def load_benchmark_return_3m() -> tuple[float | None, str]:
    try:
        bench, label = fetch_vn_benchmark_series("2y")
    except Exception:
        return None, ""
    if bench is None or len(bench) < 64:
        return None, label
    try:
        b0 = float(bench.iloc[-64])
        b1 = float(bench.iloc[-1])
        if b0 <= 0:
            return None, label
        ret = (b1 / b0 - 1.0) * 100.0
        return round(ret, 2), label
    except Exception:
        return None, label
