"""
Background jobs for production-like operation.
"""

from __future__ import annotations

import gc
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from core.ai_logic import generate_strategic_report
from core.flow_backtest_service import load_recommendation_artifact
from core.intraday_flow_alert_service import (
    evaluate_flow_alerts,
    mark_flow_alert_dispatched,
    render_alert_message_vi,
)
from core.intraday_flow_journal import append_flow_signals_batch, prune_old_journal_files
from core.intraday_flow_service import (
    FlowConfig,
    IntradayFlowError,
    adjust_signals_with_sector_context,
    analyze_flow,
)
from core.observability import log_timing
from core.product_layer import dispatch_text_notifications, load_secret, process_notification_queue
from core.realtime_guardian import RealtimeGuardian, write_guardian_health_artifact
from core.super_stock_service import Notifier, evaluate_super_stock_signal
from core.universe_rotation import rotation_offset, slice_universe, universe_auto_rotate_enabled
from scrapers.financial_data import (
    fetch_financial_snapshot,
    list_universe_symbols,
    universe_subtype_map,
)
from scrapers.intraday_vn import IntradayDataError, fetch_intraday_ohlcv, is_vn_market_open
from scrapers.portal import PortalDataError, fetch_financial_indicators, fetch_latest_news, fetch_ohlcv_history
from scripts.smart_money_event_sync import (
    _read_existing as _smart_money_read_existing,
    extract_events_from_news as _smart_money_extract_events,
    merge_events as _smart_money_merge_events,
)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


def _runtime_incident_log_path() -> Path:
    return Path(str(os.environ.get("II_RUNTIME_INCIDENT_LOG") or (ROOT / "data" / "reports" / "logs" / "runtime_incidents.jsonl")))


def _log_runtime_incident(scope: str, symbol: str, exc: Exception) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scope": str(scope or "unknown"),
        "symbol": str(symbol or "").strip().upper(),
        "error_type": exc.__class__.__name__,
        "message": str(exc)[:220],
    }
    p = _runtime_incident_log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def prefetch_symbols(
    symbols: list[str],
    profile: str = "growth",
    capital: float = 100_000_000.0,
    *,
    warm_financial_live: bool = False,
) -> dict[str, Any]:
    ok = 0
    fail = 0
    max_symbols = max(5, int(os.environ.get("II_BG_MAX_SYMBOLS", "60") or "60"))
    batch_size = max(2, int(os.environ.get("II_BG_BATCH_SIZE", "8") or "8"))
    considered = 0
    for idx, sym in enumerate(symbols[:max_symbols]):
        considered += 1
        s = (sym or "").strip().upper()
        if not s:
            continue
        snap = fetch_financial_snapshot(s)
        if snap is None:
            fail += 1
            continue
        try:
            # Default to cache-first in scheduler to avoid UI stalls.
            # Khi warm_financial_live=True → force_refresh để ghi CR/CFO/NI vào disk.
            fetch_financial_indicators(
                s,
                fast_mode=not warm_financial_live,
                force_refresh=bool(warm_financial_live),
            )
        except Exception as e:
            logger.warning("prefetch_symbols financial_indicators_failed symbol=%s error=%s", s, e.__class__.__name__)
            _log_runtime_incident("prefetch_financial_indicators", s, e)
        try:
            generate_strategic_report(
                s,
                snap,
                profile=profile,
                total_capital_vnd=float(capital),
                sessions=60,
                news_limit=5,
                enable_llm=False,
                fast_mode=True,
            )
            ok += 1
        except Exception as e:
            logger.warning("prefetch_symbols strategic_report_failed symbol=%s error=%s", s, e.__class__.__name__)
            _log_runtime_incident("prefetch_strategic_report", s, e)
            fail += 1
        if (idx + 1) % batch_size == 0:
            # Giải phóng bộ nhớ trung gian sau mỗi batch để phù hợp VPS RAM thấp.
            gc.collect()
    return {"ok": ok, "fail": fail, "total": ok + fail, "considered": considered, "batch_size": batch_size, "max_symbols": max_symbols}


