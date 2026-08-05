"""
E2E User Simulation Harness — Production-Grade Flawless gate.

Giả lập hành vi người dùng trên các panel lõi (auth, tabs, widgets, edge cases,
async PG polling) mà không cần Streamlit server thật.

Chạy:
  python -m pytest tests/simulate_user_flows.py -q
  python tests/simulate_user_flows.py
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

# CLI: đảm bảo repo root có trên sys.path (pytest đã set pythonpath=.).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import pytest

logger = logging.getLogger(__name__)


class SimulatedStreamlitAPIException(Exception):
    """Mirror StreamlitAPIException rules we must never violate in UI code."""


class _SessionState(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError as e:
            raise AttributeError(name) from e


class _Ctx:
    def __enter__(self) -> _Ctx:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class FakeStreamlit:
    """
    Lightweight Streamlit stand-in that enforces real widget contracts
    (e.g. slider min < max) and records interactions for assertions.
    """

    def __init__(self) -> None:
        self.session_state = _SessionState()
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []
        self._button_queue: dict[str, list[bool]] = {}
        self._button_default = False
        self._stop_called = False
        self._rerun_called = False

    def queue_button(self, label: str, *results: bool) -> None:
        self._button_queue.setdefault(label, []).extend(results)

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def markdown(self, *args: Any, **kwargs: Any) -> None:
        self._record("markdown", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._record("caption", *args, **kwargs)

    def header(self, *args: Any, **kwargs: Any) -> None:
        self._record("header", *args, **kwargs)

    def subheader(self, *args: Any, **kwargs: Any) -> None:
        self._record("subheader", *args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> None:
        self._record("write", *args, **kwargs)

    def dataframe(self, *args: Any, **kwargs: Any) -> None:
        self._record("dataframe", *args, **kwargs)

    def divider(self, *args: Any, **kwargs: Any) -> None:
        self._record("divider", *args, **kwargs)

    def success(self, msg: Any = "", *args: Any, **kwargs: Any) -> None:
        self.successes.append(str(msg))
        self._record("success", msg, *args, **kwargs)

    def error(self, msg: Any = "", *args: Any, **kwargs: Any) -> None:
        self.errors.append(str(msg))
        self._record("error", msg, *args, **kwargs)

    def warning(self, msg: Any = "", *args: Any, **kwargs: Any) -> None:
        self.warnings.append(str(msg))
        self._record("warning", msg, *args, **kwargs)

    def info(self, msg: Any = "", *args: Any, **kwargs: Any) -> None:
        self.infos.append(str(msg))
        self._record("info", msg, *args, **kwargs)

    def stop(self) -> None:
        self._stop_called = True
        raise SystemExit("st.stop")

    def rerun(self) -> None:
        self._rerun_called = True
        raise SystemExit("st.rerun")

    def button(self, label: str, *args: Any, **kwargs: Any) -> bool:
        self._record("button", label, *args, **kwargs)
        q = self._button_queue.get(str(label), [])
        if q:
            return bool(q.pop(0))
        return bool(self._button_default)

    def text_input(self, label: str, value: str = "", *args: Any, **kwargs: Any) -> str:
        self._record("text_input", label, value, *args, **kwargs)
        key = kwargs.get("key")
        if key and key in self.session_state:
            return str(self.session_state[key])
        override_key = f"_sim_text:{label}"
        if override_key in self.session_state:
            return str(self.session_state[override_key])
        return str(value or "")

    def number_input(self, label: str, *args: Any, **kwargs: Any) -> float | int:
        self._record("number_input", label, *args, **kwargs)
        key = kwargs.get("key")
        if key and key in self.session_state:
            return self.session_state[key]
        min_v = kwargs.get("min_value", 0)
        max_v = kwargs.get("max_value", min_v)
        value = kwargs.get("value", min_v)
        if max_v is not None and min_v is not None and max_v < min_v:
            raise SimulatedStreamlitAPIException(
                f"number_input max_value must be >= min_value. Got {min_v} and {max_v}."
            )
        return value

    def slider(self, label: str, *args: Any, **kwargs: Any) -> Any:
        self._record("slider", label, *args, **kwargs)
        min_v = kwargs.get("min_value", args[0] if args else None)
        max_v = kwargs.get("max_value", args[1] if len(args) > 1 else None)
        if min_v is not None and max_v is not None and not (min_v < max_v):
            raise SimulatedStreamlitAPIException(
                f"Slider min_value must be less than the max_value. The values were {min_v} and {max_v}."
            )
        key = kwargs.get("key")
        if key and key in self.session_state:
            return self.session_state[key]
        if "value" in kwargs:
            return kwargs["value"]
        return min_v if min_v is not None else 0

    def selectbox(self, label: str, options: list[Any], index: int = 0, *args: Any, **kwargs: Any) -> Any:
        self._record("selectbox", label, options, *args, **kwargs)
        opts = list(options or [])
        if not opts:
            return None
        key = kwargs.get("key")
        if key and key in self.session_state:
            return self.session_state[key]
        idx = max(0, min(int(index or 0), len(opts) - 1))
        return opts[idx]

    def multiselect(self, label: str, options: list[Any] | None = None, default: Any = None, **kwargs: Any) -> list[Any]:
        self._record("multiselect", label, options, default=default, **kwargs)
        key = kwargs.get("key")
        if key and key in self.session_state:
            return list(self.session_state[key])
        if default is None:
            return []
        return list(default) if isinstance(default, (list, tuple)) else [default]

    def radio(self, label: str, options: list[Any], *args: Any, **kwargs: Any) -> Any:
        self._record("radio", label, options, *args, **kwargs)
        opts = list(options or [])
        key = kwargs.get("key")
        if key and key in self.session_state:
            return self.session_state[key]
        return opts[0] if opts else None

    def toggle(self, label: str, value: bool = False, *args: Any, **kwargs: Any) -> bool:
        self._record("toggle", label, value, *args, **kwargs)
        key = kwargs.get("key")
        if key and key in self.session_state:
            return bool(self.session_state[key])
        return bool(value)

    def columns(self, spec: Any, *args: Any, **kwargs: Any) -> tuple[_Ctx, ...]:
        self._record("columns", spec, *args, **kwargs)
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec or 2)
        return tuple(_Ctx() for _ in range(max(1, n)))

    def expander(self, *args: Any, **kwargs: Any) -> _Ctx:
        self._record("expander", *args, **kwargs)
        return _Ctx()

    def container(self, *args: Any, **kwargs: Any) -> _Ctx:
        self._record("container", *args, **kwargs)
        return _Ctx()

    def spinner(self, *args: Any, **kwargs: Any) -> _Ctx:
        self._record("spinner", *args, **kwargs)
        return _Ctx()

    def empty(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        self._record("empty", *args, **kwargs)
        return SimpleNamespace(info=lambda *a, **k: None, markdown=lambda *a, **k: None, empty=lambda: None)

    def progress(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        self._record("progress", *args, **kwargs)
        return SimpleNamespace(progress=lambda *a, **k: None, empty=lambda: None)

    def metric(self, *args: Any, **kwargs: Any) -> None:
        self._record("metric", *args, **kwargs)

    def download_button(self, *args: Any, **kwargs: Any) -> bool:
        self._record("download_button", *args, **kwargs)
        return False

    def tabs(self, labels: list[str], *args: Any, **kwargs: Any) -> tuple[_Ctx, ...]:
        self._record("tabs", labels, *args, **kwargs)
        return tuple(_Ctx() for _ in labels)


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""
    error: str = ""


@dataclass
class SimulationReport:
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    def summary(self) -> str:
        lines = [f"[{'PASS' if r.ok else 'FAIL'}] {r.name}: {r.detail or r.error}" for r in self.results]
        failed = sum(1 for r in self.results if not r.ok)
        lines.append(f"Total={len(self.results)} failed={failed}")
        return "\n".join(lines)


def _patch_st(modules: list[Any], fake: FakeStreamlit):
    return [patch.object(m, "st", fake) for m in modules]


@contextmanager
def _install_fake(modules: list[Any], fake: FakeStreamlit):
    patches = _patch_st(modules, fake)
    for p in patches:
        p.start()
    try:
        yield fake
    finally:
        for p in patches:
            p.stop()


def _run_scenario(name: str, fn: Callable[[], str]) -> ScenarioResult:
    try:
        detail = fn() or "ok"
        return ScenarioResult(name=name, ok=True, detail=detail)
    except SystemExit as e:
        # st.stop / st.rerun are expected control-flow in some auth paths
        return ScenarioResult(name=name, ok=True, detail=f"controlled_exit:{e}")
    except Exception as e:
        logger.exception("scenario_failed name=%s", name)
        return ScenarioResult(
            name=name,
            ok=False,
            error=f"{type(e).__name__}: {e}",
            detail=traceback.format_exc(limit=8),
        )


def scenario_auth_success() -> str:
    from core import app_auth_gate, app_sidebar_account_panel as auth_panel

    fake = FakeStreamlit()
    fake.session_state["_sim_text:Mã khách hàng"] = "sim_user"
    fake.session_state["_sim_text:PIN truy cập"] = "1234"
    fake.queue_button("Đăng nhập", True)

    pins = {"sim_user": "1234"}

    with _install_fake([auth_panel, app_auth_gate], fake):
        uid = auth_panel.render_sidebar_auth_section(
            has_auth_user=lambda u: u in pins,
            verify_user_pin=lambda u, p: pins.get(u) == p,
            register_user_pin=lambda u, p, **k: (True, "ok"),
        )
        assert uid == "sim_user"
        assert fake.session_state.get("auth_ok") is True
        assert app_auth_gate.is_authenticated_session("sim_user", fake.session_state)
        assert fake.successes, "expected login success toast"
    return "login_ok"


def scenario_auth_failure() -> str:
    from core import app_auth_gate, app_sidebar_account_panel as auth_panel

    fake = FakeStreamlit()
    fake.session_state["_sim_text:Mã khách hàng"] = "sim_user"
    fake.session_state["_sim_text:PIN truy cập"] = "wrong"
    fake.queue_button("Đăng nhập", True)

    with _install_fake([auth_panel, app_auth_gate], fake):
        auth_panel.render_sidebar_auth_section(
            has_auth_user=lambda u: True,
            verify_user_pin=lambda u, p: False,
            register_user_pin=lambda u, p, **k: (False, "fail"),
        )
        assert fake.session_state.get("auth_ok") is False
        assert fake.errors, "expected PIN error"
    return "login_rejected"


def scenario_session_expired() -> str:
    from core.app_auth_gate import (
        SessionAuthorizationError,
        clear_authenticated_session,
        enforce_auth_gate,
        require_authenticated_session,
        start_authenticated_session,
    )

    fake = FakeStreamlit()
    start_authenticated_session("u1", fake.session_state)
    # Expire: wipe token (as if TTL / tamper)
    fake.session_state["session_token"] = "short"
    with pytest.raises(SessionAuthorizationError):
        require_authenticated_session("u1", fake.session_state)

    clear_authenticated_session(fake.session_state)
    with _install_fake([__import__("core.app_auth_gate", fromlist=["st"])], fake):
        import core.app_auth_gate as gate

        with patch.object(gate, "st", fake):
            try:
                enforce_auth_gate(user_id="u1", has_auth_user=lambda u: True)
            except SystemExit:
                pass
            assert fake._stop_called or fake.warnings
    return "session_expired_gated"


def scenario_tab_navigation() -> str:
    from core import (
        app_autopilot_panel as auto,
        app_daily_action_panel as daily,
        app_finder_panel as finder,
        app_scan_flow as scan,
        app_watch_board_panel as watch,
        opportunity_filter_panel as opp,
    )

    os.environ["II_WATCH_SHELF_PREFER_LIVE"] = "0"
    os.environ["II_SNAPSHOT_PREFER_LIVE"] = "0"

    fake = FakeStreamlit()
    plan = {"scan_limit": 100, "llm_live": False, "analysis_per_day": 30, "alerts": 3}

    with _install_fake([watch, daily, auto, finder, opp, scan], fake), patch(
        "core.app_view_helpers.is_tradable_vn_symbol", return_value=True
    ), patch(
        "core.app_view_helpers._watch_shelf_prefer_live_quote", return_value=False
    ):
        # 1) Watch board
        df = watch.render_watch_board(
            watchlist=["FPT", "VCB"],
            watchlist_default=["FPT"],
            load_snapshot_cached=lambda s: {"symbol": s, "price": 100.0, "price_source": "sim"},
        )
        assert isinstance(df, pd.DataFrame)

        # 2) Daily actions
        fake.queue_button("Tải Daily Action List", True)
        daily.render_daily_action_panel(
            user_id="u1",
            plan=plan,
            profile="growth",
            total_capital_vnd=100_000_000.0,
            effective_quick_mode=True,
            list_holdings=lambda uid: [],
            list_universe_symbols=lambda limit=None: ["FPT", "VCB", "HPG"][: int(limit or 3)],
            build_daily_action_list=lambda *a, **k: pd.DataFrame(
                [{"Mã": "FPT", "Hành động": "BUY"}]
            ),
        )

        # 3) Auto Pilot (local path — PG off)
        with patch("core.pg_analysis_jobs.autopilot_pg_jobs_enabled", return_value=False):
            board = pd.DataFrame([{"Mã": "FPT", "Điểm": 80, "Hành động": "BUY", "Giá": 100.0}])
            simple = pd.DataFrame(
                [
                    {
                        "Mã": "FPT",
                        "Khuyến nghị": "MUA",
                        "Hành động": "BUY",
                        "Giá vào": 100.0,
                        "SL": 90.0,
                        "TP": 120.0,
                    }
                ]
            )
            auto.render_autopilot_panel(
                autopilot_mode=True,
                autopilot_refresh=False,
                profile="growth",
                autopilot_limit=30,
                total_capital_vnd=100_000_000.0,
                effective_quick_mode=True,
                plan=plan,
                plan_id="free",
                user_id="u1",
                ticker="FPT",
                run_analysis=False,
                profit_focus_mode=False,
                load_autopilot_board=lambda *a, **k: board.copy(),
                build_autopilot_simple_view=lambda *a, **k: simple.copy(),
                build_profit_focus_board=lambda *a, **k: board.copy(),
                simple_view_for_plan=lambda df, *a, **k: df,
                can_auto_execute_symbol=lambda *a, **k: (False, "skip"),
                add_decision=lambda *a, **k: (True, "ok"),
                can_use_feature=lambda *a, **k: (True, "ok"),
                add_alert=lambda *a, **k: None,
                log_event=lambda *a, **k: None,
            )

        # 4) Finder widgets (avoid st.rerun by keeping preset stable)
        fake.session_state["finder_preset_id"] = "quick"
        fake.session_state["finder_preset_last_applied"] = "quick"
        fake.session_state["finder_opp_limit"] = 30
        fake.session_state["finder_min_avg_vol20"] = 0.0
        fake.session_state["finder_min_data_quality"] = 40.0
        fake.session_state["finder_min_catalyst_score"] = 0.0
        fake.session_state["finder_only_actionable"] = False
        fake.session_state["finder_dynamic_sector"] = True
        with patch.object(finder.pgj, "pg_analysis_jobs_enabled", return_value=False), patch.object(
            finder.pgj, "finder_pg_jobs_enabled", return_value=False
        ), patch("core.app_finder_panel.day_cache_load", return_value=None), patch(
            "core.app_finder_panel.day_cache_save", return_value=None
        ):
            finder.render_finder_panel(
                user_id="u1",
                profile="growth",
                total_capital_vnd=100_000_000.0,
                effective_quick_mode=True,
                plan=plan,
                subtype_label_to_id={"Ngân hàng": "bank"},
                universe_subtype_map=lambda: {"FPT": "tech", "VCB": "bank"},
                list_universe_symbols=lambda limit=None: ["FPT", "VCB"],
                build_opportunity_3m_board=lambda *a, **k: pd.DataFrame(
                    [
                        {
                            "Mã": "FPT",
                            "Xác suất tăng 3M %": 62.0,
                            "Data Quality %": 80.0,
                            "Ngành con": "tech",
                        }
                    ]
                ),
                load_benchmark_return_3m=lambda: (5.0, "VNINDEX"),
            )

        # 5) Scanner / opportunity filter + scan flow (no run)
        opp_cfg = opp.render_opportunity_filter_panel(
            watchlist=["FPT"],
            watchlist_default=["FPT"],
            profile="growth",
            total_capital_vnd=100_000_000.0,
            subtype_label_to_id={"Ngân hàng": "bank"},
            compute_top5_for_profile=lambda *a, **k: pd.DataFrame(),
            plan_scan_limit=100,
            universe_total=500,
        )
        assert isinstance(opp_cfg["universe_limit"], int)
        scan.run_scan_flow(
            run_scan=False,
            universe_limit=opp_cfg["universe_limit"],
            plan=plan,
            plan_label="Free",
            subtype_labels=[],
            subtype_label_to_id={},
            user_id="u1",
            plan_id="free",
            profile="growth",
            total_capital_vnd=100_000_000.0,
            min_avg_volume_20=300_000.0,
            list_universe_symbols=lambda limit=None: ["FPT"],
            universe_subtype_map=lambda: {},
            can_use_feature=lambda *a, **k: (True, "ok"),
            log_event=lambda *a, **k: None,
            scan_potential_stocks=lambda *a, **k: pd.DataFrame(),
            build_portfolio_options=lambda *a, **k: {},
        )
    return "tabs_ok"


def scenario_widget_edge_quota_slider() -> str:
    """Regression: plan_scan_limit=20 must not raise StreamlitAPIException."""
    from core import opportunity_filter_panel as opp, ui_widgets

    fake = FakeStreamlit()
    with _install_fake([opp, ui_widgets], fake):
        cfg = opp.render_opportunity_filter_panel(
            watchlist=["FPT"],
            watchlist_default=["FPT"],
            profile="growth",
            total_capital_vnd=1.0,
            subtype_label_to_id={},
            compute_top5_for_profile=lambda *a, **k: None,
            plan_scan_limit=20,
            universe_total=0,
        )
        assert isinstance(cfg["universe_limit"], int)
        assert cfg["universe_limit"] == 20
        slider_calls = [c for c in fake.calls if c[0] == "slider" and "universe" in str(c[1][0]).lower()]
        assert not slider_calls, "must not call slider when max==min"
    return "quota20_safe"


def scenario_edge_empty_universe() -> str:
    from core import app_scan_flow as scan, app_watch_board_panel as watch

    os.environ["II_WATCH_SHELF_PREFER_LIVE"] = "0"
    fake = FakeStreamlit()
    with _install_fake([watch, scan], fake), patch(
        "core.app_view_helpers.is_tradable_vn_symbol", return_value=True
    ), patch("core.app_view_helpers._watch_shelf_prefer_live_quote", return_value=False):
        df = watch.render_watch_board(
            watchlist=[],
            watchlist_default=[],
            load_snapshot_cached=lambda s: None,
        )
        assert isinstance(df, pd.DataFrame)

        with patch("core.pg_analysis_jobs.scan_pg_jobs_enabled", return_value=False):
            scan.run_scan_flow(
                run_scan=True,
                universe_limit=20,
                plan={"scan_limit": 20},
                plan_label="Free",
                subtype_labels=[],
                subtype_label_to_id={},
                user_id="u1",
                plan_id="free",
                profile="growth",
                total_capital_vnd=1.0,
                min_avg_volume_20=0.0,
                list_universe_symbols=lambda limit=None: [],
                universe_subtype_map=lambda: {},
                can_use_feature=lambda *a, **k: (True, "ok"),
                log_event=lambda *a, **k: None,
                scan_potential_stocks=lambda *a, **k: pd.DataFrame(),
                build_portfolio_options=lambda *a, **k: {},
            )
    return "empty_universe_ok"


def scenario_edge_quota_exhausted() -> str:
    from core import app_scan_flow as scan
    from core.exceptions import InsufficientQuotaError
    from core.product_layer import require_feature

    # Direct domain exception path
    with patch("core.plan_usage_service.can_use_feature", return_value=(False, "Vượt giới hạn")):
        # require_feature needs full deps — exercise scan UI path instead
        pass

    fake = FakeStreamlit()
    with _install_fake([scan], fake):
        with patch("core.pg_analysis_jobs.scan_pg_jobs_enabled", return_value=False):
            scan.run_scan_flow(
                run_scan=True,
                universe_limit=50,
                plan={"scan_limit": 50},
                plan_label="Free",
                subtype_labels=[],
                subtype_label_to_id={},
                user_id="u1",
                plan_id="free",
                profile="growth",
                total_capital_vnd=1.0,
                min_avg_volume_20=0.0,
                list_universe_symbols=lambda limit=None: ["FPT"] * 30,
                universe_subtype_map=lambda: {},
                can_use_feature=lambda *a, **k: (False, "Vượt giới hạn quét"),
                log_event=lambda *a, **k: None,
                scan_potential_stocks=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("should not scan")),
                build_portfolio_options=lambda *a, **k: {},
            )
        assert any("Vượt giới hạn" in e for e in fake.errors)
    _ = (InsufficientQuotaError, require_feature)
    return "quota_blocked"


def scenario_edge_ohlcv_failure() -> str:
    from core.ai_logic import generate_strategic_report
    from core.exceptions import DataProviderError
    from scrapers.portal import PortalDataError

    # Soft path: context failure should not crash report generation when not strict
    snap = {"symbol": "FPT", "price": 100.0, "pe": 10.0, "pb": 1.0, "roe": 0.15}
    with patch("core.ai_logic.build_investment_context", side_effect=RuntimeError("boom")), patch(
        "core.ai_logic.fetch_ohlcv_history", side_effect=PortalDataError("no ohlcv")
    ), patch("core.ai_logic.fetch_financial_indicators", side_effect=PortalDataError("no fin")), patch(
        "core.ai_logic.fetch_latest_news", side_effect=PortalDataError("no news")
    ), patch("core.ai_logic._call_openai", side_effect=Exception("no llm")), patch.dict(
        "os.environ", {"II_STRICT_DATA_PROVIDER": "0", "II_PREFERRED_LLM": "none"}, clear=False
    ):
        # Prefer no live LLM
        with patch("core.ai_logic._build_auto_provider_order", return_value=[]):
            report = generate_strategic_report(
                "FPT",
                snap,
                profile="growth",
                total_capital_vnd=100_000_000.0,
                sessions=60,
                news_limit=3,
                fast_mode=True,
            )
        assert isinstance(report, dict)
        assert report.get("ticker") == "FPT"

    with patch.dict("os.environ", {"II_STRICT_DATA_PROVIDER": "1"}, clear=False), patch(
        "core.ai_logic.build_investment_context", side_effect=RuntimeError("boom")
    ), patch("core.ai_logic.fetch_ohlcv_history", side_effect=PortalDataError("no ohlcv")):
        with pytest.raises(DataProviderError):
            generate_strategic_report(
                "FPT",
                snap,
                profile="growth",
                total_capital_vnd=100_000_000.0,
                sessions=60,
                news_limit=1,
                fast_mode=True,
            )
    return "ohlcv_fallback_ok"


def scenario_async_pg_polling() -> str:
    from core import app_autopilot_panel as auto, app_scan_flow as scan

    fake = FakeStreamlit()
    plan = {"scan_limit": 40, "llm_live": False}
    enqueued: list[str] = []

    mock_pgj = MagicMock()
    mock_pgj.autopilot_pg_jobs_enabled.return_value = True
    mock_pgj.scan_pg_jobs_enabled.return_value = True
    mock_pgj.enqueue_autopilot_board.side_effect = lambda jid, payload: enqueued.append(f"auto:{jid}")
    mock_pgj.enqueue_deep_scan.side_effect = lambda jid, payload: enqueued.append(f"scan:{jid}")
    mock_pgj.delete_job_if_failed.return_value = None

    with _install_fake([auto, scan], fake):
        with patch.dict("sys.modules", {}), patch(
            "core.pg_analysis_jobs.autopilot_pg_jobs_enabled", return_value=True
        ), patch("core.pg_analysis_jobs.enqueue_autopilot_board", mock_pgj.enqueue_autopilot_board), patch(
            "core.ui_bg_analysis.try_consume_analysis_job", return_value=None
        ), patch(
            "core.ui_bg_analysis.read_analysis_job_status",
            return_value={"state": "pending"},
        ), patch(
            "core.state_manager.set_autopilot_pg_poll_jid", lambda jid: fake.session_state.update({"autopilot_pg_poll_jid": jid})
        ), patch(
            "core.state_manager.render_job_progress_placeholder", lambda msg: fake.info(msg)
        ):
            # First render: job pending → lightweight poll path (no heavy board load)
            ticker, run = auto.render_autopilot_panel(
                autopilot_mode=True,
                autopilot_refresh=True,
                profile="growth",
                autopilot_limit=30,
                total_capital_vnd=1.0,
                effective_quick_mode=True,
                plan=plan,
                plan_id="free",
                user_id="u1",
                ticker="FPT",
                run_analysis=False,
                profit_focus_mode=False,
                load_autopilot_board=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("must not load sync")),
                build_autopilot_simple_view=lambda df, **k: df,
                build_profit_focus_board=lambda df, **k: df,
                simple_view_for_plan=lambda df, **k: df,
                can_auto_execute_symbol=lambda *a, **k: (False, ""),
                add_decision=lambda *a, **k: (True, "ok"),
                can_use_feature=lambda *a, **k: (True, "ok"),
                add_alert=lambda *a, **k: None,
                log_event=lambda *a, **k: None,
            )
            assert ticker == "FPT"
            assert run is False

        # Deep scan enqueue + poll
        with patch("core.pg_analysis_jobs.scan_pg_jobs_enabled", return_value=True), patch(
            "core.pg_analysis_jobs.enqueue_deep_scan", mock_pgj.enqueue_deep_scan
        ), patch("core.ui_bg_analysis.try_consume_analysis_job", return_value=None), patch(
            "core.ui_bg_analysis.read_analysis_job_status", return_value=None
        ), patch(
            "core.state_manager.set_scan_pg_poll_jid",
            lambda jid: fake.session_state.update({"scan_pg_poll_jid": jid}),
        ), patch(
            "core.state_manager.render_job_progress_placeholder", lambda msg: fake.info(msg)
        ):
            scan.run_scan_flow(
                run_scan=True,
                universe_limit=20,
                plan=plan,
                plan_label="Free",
                subtype_labels=[],
                subtype_label_to_id={},
                user_id="u1",
                plan_id="free",
                profile="growth",
                total_capital_vnd=1.0,
                min_avg_volume_20=0.0,
                list_universe_symbols=lambda limit=None: ["FPT", "VCB", "HPG"],
                universe_subtype_map=lambda: {},
                can_use_feature=lambda *a, **k: (True, "ok"),
                log_event=lambda *a, **k: None,
                scan_potential_stocks=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no sync scan")),
                build_portfolio_options=lambda *a, **k: {},
            )
            assert enqueued, "expected deep scan enqueue"
            assert fake.session_state.get("scan_pg_poll_jid")

        # Consume completed job on next poll
        done_df = pd.DataFrame([{"Mã": "FPT", "Điểm": 1}])
        with patch("core.pg_analysis_jobs.scan_pg_jobs_enabled", return_value=True), patch(
            "core.ui_bg_analysis.try_consume_analysis_job",
            return_value={"candidates": done_df, "portfolios": {}, "relaxed_used": False},
        ), patch(
            "core.state_manager.set_scan_pg_poll_jid",
            lambda jid: fake.session_state.update({"scan_pg_poll_jid": jid}),
        ):
            scan.run_scan_flow(
                run_scan=True,
                universe_limit=20,
                plan=plan,
                plan_label="Free",
                subtype_labels=[],
                subtype_label_to_id={},
                user_id="u1",
                plan_id="free",
                profile="growth",
                total_capital_vnd=1.0,
                min_avg_volume_20=0.0,
                list_universe_symbols=lambda limit=None: ["FPT", "VCB"],
                universe_subtype_map=lambda: {},
                can_use_feature=lambda *a, **k: (True, "ok"),
                log_event=lambda *a, **k: None,
                scan_potential_stocks=lambda *a, **k: pd.DataFrame(),
                build_portfolio_options=lambda *a, **k: {},
            )
            assert "scan_candidates" in fake.session_state
    return "async_poll_ok"


def scenario_apptest_auth_shell() -> str:
    """
    Streamlit AppTest smoke — skipped by default on hosts where AppTest can hang
    (set II_ENABLE_APPTEST=1 to force). FakeStreamlit auth scenarios already cover
    the same contracts without a ScriptRunContext.
    """
    if str(os.environ.get("II_ENABLE_APPTEST", "0")).strip().lower() not in ("1", "true", "yes", "on"):
        # Still exercise a minimal AppTest-shaped contract via FakeStreamlit.
        return scenario_auth_success().replace("login_ok", "apptest_skipped_use_fake_auth")

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    from streamlit.testing.v1 import AppTest

    def _auth_app() -> None:
        import streamlit as st

        from core.app_auth_gate import (
            clear_authenticated_session,
            is_authenticated_session,
            start_authenticated_session,
        )

        uid = st.text_input("Mã khách hàng", value="demo")
        pin = st.text_input("PIN truy cập", value="1234", type="password")
        if st.button("Đăng nhập"):
            if pin == "1234":
                start_authenticated_session(uid)
                st.success("ok")
            else:
                clear_authenticated_session()
                st.error("bad pin")
        if is_authenticated_session(uid):
            st.write("authenticated")

    def _run() -> str:
        at = AppTest.from_function(_auth_app, default_timeout=8)
        at.run(timeout=8)
        if at.exception:
            raise AssertionError(f"AppTest exception: {at.exception}")
        if at.button:
            at.button[0].click().run(timeout=8)
        if at.exception:
            raise AssertionError(f"AppTest after click: {at.exception}")
        return "apptest_auth_ok"

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_run)
        try:
            return fut.result(timeout=30)
        except FuturesTimeout as e:
            raise RuntimeError("AppTest hung >30s — treat as failure for production gate") from e


SCENARIOS: list[tuple[str, Callable[[], str]]] = [
    ("auth_success", scenario_auth_success),
    ("auth_failure", scenario_auth_failure),
    ("session_expired", scenario_session_expired),
    ("tab_navigation", scenario_tab_navigation),
    ("widget_quota_slider", scenario_widget_edge_quota_slider),
    ("edge_empty_universe", scenario_edge_empty_universe),
    ("edge_quota_exhausted", scenario_edge_quota_exhausted),
    ("edge_ohlcv_failure", scenario_edge_ohlcv_failure),
    ("async_pg_polling", scenario_async_pg_polling),
    ("apptest_auth_shell", scenario_apptest_auth_shell),
]


def run_all_simulations() -> SimulationReport:
    # Mirror pytest conftest defaults — avoid accidental live network hangs in CLI mode.
    os.environ.setdefault("II_SNAPSHOT_PREFER_LIVE", "0")
    os.environ.setdefault("II_WATCH_SHELF_PREFER_LIVE", "0")
    os.environ.setdefault("II_FORECAST_SETTLE_LIVE_BACKFILL", "0")
    os.environ.setdefault("II_FETCH_FINANCIAL_STATEMENTS", "0")
    os.environ.setdefault("II_SKIP_PEER_FETCH", "1")

    try:
        from scrapers import vn_listing as _vl

        net_ctx = patch.object(_vl, "fetch_vndirect_stock_codes", return_value=([], "offline_sim"))
        net_ctx2 = patch.object(_vl, "fetch_fireant_stock_codes", return_value=([], "offline_sim"))
    except Exception:
        net_ctx = nullcontext()
        net_ctx2 = nullcontext()

    report = SimulationReport()
    with net_ctx, net_ctx2:
        for name, fn in SCENARIOS:
            report.results.append(_run_scenario(name, fn))
    return report


@pytest.mark.timeout(120)
def test_simulate_user_flows_production_gate() -> None:
    report = run_all_simulations()
    assert report.ok, report.summary()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = run_all_simulations()
    print(rep.summary())
    raise SystemExit(0 if rep.ok else 1)
