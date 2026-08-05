"""
Finder 3M opportunity panel rendering.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st

from core import pg_analysis_jobs as pgj
from core.ui_bg_analysis import read_analysis_job_status, try_consume_analysis_job
from core.ui_day_cache import cache_key_hash, day_cache_load, day_cache_save

FINDER_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "label": "Thử nhanh (khuyến nghị)",
        "help": "Lọc nhẹ — dễ thấy danh sách mã ngay khi demo / mạng chậm.",
        "opp_limit": 30,
        "min_avg_vol20": 0.0,
        "min_data_quality": 40.0,
        "min_catalyst_score": 0.0,
        "only_actionable": False,
        "dynamic_sector": True,
    },
    "quality": {
        "label": "Chất lượng cao",
        "help": "Lọc chặt — ưu tiên mã actionable, thanh khoản và catalyst rõ.",
        "opp_limit": 60,
        "min_avg_vol20": 300_000.0,
        "min_data_quality": 55.0,
        "min_catalyst_score": 70.0,
        "only_actionable": True,
        "dynamic_sector": True,
    },
}


def _default_finder_preset_id() -> str:
    raw = str(os.environ.get("II_FINDER_PRESET_DEFAULT", "quick") or "quick").strip().lower()
    return raw if raw in FINDER_PRESETS else "quick"


def _apply_finder_preset(preset_id: str) -> None:
    pid = preset_id if preset_id in FINDER_PRESETS else "quick"
    p = FINDER_PRESETS[pid]
    st.session_state["finder_preset_id"] = pid
    st.session_state["finder_opp_limit"] = int(p["opp_limit"])
    st.session_state["finder_min_avg_vol20"] = float(p["min_avg_vol20"])
    st.session_state["finder_min_data_quality"] = float(p["min_data_quality"])
    st.session_state["finder_min_catalyst_score"] = float(p["min_catalyst_score"])
    st.session_state["finder_only_actionable"] = bool(p["only_actionable"])
    st.session_state["finder_dynamic_sector"] = bool(p["dynamic_sector"])


def _ensure_finder_preset_state() -> None:
    if "finder_opp_limit" not in st.session_state:
        _apply_finder_preset(_default_finder_preset_id())
        st.session_state["finder_preset_last_applied"] = st.session_state["finder_preset_id"]
        return
    if "finder_preset_id" not in st.session_state:
        st.session_state["finder_preset_id"] = _default_finder_preset_id()


def _format_cache_age(age_sec: float) -> str:
    sec = max(0, int(age_sec))
    if sec < 60:
        return f"{sec}s"
    minutes, seconds = divmod(sec, 60)
    return f"{minutes}m {seconds}s"


def render_finder_panel(
    *,
    user_id: str,
    profile: str,
    total_capital_vnd: float,
    effective_quick_mode: bool,
    plan: dict[str, Any],
    subtype_label_to_id: dict[str, str],
    universe_subtype_map: Callable[[], dict[str, str]],
    list_universe_symbols: Callable[..., list[str]],
    build_opportunity_3m_board: Callable[..., pd.DataFrame],
    load_benchmark_return_3m: Callable[..., tuple[float | None, str | None]],
) -> None:
    st.markdown("### 🎯 Finder: Cổ phiếu cơ hội tăng trưởng trong 3 tháng tới")
    st.caption(
        "Quét universe, kết hợp lịch sử giá + thanh khoản + tài chính + định giá + **pha tích lũy/breakout** "
        "+ **smart money (tin/CBTT)** để ước lượng xác suất tăng trưởng giá trong 3 tháng tới."
    )

    _ensure_finder_preset_state()
    _preset_labels = {k: str(v["label"]) for k, v in FINDER_PRESETS.items()}
    preset_choice = st.radio(
        "Chế độ Finder",
        options=list(FINDER_PRESETS.keys()),
        format_func=lambda x: _preset_labels.get(x, x),
        horizontal=True,
        key="finder_preset_id",
        help="Thử nhanh: lọc nhẹ để thấy kết quả ngay. Chất lượng cao: lọc chặt như trước.",
    )
    last_applied = str(st.session_state.get("finder_preset_last_applied") or "")
    if preset_choice != last_applied:
        _apply_finder_preset(str(preset_choice))
        st.session_state["finder_preset_last_applied"] = str(preset_choice)
        st.rerun()

    active = FINDER_PRESETS.get(str(preset_choice), FINDER_PRESETS["quick"])
    st.caption(str(active.get("help") or ""))

    opp_limit = int(
        st.slider(
            "Số mã quét Finder tăng trưởng 3 tháng tới",
            min_value=20,
            max_value=200,
            step=10,
            key="finder_opp_limit",
        )
    )
    if opp_limit >= 80:
        try:
            fw = int(os.environ.get("II_FINDER_MAX_WORKERS", "4") or "4")
        except ValueError:
            fw = 4
        fw = max(1, min(12, fw))
        st.caption(
            f"Lưu ý thời gian: **{opp_limit}** mã ⇒ mỗi mã cần tải snapshot + OHLCV + báo cáo (tối đa **{fw}** luồng song song). "
            "Mạng chậm dễ **10–25+ phút**; nếu chỉ thử nhanh, hãy giảm còn **20–40** mã."
        )
    subtype_map = universe_subtype_map()
    subtype_ids = sorted(set(str(x or "other").strip().lower() for x in subtype_map.values()))
    subtype_label_by_id = {v: k for k, v in subtype_label_to_id.items()}
    subtype_options = ["Tất cả ngành con"] + [subtype_label_by_id.get(x, x) for x in subtype_ids]
    selected_subtype_labels = st.multiselect(
        "Lọc theo ngành con",
        options=subtype_options,
        default=["Tất cả ngành con"],
    )
    selected_subtypes: tuple[str, ...]
    if "Tất cả ngành con" in selected_subtype_labels or not selected_subtype_labels:
        selected_subtypes = tuple()
    else:
        selected_subtypes = tuple(
            subtype_label_to_id.get(lbl, lbl).strip().lower() for lbl in selected_subtype_labels if lbl != "Tất cả ngành con"
        )
    min_avg_vol20 = float(
        st.number_input(
            "Thanh khoản tối thiểu (KL TB20)",
            min_value=0.0,
            step=50000.0,
            key="finder_min_avg_vol20",
        )
    )
    min_data_quality = float(
        st.slider(
            "Data Quality tối thiểu (%)",
            min_value=30,
            max_value=95,
            step=5,
            key="finder_min_data_quality",
        )
    )
    min_catalyst_score = float(
        st.slider(
            "Catalyst Score tối thiểu",
            min_value=0,
            max_value=100,
            step=5,
            key="finder_min_catalyst_score",
        )
    )
    only_actionable = st.toggle(
        "Chỉ hiện mã actionable (CƠ HỘI CAO/THEO DÕI)",
        help="Ẩn các mã THẬN TRỌNG để tập trung danh sách hành động.",
        key="finder_only_actionable",
    )
    dynamic_sector = st.toggle(
        "Hiệu chỉnh ngành động theo dữ liệu",
        help="Tự cân bằng trọng số kỹ thuật/cơ bản theo hiệu quả lịch sử gần đây của từng ngành.",
        key="finder_dynamic_sector",
    )
    bm_ret_3m, bm_label = load_benchmark_return_3m()
    if bm_ret_3m is not None:
        st.caption(f"Benchmark 3M: {bm_ret_3m:.2f}% ({bm_label or 'market proxy'})")
    else:
        st.caption("Benchmark 3M: chưa khả dụng ở lần tải này.")

    finder_cache_ttl_sec = 180
    finder_cache_key = (
        str(profile or ""),
        str(st.session_state.get("finder_preset_id") or "quick"),
        int(opp_limit),
        float(total_capital_vnd),
        bool(effective_quick_mode),
        bool(plan["llm_live"]),
        tuple(selected_subtypes),
        float(min_avg_vol20),
        float(min_data_quality),
        float(min_catalyst_score),
        bool(only_actionable),
        bool(dynamic_sector),
        float(bm_ret_3m) if bm_ret_3m is not None else None,
        str(bm_label or ""),
        25,
    )
    now_ts = datetime.now(timezone.utc).timestamp()
    cached_key = st.session_state.get("finder_df_cache_key")
    cached_ts = float(st.session_state.get("finder_df_cache_ts") or 0.0)
    cached_df = st.session_state.get("finder_df_cache")
    can_use_cache = (
        cached_key == finder_cache_key
        and (now_ts - cached_ts) <= finder_cache_ttl_sec
        and isinstance(cached_df, pd.DataFrame)
        and (not cached_df.empty)
    )
    finder_cache_age = max(0.0, now_ts - cached_ts) if cached_ts > 0 else 0.0
    day_parts: tuple[Any, ...] = (str(user_id or ""),) + tuple(finder_cache_key)
    day_df = day_cache_load("finder_board", day_parts)
    if isinstance(day_df, pd.DataFrame) and not day_df.empty:
        opportunity_df = day_df.copy()
        cache_status = "DAY_DISK"
        st.session_state["finder_df_cache_key"] = finder_cache_key
        st.session_state["finder_df_cache_ts"] = now_ts
        st.session_state["finder_df_cache"] = opportunity_df.copy()
        finder_cache_age = 0.0
    elif can_use_cache:
        assert isinstance(cached_df, pd.DataFrame)
        opportunity_df = cached_df.copy()
        cache_status = "HIT"
    else:
        try:
            from core.liquid_universe import resolve_scan_universe

            opp_syms, _meta = resolve_scan_universe(
                int(opp_limit),
                rotation_key="finder",
            )
            opp_symbols = tuple(opp_syms)
        except Exception:
            opp_symbols = tuple(list_universe_symbols(limit=opp_limit))
        n_sym = len(opp_symbols)
        jid_parts = (str(user_id or ""),) + tuple(finder_cache_key) + (tuple(opp_symbols),)
        jid = cache_key_hash("finder_pg", jid_parts)

        opportunity_df: pd.DataFrame | None = None
        cache_status = "MISS"
        use_pg_finder = bool(pgj.pg_analysis_jobs_enabled() and pgj.finder_pg_jobs_enabled())

        if use_pg_finder:
            bundle = try_consume_analysis_job(jid)
            if isinstance(bundle, dict):
                fd = bundle.get("finder_df")
                if isinstance(fd, pd.DataFrame):
                    opportunity_df = fd.copy()
                    st.session_state.pop("finder_pg_poll_jid", None)
                    cache_status = "PG_WORKER"
            if opportunity_df is None:
                stt = read_analysis_job_status(jid)
                if stt and stt.get("state") == "error":
                    st.warning(
                        "Finder (PostgreSQL worker) báo lỗi — chuyển sang chạy trực tiếp trong app lần này. "
                        f"Chi tiết: {str(stt.get('error') or '')[:400]}"
                    )
                    st.session_state.pop("finder_pg_poll_jid", None)
                    try:
                        pgj.delete_job_if_failed(jid)
                    except Exception:
                        pass
                    st.session_state["_finder_pg_force_sync_once"] = True
                elif stt and stt.get("state") in ("pending", "running"):
                    st.session_state["finder_pg_poll_jid"] = jid
                    try:
                        from core import state_manager as sm

                        sm.render_job_progress_placeholder(
                            f"Finder **{n_sym} mã** đang chạy trên **PostgreSQL worker** (không chặn tab). "
                            "Đảm bảo `python worker.py` hoặc II_AUTO_START_PG_WORKER=1."
                        )
                    except Exception:
                        st.info(
                            f"Finder **{n_sym} mã** đang chạy trên **PostgreSQL worker** (không chặn tab)."
                        )
                    return
                else:
                    payload = {
                        "universe": list(opp_symbols),
                        "profile": profile,
                        "total_capital_vnd": float(total_capital_vnd),
                        "quick_mode": bool(effective_quick_mode),
                        "llm_live": bool(plan["llm_live"]),
                        "allowed_subtypes": list(selected_subtypes),
                        "min_avg_volume_20": float(min_avg_vol20),
                        "benchmark_return_3m_pct": float(bm_ret_3m) if bm_ret_3m is not None else None,
                        "min_data_quality_pct": float(min_data_quality),
                        "only_actionable": bool(only_actionable),
                        "min_catalyst_score": float(min_catalyst_score),
                        "dynamic_sector_calibration": bool(dynamic_sector),
                        "top_n": 25,
                    }
                    pgj.enqueue_finder_3m_board(jid, payload)
                    st.session_state["finder_pg_poll_jid"] = jid
                    st.info(
                        f"Đã xếp hàng Finder **{n_sym} mã** trên worker Postgres. "
                        "Vui lòng đợi vài phút; nếu kẹt lâu, kiểm tra worker đang chạy."
                    )
                    return

        if opportunity_df is None:
            with st.spinner(
                f"Đang quét Finder ({n_sym} mã): snapshot + OHLCV + báo cáo / mã — có thể vài đến mười mút tùy mạng, "
                "vui lòng không đóng tab…"
            ):
                opportunity_df = build_opportunity_3m_board(
                    opp_symbols,
                    profile,
                    float(total_capital_vnd),
                    quick_mode=effective_quick_mode,
                    llm_live=bool(plan["llm_live"]),
                    allowed_subtypes=selected_subtypes,
                    min_avg_volume_20=min_avg_vol20,
                    benchmark_return_3m_pct=bm_ret_3m,
                    min_data_quality_pct=min_data_quality,
                    min_catalyst_score=min_catalyst_score,
                    only_actionable=only_actionable,
                    dynamic_sector_calibration=dynamic_sector,
                    top_n=25,
                )

        st.session_state["finder_df_cache_key"] = finder_cache_key
        st.session_state["finder_df_cache_ts"] = now_ts
        st.session_state["finder_df_cache"] = opportunity_df.copy()
        finder_cache_age = 0.0
        if cache_status == "MISS" and not opportunity_df.empty:
            try:
                day_cache_save("finder_board", day_parts, opportunity_df.copy())
            except Exception:
                pass
        elif cache_status == "PG_WORKER" and not opportunity_df.empty:
            try:
                day_cache_save("finder_board", day_parts, opportunity_df.copy())
            except Exception:
                pass

    st.caption(
        f"Cache Finder: **{cache_status}** | tuổi cache: "
        f"**{_format_cache_age(finder_cache_age)}** | TTL: **{finder_cache_ttl_sec}s**"
    )
    if opportunity_df.empty:
        st.caption("Chưa đủ dữ liệu để dựng Finder cổ phiếu cơ hội tăng trưởng trong 3 tháng tới.")
        st.info(
            "**Gợi ý nếu bạn đã chờ lâu:** (1) Chọn preset **Thử nhanh** ở trên. "
            "(2) Giảm *Catalyst Score* hoặc tắt *Chỉ hiện mã actionable*. "
            "(3) Hạ *Data Quality* / *KL TB20*. "
            "(4) Giảm *Số mã quét* (20–30). "
            "(5) Kiểm tra mạng — snapshot chậm làm cả vòng quét kéo dài."
        )
        return

    ict_tz = timezone(timedelta(hours=7), "ICT")
    export_dt = datetime.now(ict_tz)
    export_ts = export_dt.strftime("%Y%m%d_%H%M%S")
    export_tag = f"{export_ts}_ICT"
    run_seed = (
        f"{export_tag}|{profile}|"
        f"{','.join(str(x) for x in opportunity_df.get('Mã', pd.Series(dtype=str)).astype(str).tolist())}"
    )
    run_id = hashlib.sha1(run_seed.encode("utf-8")).hexdigest()[:10]
    st.caption(f"Run ID: `{run_id}` | Export time: {export_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    c_opp1, c_opp2, c_opp3 = st.columns(3)
    with c_opp1:
        st.metric("Mã actionable", int(len(opportunity_df)))
    with c_opp2:
        if "Xác suất tăng 3M %" in opportunity_df.columns:
            st.metric("Xác suất tăng TB", f"{float(opportunity_df['Xác suất tăng 3M %'].mean()):.1f}%")
        else:
            st.metric("Xác suất tăng TB", "N/A")
    with c_opp3:
        if "Data Quality %" in opportunity_df.columns:
            st.metric("Data Quality TB", f"{float(opportunity_df['Data Quality %'].mean()):.1f}%")
        else:
            st.metric("Data Quality TB", "N/A")
    st.dataframe(opportunity_df, width="stretch", hide_index=True)
    with st.expander("Sector Calibration Report", expanded=False):
        if "Ngành con" in opportunity_df.columns:
            agg_map: dict[str, tuple[str, str]] = {"so_ma": ("Mã", "count")}
            if "Điểm cơ hội (hiệu chỉnh ngành)" in opportunity_df.columns:
                agg_map["diem_hieu_chinh_tb"] = ("Điểm cơ hội (hiệu chỉnh ngành)", "mean")
            if "Xác suất tăng 3M %" in opportunity_df.columns:
                agg_map["xs_tang_tb"] = ("Xác suất tăng 3M %", "mean")
            if "Data Quality %" in opportunity_df.columns:
                agg_map["data_quality_tb"] = ("Data Quality %", "mean")
            sector_df = (
                opportunity_df.groupby("Ngành con", dropna=False)
                .agg(**{k: v for k, v in agg_map.items()})
                .reset_index()
            )
            if "Hệ số ngành (KT/CB)" in opportunity_df.columns:
                mult_map = (
                    opportunity_df[["Ngành con", "Hệ số ngành (KT/CB)"]]
                    .dropna()
                    .drop_duplicates(subset=["Ngành con"])
                    .set_index("Ngành con")["Hệ số ngành (KT/CB)"]
                    .to_dict()
                )
                sector_df["Hệ số KT/CB"] = sector_df["Ngành con"].map(mult_map)
            sector_df = sector_df.rename(
                columns={
                    "Ngành con": "Ngành",
                    "so_ma": "Số mã",
                    "diem_hieu_chinh_tb": "Điểm hiệu chỉnh TB",
                    "xs_tang_tb": "Xác suất tăng TB %",
                    "data_quality_tb": "Data Quality TB %",
                }
            )
            for col in ("Điểm hiệu chỉnh TB", "Xác suất tăng TB %", "Data Quality TB %"):
                if col in sector_df.columns:
                    sector_df[col] = sector_df[col].map(lambda x: round(float(x), 2))
            sort_cols = [
                c
                for c in ("Điểm hiệu chỉnh TB", "Xác suất tăng TB %", "Data Quality TB %", "Số mã")
                if c in sector_df.columns
            ]
            if sort_cols:
                sector_df = sector_df.sort_values(sort_cols, ascending=[False] * len(sort_cols))
            st.dataframe(sector_df, width="stretch", hide_index=True)
            sector_csv = sector_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ Export Sector Report CSV",
                data=sector_csv,
                file_name=f"sector_calibration_report_{export_tag}_{run_id}.csv",
                mime="text/csv",
                width="content",
            )
            sector_json_payload = {
                "exported_at": export_dt.isoformat(),
                "timezone": "ICT",
                "run_id": run_id,
                "rows": json.loads(sector_df.to_json(orient="records", force_ascii=False)),
            }
            sector_json = json.dumps(sector_json_payload, ensure_ascii=False).encode("utf-8")
            st.download_button(
                "⬇️ Export Sector Report JSON",
                data=sector_json,
                file_name=f"sector_calibration_report_{export_tag}_{run_id}.json",
                mime="application/json",
                width="content",
            )
            if "Ghi chú hiệu chỉnh ngành" in opportunity_df.columns:
                note_df = (
                    opportunity_df[["Ngành con", "Ghi chú hiệu chỉnh ngành"]]
                    .drop_duplicates(subset=["Ngành con"])
                    .rename(columns={"Ngành con": "Ngành", "Ghi chú hiệu chỉnh ngành": "Ghi chú"})
                )
                st.dataframe(note_df, width="stretch", hide_index=True)
                note_csv = note_df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "⬇️ Export Sector Notes CSV",
                    data=note_csv,
                    file_name=f"sector_calibration_notes_{export_tag}_{run_id}.csv",
                    mime="text/csv",
                    width="content",
                )
        else:
            st.caption("Chưa có dữ liệu ngành để dựng report.")
    with st.expander("Giải thích điểm số Finder", expanded=False):
        explain_cols = [
            "Mã",
            "Trạng thái",
            "Catalyst Score",
            "Catalyst Pass",
            "Điểm kỹ thuật",
            "Điểm cơ bản",
            "Điểm cơ hội",
            "Data Quality %",
            "Xác suất tăng 3M %",
            "Khuyến nghị theo profile",
            "Lý do khuyến nghị",
        ]
        explain_df = opportunity_df[[c for c in explain_cols if c in opportunity_df.columns]].head(10).copy()
        st.dataframe(explain_df, width="stretch", hide_index=True)
        st.caption(
            "Điểm cơ hội (hiệu chỉnh ngành) = Điểm kỹ thuật/Điểm cơ bản sau hiệu chỉnh theo ngành con. "
            "Data Quality càng cao thì độ tin cậy khuyến nghị càng tốt."
        )
    csv_bytes = opportunity_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Export Finder CSV",
        data=csv_bytes,
        file_name=f"finder_co_phieu_co_hoi_tang_truong_3_thang_toi_{export_tag}_{run_id}.csv",
        mime="text/csv",
        width="content",
    )
    finder_json_payload = {
        "exported_at": export_dt.isoformat(),
        "timezone": "ICT",
        "run_id": run_id,
        "rows": json.loads(opportunity_df.to_json(orient="records", force_ascii=False)),
    }
    json_bytes = json.dumps(finder_json_payload, ensure_ascii=False).encode("utf-8")
    st.download_button(
        "⬇️ Export Finder JSON",
        data=json_bytes,
        file_name=f"finder_co_phieu_co_hoi_tang_truong_3_thang_toi_{export_tag}_{run_id}.json",
        mime="application/json",
        width="content",
    )
    manifest_payload = {
        "run_id": run_id,
        "exported_at": export_dt.isoformat(),
        "timezone": "ICT",
        "profile": profile,
        "version_stamp": {
            "finder_model_version": "opportunity_finder_v5",
            "app_schema_version": "finder_manifest_v2",
            "dynamic_sector_calibration": bool(dynamic_sector),
            "quick_mode": bool(effective_quick_mode),
            "llm_live": bool(plan["llm_live"]),
            "filters": {
                "min_avg_volume_20": float(min_avg_vol20),
                "min_data_quality_pct": float(min_data_quality),
                "min_catalyst_score": float(min_catalyst_score),
                "only_actionable": bool(only_actionable),
                "universe_limit": int(opp_limit),
            },
        },
        "files": {
            "finder_csv": f"finder_co_phieu_co_hoi_tang_truong_3_thang_toi_{export_tag}_{run_id}.csv",
            "finder_json": f"finder_co_phieu_co_hoi_tang_truong_3_thang_toi_{export_tag}_{run_id}.json",
            "sector_report_csv": f"sector_calibration_report_{export_tag}_{run_id}.csv",
            "sector_report_json": f"sector_calibration_report_{export_tag}_{run_id}.json",
            "sector_notes_csv": f"sector_calibration_notes_{export_tag}_{run_id}.csv",
        },
        "checksums": {
            "finder_csv_sha1": hashlib.sha1(csv_bytes).hexdigest(),
            "finder_json_sha1": hashlib.sha1(json_bytes).hexdigest(),
            "rows": int(len(opportunity_df)),
        },
    }
    manifest_bytes = json.dumps(manifest_payload, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button(
        "⬇️ Export Session Manifest JSON",
        data=manifest_bytes,
        file_name=f"finder_manifest_{export_tag}_{run_id}.json",
        mime="application/json",
        width="content",
    )