def run_background_cycle(
    *,
    universe_limit: int = 30,
    watchlist: list[str] | None = None,
    queue_jobs: int = 30,
    warm_financial_live: bool = False,
    user_id: str = "default_user",
) -> dict[str, Any]:
    watch = [x.strip().upper() for x in (watchlist or ["FPT", "HPG", "VNM"]) if x.strip()]
    lim = max(0, int(universe_limit))
    full = list_universe_symbols(limit=None)
    rd = date.today().toordinal()
    off = rotation_offset(total=len(full), window=max(1, lim), key="bg_prefetch", day_ordinal=rd) if universe_auto_rotate_enabled() and lim > 0 else 0
    uni = slice_universe(full, offset=off, limit=lim) if lim > 0 else []
    merged: list[str] = []
    for s in watch + uni:
        if s not in merged:
            merged.append(s)
    try:
        prefetch_stat = prefetch_symbols(
            merged,
            profile="growth",
            capital=100_000_000.0,
            warm_financial_live=warm_financial_live,
        )
    except Exception as e:
        _log_runtime_incident("run_background_cycle.prefetch", "", e)
        prefetch_stat = {"ok": 0, "fail": 0, "total": 0, "error": e.__class__.__name__}
    try:
        super_stat = _run_super_stock_cycle(merged, user_id=user_id)
    except Exception as e:
        _log_runtime_incident("run_background_cycle.super_stock", "", e)
        super_stat = {"checked": 0, "passed": 0, "notified": 0, "failures": 1, "error": e.__class__.__name__}
    try:
        flow_stat = _run_intraday_flow_cycle(merged, user_id=user_id)
    except Exception as e:
        _log_runtime_incident("run_background_cycle.intraday_flow", "", e)
        flow_stat = {"checked": 0, "alerts": 0, "notified": 0, "failures": 1, "error": e.__class__.__name__}
    try:
        seed_stat = _run_smart_money_seed_cycle(merged)
    except Exception as e:
        _log_runtime_incident("run_background_cycle.smart_money_seed", "", e)
        seed_stat = {"checked": 0, "ingested": 0, "stored": 0, "failures": 1, "error": e.__class__.__name__}
    try:
        queue_stat = process_notification_queue(max_jobs=max(1, int(queue_jobs)))
    except Exception as e:
        _log_runtime_incident("run_background_cycle.notification_queue", "", e)
        queue_stat = {"sent": 0, "failed": 1, "retried": 0, "processed": 0, "error": e.__class__.__name__}
    return {
        "prefetch": prefetch_stat,
        "super_stock": super_stat,
        "intraday_flow": flow_stat,
        "smart_money_seed": seed_stat,
        "queue": queue_stat,
    }


def _run_super_stock_cycle(symbols: list[str], *, user_id: str = "default_user") -> dict[str, Any]:
    """Quét tín hiệu Siêu cổ phiếu theo 3 điều kiện và gửi Telegram ngay khi đạt."""
    started_at = perf_counter()
    checked = 0
    passed = 0
    notified = 0
    failures = 0
    suppressed = 0
    red_flag_hits = 0
    cooldown_minutes = max(10, int(os.environ.get("II_GUARDIAN_COOLDOWN_MINUTES", "180") or "180"))
    guardian_state_path = Path(str(os.environ.get("II_GUARDIAN_STATE_PATH") or (ROOT / "data" / "runtime_guardian_state.json")))
    guardian = RealtimeGuardian(guardian_state_path, cooldown_minutes=cooldown_minutes)
    notifier = Notifier(
        load_secret_func=load_secret,
        dispatch_text_notifications_func=dispatch_text_notifications,
        user_id=user_id,
    )
    selected: list[str] = []
    for sym in symbols[:30]:
        checked += 1
        try:
            signal = evaluate_super_stock_signal(sym)
            if not signal:
                continue
            if not signal.passed:
                continue
            passed += 1
            if signal.red_flags:
                red_flag_hits += 1
            selected.append(signal.symbol)
            decision = guardian.decide(signal)
            if not decision.allow_notify:
                suppressed += 1
                continue
            stat = notifier.notify_super_stock(signal)
            if int(stat.get("sent") or 0) > 0:
                notified += 1
                guardian.mark_notified(signal, decision.signal_key, status="sent")
            else:
                failures += int(stat.get("failed") or 0)
                guardian.mark_notified(signal, decision.signal_key, status="failed")
        except Exception as e:
            logger.warning("super_stock_cycle_failed symbol=%s error=%s", sym, e.__class__.__name__)
            _log_runtime_incident("super_stock_cycle", sym, e)
            failures += 1
    guardian.save()
    health_payload = {
        **guardian.build_health_summary(),
        "checked": int(checked),
        "passed": int(passed),
        "notified": int(notified),
        "suppressed_cooldown": int(suppressed),
        "failures": int(failures),
        "red_flag_hits": int(red_flag_hits),
        "symbols": selected[:10],
    }
    artifact_path = Path(
        str(os.environ.get("II_GUARDIAN_HEALTH_PATH") or (ROOT / "artifacts" / "operations" / "runtime_guardian_health.json"))
    )
    write_guardian_health_artifact(artifact_path, health_payload)
    log_timing(
        "background_jobs.super_stock_cycle",
        (perf_counter() - started_at) * 1000.0,
        checked=int(checked),
        passed=int(passed),
        notified=int(notified),
        suppressed_cooldown=int(suppressed),
        red_flag_hits=int(red_flag_hits),
        failures=int(failures),
        symbols=",".join(selected[:10]),
    )
    return {
        "checked": checked,
        "passed": passed,
        "notified": notified,
        "suppressed_cooldown": suppressed,
        "failures": failures,
        "red_flag_hits": red_flag_hits,
        "symbols": selected[:10],
    }


_FLOW_RECOMMENDATION_SOURCE: dict[str, Any] = {"source": "default", "value": 6.0, "path": None}


def _flow_recommendation_source_snapshot() -> dict[str, Any]:
    """Snapshot nguồn ``min_intensity`` cuối cùng đã giải mã — dùng cho audit/health.

    Có 3 nguồn theo thứ tự ưu tiên:

    1. ``II_FLOW_MIN_INTENSITY`` env (explicit override của user/op).
    2. Artifact ``recommendation_latest.json`` (do CLI backtest sinh ra)
       khi ``II_FLOW_USE_BACKTEST_RECOMMENDATION=1``.
    3. Default 6.0.
    """
    return dict(_FLOW_RECOMMENDATION_SOURCE)


def _flow_min_intensity_env() -> float:
    """Trả về ``min_intensity`` runtime — auto-tune từ backtest nếu enabled.

    Priority (cao → thấp):
    1. Env ``II_FLOW_MIN_INTENSITY`` set explicit (giá trị > 0).
    2. Nếu ``II_FLOW_USE_BACKTEST_RECOMMENDATION=1`` và file recommendation
       còn fresh (TTL từ ``II_FLOW_RECOMMENDATION_TTL_DAYS``, default 14):
       dùng số empirical đó.
    3. Default 6.0.

    Mọi nguồn đều clamp về ``[1.0, 10.0]`` để tránh vô tình tắt detector
    hoặc đặt ngưỡng không bao giờ đạt được.
    """
    raw = (os.environ.get("II_FLOW_MIN_INTENSITY") or "").strip()
    if raw:
        try:
            v = float(raw)
        except ValueError:
            v = 6.0
        clamped = max(1.0, min(10.0, v))
        _FLOW_RECOMMENDATION_SOURCE.update({"source": "env", "value": clamped, "path": None})
        return clamped

    use_backtest = (os.environ.get("II_FLOW_USE_BACKTEST_RECOMMENDATION") or "0").strip().lower()
    if use_backtest in ("1", "true", "yes", "on"):
        path_raw = os.environ.get("II_FLOW_RECOMMENDATION_PATH")
        path = Path(path_raw) if path_raw else None
        try:
            ttl = int(os.environ.get("II_FLOW_RECOMMENDATION_TTL_DAYS") or "14")
        except ValueError:
            ttl = 14
        payload = load_recommendation_artifact(path=path, max_age_days=max(1, ttl))
        if payload is not None:
            try:
                v = float(payload.get("recommended_min_intensity") or 6.0)
            except (TypeError, ValueError):
                v = 6.0
            clamped = max(1.0, min(10.0, v))
            _FLOW_RECOMMENDATION_SOURCE.update(
                {
                    "source": "backtest_recommendation",
                    "value": clamped,
                    "path": str(path) if path else None,
                    "horizon_days": payload.get("horizon_days"),
                    "generated_at_utc": payload.get("generated_at_utc"),
                }
            )
            return clamped

    _FLOW_RECOMMENDATION_SOURCE.update({"source": "default", "value": 6.0, "path": None})
    return 6.0


def _flow_max_symbols_env() -> int:
    raw = (os.environ.get("II_FLOW_MAX_SYMBOLS") or "").strip()
    try:
        v = int(raw) if raw else 30
    except ValueError:
        v = 30
    return max(0, min(120, v))


def _flow_sessions_env() -> int:
    raw = (os.environ.get("II_FLOW_SESSIONS") or "").strip()
    try:
        v = int(raw) if raw else 200
    except ValueError:
        v = 200
    return max(60, min(800, v))


def _flow_resolution_env() -> str:
    """Đọc env ``II_FLOW_RESOLUTION``.

    Hợp lệ: ``D`` / ``DAILY`` (mặc định, dùng ``fetch_ohlcv_history``) hoặc
    ``1`` / ``3`` / ``5`` / ``15`` / ``30`` / ``60`` (phút, dùng intraday
    miễn phí VNDirect→TCBS). Resolution không hợp lệ tự fallback về ``D``.
    """
    raw = (os.environ.get("II_FLOW_RESOLUTION") or "D").strip().upper()
    if raw in ("D", "DAILY", "1D"):
        return "D"
    if raw in ("1", "3", "5", "15", "30", "60"):
        return raw
    return "D"


def _flow_primary_source_env() -> str:
    raw = (os.environ.get("II_FLOW_PRIMARY_SOURCE") or "vndirect").strip().lower()
    if raw not in ("vndirect", "tcbs"):
        return "vndirect"
    return raw


def _flow_skip_outside_market_hours() -> bool:
    raw = (os.environ.get("II_FLOW_SKIP_OUTSIDE_HOURS") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _sector_adjustment_enabled() -> bool:
    """Bật/tắt sector-aware adjustment ở cycle background (default ON)."""
    raw = (os.environ.get("II_FLOW_SECTOR_ADJUST_ENABLED") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _sector_alignment_boost() -> float:
    try:
        v = float(os.environ.get("II_FLOW_SECTOR_ALIGNMENT_BOOST") or "1.10")
    except (TypeError, ValueError):
        v = 1.10
    return max(1.0, min(1.5, v))


def _sector_divergence_penalty() -> float:
    try:
        v = float(os.environ.get("II_FLOW_SECTOR_DIVERGENCE_PENALTY") or "0.85")
    except (TypeError, ValueError):
        v = 0.85
    return max(0.5, min(1.0, v))


def _load_flow_ohlcv(
    symbol: str,
    *,
    sessions: int,
    resolution: str,
    primary_source: str,
) -> pd.DataFrame:
    """Lấy OHLCV cho flow analyzer theo resolution.

    - ``resolution == "D"``: dùng ``fetch_ohlcv_history`` (cache/store/SLA chain
      của portal).
    - Khác: dùng ``fetch_intraday_ohlcv`` (VNDirect → TCBS fallback, miễn phí).
    """
    if resolution == "D":
        return fetch_ohlcv_history(symbol, sessions=sessions)
    return fetch_intraday_ohlcv(
        symbol,
        resolution=resolution,
        lookback_bars=sessions,
        primary_source=primary_source,
    )


def _run_intraday_flow_cycle(symbols: list[str], *, user_id: str = "default_user") -> dict[str, Any]:
    """Quét tín hiệu dòng tiền lớn (Tier 1) và đẩy alert qua Telegram với cooldown.

    Tách guardian state riêng (`flow_guardian_state.json`) để không xung đột cooldown
    với super_stock cycle. Cấu hình qua env:

    - ``II_FLOW_MIN_INTENSITY`` (default 6.0)
    - ``II_FLOW_MAX_SYMBOLS`` (default 30, 0 để tắt)
    - ``II_FLOW_SESSIONS`` (default 200 phiên/nến)
    - ``II_FLOW_RESOLUTION`` (default ``D``; ``1``/``5``/``15``/``30``/``60``
      bật chế độ intraday miễn phí VNDirect → TCBS)
    - ``II_FLOW_PRIMARY_SOURCE`` (``vndirect`` | ``tcbs``)
    - ``II_FLOW_SKIP_OUTSIDE_HOURS`` (default ``1``; chỉ áp dụng khi resolution
      là intraday — tránh ping API lúc sàn đóng cửa)
    """
    started_at = perf_counter()
    max_symbols = _flow_max_symbols_env()
    if max_symbols == 0:
        return {
            "checked": 0,
            "alerts": 0,
            "notified": 0,
            "failures": 0,
            "suppressed": 0,
            "skipped_no_data": 0,
        }

    resolution = _flow_resolution_env()
    primary_source = _flow_primary_source_env()
    timeframe_label = "1D" if resolution == "D" else f"{resolution}m"
    if resolution != "D" and _flow_skip_outside_market_hours() and not is_vn_market_open():
        return {
            "checked": 0,
            "alerts": 0,
            "notified": 0,
            "failures": 0,
            "suppressed": 0,
            "skipped_no_data": 0,
            "skipped_reason": "market_closed",
            "resolution": resolution,
        }

    min_intensity = _flow_min_intensity_env()
    sessions = _flow_sessions_env()
    cooldown_minutes = max(10, int(os.environ.get("II_FLOW_COOLDOWN_MINUTES", "180") or "180"))
    guardian_state_path = Path(
        str(os.environ.get("II_FLOW_GUARDIAN_STATE_PATH") or (ROOT / "data" / "flow_guardian_state.json"))
    )
    guardian = RealtimeGuardian(guardian_state_path, cooldown_minutes=cooldown_minutes)

    config = FlowConfig(rolling_window=min(180, max(60, sessions // 2)), min_rows=30)
    signals_map = {}
    checked = 0
    failures = 0
    skipped_no_data = 0
    notified = 0
    suppressed = 0

    sector_contexts: dict[str, dict[str, Any]] = {}
    try:
        subtype_map = universe_subtype_map() or {}
    except Exception as exc:  # noqa: BLE001
        logger.info("intraday_flow_cycle_subtype_map_failed error=%s", exc.__class__.__name__)
        subtype_map = {}

    for sym in symbols[:max_symbols]:
        s = (sym or "").strip().upper()
        if not s:
            continue
        checked += 1
        try:
            ohlcv = _load_flow_ohlcv(
                s,
                sessions=sessions,
                resolution=resolution,
                primary_source=primary_source,
            )
        except (PortalDataError, IntradayDataError):
            skipped_no_data += 1
            continue
        except Exception as e:
            failures += 1
            logger.warning("intraday_flow_cycle_ohlcv_failed symbol=%s error=%s", s, e.__class__.__name__)
            _log_runtime_incident("intraday_flow_cycle.ohlcv", s, e)
            continue
        if ohlcv is None or len(ohlcv) < config.min_rows:
            skipped_no_data += 1
            continue
        subtype = str(subtype_map.get(s) or "").strip()
        ctx_for_sym: dict[str, Any] = {}
        if subtype and subtype.lower() not in ("other", "unknown", ""):
            ctx_for_sym["industry_subtype"] = subtype
        if ctx_for_sym:
            sector_contexts[s] = ctx_for_sym
        try:
            signal = analyze_flow(
                ohlcv,
                symbol=s,
                config=config,
                timeframe=timeframe_label,
                context=ctx_for_sym or None,
            )
        except IntradayFlowError:
            skipped_no_data += 1
            continue
        except Exception as e:
            failures += 1
            logger.warning("intraday_flow_cycle_analyze_failed symbol=%s error=%s", s, e.__class__.__name__)
            _log_runtime_incident("intraday_flow_cycle.analyze", s, e)
            continue
        signals_map[s] = signal

    # Pass 2 — sector adjustment (loại "lẻ loi cơ cấu", boost sóng ngành).
    sector_adjustment_enabled = _sector_adjustment_enabled()
    sector_adjusted_count = 0
    if sector_adjustment_enabled and signals_map:
        try:
            before = {sym: sig.intensity_score for sym, sig in signals_map.items()}
            signals_map = adjust_signals_with_sector_context(
                signals_map,
                contexts=sector_contexts,
                alignment_boost=_sector_alignment_boost(),
                divergence_penalty=_sector_divergence_penalty(),
            )
            sector_adjusted_count = sum(
                1
                for sym in signals_map
                if abs(signals_map[sym].intensity_score - before.get(sym, 0.0)) > 1e-6
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "intraday_flow_cycle_sector_adjust_failed error=%s",
                exc.__class__.__name__,
            )
            _log_runtime_incident("intraday_flow_cycle.sector_adjust", "", exc)

    if signals_map:
        try:
            append_flow_signals_batch(
                list(signals_map.values()),
                extra_context={
                    "phase": "background_cycle",
                    "resolution": resolution,
                    "primary_source": primary_source,
                    "min_intensity": float(min_intensity),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("flow_journal_append_failed error=%s", exc.__class__.__name__)
            _log_runtime_incident("intraday_flow_cycle.journal", "", exc)
        if int(os.environ.get("II_FLOW_JOURNAL_PRUNE_PER_CYCLE", "0") or "0"):
            try:
                prune_old_journal_files()
            except Exception as exc:  # noqa: BLE001
                logger.info("flow_journal_prune_failed error=%s", exc.__class__.__name__)

    decisions = evaluate_flow_alerts(
        signals_map,
        guardian,
        min_intensity=min_intensity,
        require_big_boy=True,
    )
    alerts = len(decisions)

    token = load_secret(user_id, "telegram_bot_token", "")
    chat_id = load_secret(user_id, "telegram_chat_id", "")
    can_dispatch = bool(token and chat_id)

    notified_symbols: list[str] = []
    for decision in decisions:
        if not decision.allow_notify:
            suppressed += 1
            continue
        if not can_dispatch:
            continue
        try:
            text = render_alert_message_vi(decision.payload)
            stat = dispatch_text_notifications(
                text,
                telegram_bot_token=token,
                telegram_chat_id=chat_id,
            )
            sent_n = int(stat.get("sent") or 0) if isinstance(stat, dict) else 0
            failed_n = int(stat.get("failed") or 0) if isinstance(stat, dict) else 0
            if sent_n > 0:
                notified += 1
                notified_symbols.append(decision.payload.symbol)
                mark_flow_alert_dispatched(guardian, decision, status="sent")
            else:
                failures += max(1, failed_n)
                mark_flow_alert_dispatched(guardian, decision, status="failed")
        except Exception as e:
            failures += 1
            logger.warning(
                "intraday_flow_cycle_dispatch_failed symbol=%s error=%s",
                decision.payload.symbol,
                e.__class__.__name__,
            )
            _log_runtime_incident("intraday_flow_cycle.dispatch", decision.payload.symbol, e)

    guardian.save()
    health_payload = {
        **guardian.build_health_summary(),
        "checked": int(checked),
        "alerts_eligible": int(alerts),
        "notified": int(notified),
        "suppressed_cooldown": int(suppressed),
        "skipped_no_data": int(skipped_no_data),
        "failures": int(failures),
        "min_intensity": float(min_intensity),
        "min_intensity_source": _flow_recommendation_source_snapshot(),
        "symbols": notified_symbols[:10],
        "dispatch_enabled": bool(can_dispatch),
        "resolution": resolution,
        "primary_source": primary_source,
        "sector_adjust_enabled": bool(sector_adjustment_enabled),
        "sector_adjusted_count": int(sector_adjusted_count),
    }
    artifact_path = Path(
        str(
            os.environ.get("II_FLOW_GUARDIAN_HEALTH_PATH")
            or (ROOT / "artifacts" / "operations" / "intraday_flow_guardian_health.json")
        )
    )
    write_guardian_health_artifact(artifact_path, health_payload)
    log_timing(
        "background_jobs.intraday_flow_cycle",
        (perf_counter() - started_at) * 1000.0,
        checked=int(checked),
        alerts=int(alerts),
        notified=int(notified),
        suppressed=int(suppressed),
        skipped_no_data=int(skipped_no_data),
        failures=int(failures),
        symbols=",".join(notified_symbols[:10]),
    )
    return {
        "checked": checked,
        "alerts": alerts,
        "notified": notified,
        "suppressed": suppressed,
        "skipped_no_data": skipped_no_data,
        "failures": failures,
        "min_intensity": min_intensity,
        "symbols": notified_symbols[:10],
        "dispatch_enabled": can_dispatch,
        "resolution": resolution,
        "primary_source": primary_source,
        "sector_adjust_enabled": bool(sector_adjustment_enabled),
        "sector_adjusted_count": int(sector_adjusted_count),
    }


def _smart_money_seed_enabled() -> bool:
    raw = (os.environ.get("II_SMART_MONEY_SEED_ENABLED") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _smart_money_seed_news_limit() -> int:
    try:
        v = int(os.environ.get("II_SMART_MONEY_SEED_NEWS_LIMIT") or "20")
    except ValueError:
        v = 20
    return max(1, min(80, v))


def _smart_money_seed_max_per_symbol() -> int:
    try:
        v = int(os.environ.get("II_SMART_MONEY_SEED_MAX_PER_SYMBOL") or "200")
    except ValueError:
        v = 200
    return max(10, min(2000, v))


def _smart_money_seed_state_path() -> Path:
    return Path(
        str(os.environ.get("II_SMART_MONEY_SEED_STATE_PATH")
            or (ROOT / "data" / "runtime" / "smart_money_seed_last_run.txt"))
    )


def _smart_money_seed_output_path() -> Path:
    return Path(
        str(os.environ.get("II_SMART_MONEY_SEED_OUTPUT_PATH")
            or (ROOT / "data" / "smart_money_events.json"))
    )


def _smart_money_seed_due(state_path: Path, *, today: date | None = None) -> bool:
    """Trả về True nếu chu kỳ seed hôm nay chưa chạy.

    State được lưu plain-text dạng ``YYYY-MM-DD`` để dễ debug bằng tay.
    """
    today_str = (today or datetime.now(timezone.utc).date()).isoformat()
    if not state_path.exists():
        return True
    try:
        last = state_path.read_text(encoding="utf-8").strip()
    except OSError:
        return True
    return last != today_str


def _smart_money_seed_mark_done(state_path: Path, *, today: date | None = None) -> None:
    today_str = (today or datetime.now(timezone.utc).date()).isoformat()
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(today_str, encoding="utf-8")
    except OSError as exc:
        logger.warning("smart_money_seed_state_write_failed error=%s", exc.__class__.__name__)


def _run_smart_money_seed_cycle(
    symbols: list[str],
    *,
    news_loader: Any = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Seed/refresh ``data/smart_money_events.json`` mỗi ngày 1 lần.

    Lấy tin tức mới nhất qua ``fetch_latest_news`` (free; CafeF/VietStock chain
    qua portal scraper), parse thành sự kiện smart money rồi merge với JSON
    hiện có. Có gating theo file timestamp để tránh gọi nhiều lần/ngày.

    Tunables (env):
    - ``II_SMART_MONEY_SEED_ENABLED`` (default ``1``; ``0`` để tắt)
    - ``II_SMART_MONEY_SEED_NEWS_LIMIT`` (default 20 tin/mã)
    - ``II_SMART_MONEY_SEED_MAX_PER_SYMBOL`` (default 200, giới hạn JSON)
    - ``II_SMART_MONEY_SEED_STATE_PATH`` (file timestamp gating)
    - ``II_SMART_MONEY_SEED_OUTPUT_PATH`` (override JSON output)
    """
    if not _smart_money_seed_enabled():
        return {"checked": 0, "ingested": 0, "stored": 0, "skipped_reason": "disabled"}

    state_path = _smart_money_seed_state_path()
    if not _smart_money_seed_due(state_path, today=today):
        return {"checked": 0, "ingested": 0, "stored": 0, "skipped_reason": "already_run_today"}

    started_at = perf_counter()
    loader = news_loader or fetch_latest_news
    news_limit = _smart_money_seed_news_limit()
    max_per_symbol = _smart_money_seed_max_per_symbol()
    out_path = _smart_money_seed_output_path()

    incoming: list[dict[str, Any]] = []
    checked = 0
    failures = 0
    for sym in symbols[:60]:
        s = (sym or "").strip().upper()
        if not s:
            continue
        checked += 1
        try:
            rows = loader(s, limit=news_limit)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.info("smart_money_seed_news_failed symbol=%s error=%s", s, exc.__class__.__name__)
            _log_runtime_incident("smart_money_seed.news", s, exc)
            continue
        try:
            extracted = _smart_money_extract_events(s, rows or [])
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.info("smart_money_seed_parse_failed symbol=%s error=%s", s, exc.__class__.__name__)
            _log_runtime_incident("smart_money_seed.parse", s, exc)
            continue
        incoming.extend(extracted)

    existing = _smart_money_read_existing(out_path)
    merged = _smart_money_merge_events(existing, incoming, max_per_symbol=max_per_symbol)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        _smart_money_seed_mark_done(state_path, today=today)
    except OSError as exc:
        failures += 1
        logger.warning("smart_money_seed_write_failed error=%s", exc.__class__.__name__)
        _log_runtime_incident("smart_money_seed.write", "", exc)

    log_timing(
        "background_jobs.smart_money_seed_cycle",
        (perf_counter() - started_at) * 1000.0,
        checked=int(checked),
        ingested=int(len(incoming)),
        stored=int(len(merged)),
        failures=int(failures),
    )
    return {
        "checked": checked,
        "ingested": len(incoming),
        "stored": len(merged),
        "failures": failures,
        "out_path": str(out_path),
        "news_limit": news_limit,
    }
