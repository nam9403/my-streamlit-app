#!/usr/bin/env python3
"""
Đánh giá hiệu quả ứng dụng theo giai đoạn 01/2025 -> 01/2026.

Mục tiêu:
- Mô phỏng vốn ban đầu 100 triệu VND theo rule tín hiệu pha (đang dùng trong app/backtest core).
- Tính tăng/giảm giá trị danh mục trong giai đoạn.
- Tổng hợp một số yếu tố vĩ mô/vi mô để tham chiếu bối cảnh.

Lưu ý:
- Đây là mô phỏng học tập, không phải cam kết lợi nhuận.
- Không bao gồm phí giao dịch, thuế, trượt giá.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _to_pct(x: float) -> float:
    return float(round(x * 100.0, 2))


def _max_drawdown(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    peak = series.cummax()
    dd = (series / peak - 1.0).fillna(0.0)
    return float(dd.min())


def _period_slice(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    out = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    return out.sort_values("date").reset_index(drop=True)


def _equity_between_dates(
    dates: list[pd.Timestamp], equity: np.ndarray, start: pd.Timestamp, end: pd.Timestamp
) -> pd.Series:
    s = pd.Series(equity, index=pd.to_datetime(dates)).sort_index()
    s = s[(s.index >= start) & (s.index <= end)]
    return s


def _simulate_strategy_from_start(
    ohlcv: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    initial_cash: float,
    warmup: int = 60,
    stop_loss_pct: float = 0.12,
) -> tuple[pd.Series, float, list[dict[str, Any]]]:
    """
    Chạy mô phỏng đúng câu hỏi "đầu tư từ start":
    - Chỉ bắt đầu có vốn và giao dịch từ start.
    - Dùng dữ liệu trước start làm warmup cho phase/MA50 (không mang vị thế từ quá khứ).
    """
    from core.engine import compute_technical_indicators, detect_market_phase_from_ohlcv

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    df = df[(df["date"] <= end)].reset_index(drop=True)
    if df.empty:
        raise ValueError("OHLCV rỗng.")

    start_idx_arr = df.index[df["date"] >= start]
    if len(start_idx_arr) == 0:
        raise ValueError("Không có dữ liệu từ ngày bắt đầu.")
    start_idx = int(start_idx_arr[0])
    if start_idx < warmup:
        raise ValueError("Không đủ dữ liệu warmup trước ngày bắt đầu.")

    cash = float(initial_cash)
    shares = 0.0
    invested = False
    entry_price = 0.0
    out_dates: list[pd.Timestamp] = []
    out_eq: list[float] = []
    trades: list[dict[str, Any]] = []

    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        d = pd.Timestamp(row["date"]).normalize()
        if d > end:
            break
        price = float(row["close"])
        if price <= 0:
            continue

        window = df.iloc[: i + 1].copy()
        try:
            ph = detect_market_phase_from_ohlcv(window).phase
        except Exception:
            ph = "neutral"

        want_buy = ph in ("accumulation", "breakout")
        if want_buy and not invested:
            shares = cash / price
            cash = 0.0
            invested = True
            entry_price = price
            trades.append({"date": str(d.date()), "side": "BUY", "price": round(float(price), 4), "phase": str(ph)})
        elif ph == "distribution" and invested:
            do_exit = True
            if len(window) >= 55:
                try:
                    ti = compute_technical_indicators(window)
                    ma50 = float(ti.iloc[-1]["ma50"])
                    if pd.notna(ma50) and ma50 > 0 and price > ma50:
                        do_exit = False
                except Exception:
                    do_exit = True
            if do_exit:
                cash = shares * price
                trades.append({"date": str(d.date()), "side": "SELL", "price": round(float(price), 4), "phase": str(ph)})
                shares = 0.0
                invested = False
                entry_price = 0.0

        # Hard risk guardrail: stop-loss theo giá vào lệnh.
        if invested and entry_price > 0 and price <= entry_price * (1.0 - max(0.0, float(stop_loss_pct))):
            cash = shares * price
            trades.append({"date": str(d.date()), "side": "SELL", "price": round(float(price), 4), "phase": "stop_loss"})
            shares = 0.0
            invested = False
            entry_price = 0.0

        eq = cash + shares * price
        out_dates.append(d)
        out_eq.append(eq)

    s = pd.Series(out_eq, index=pd.to_datetime(out_dates)).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    invested_ratio = float(np.mean(np.array(out_eq) > cash + 1e-9)) if len(out_eq) else 0.0
    return s, invested_ratio, trades


def _simulate_momentum_rotation_from_start(
    closes_by_symbol: dict[str, pd.Series],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    initial_cash: float,
    top_n: int = 2,
    mom_lookback: int = 60,
    ma_window: int = 50,
) -> tuple[pd.Series, dict[str, Any]]:
    """
    Mô hình nâng cấp:
    - Rebalance đầu tháng.
    - Chọn top N mã theo momentum lookback.
    - Chỉ giữ mã có close > MA50 và momentum dương.
    - Không đạt điều kiện => giữ tiền mặt.
    """
    if not closes_by_symbol:
        raise ValueError("Không có chuỗi giá để mô phỏng rotation.")
    all_idx: pd.DatetimeIndex | None = None
    for s in closes_by_symbol.values():
        si = pd.to_datetime(s.index).normalize()
        all_idx = si if all_idx is None else all_idx.union(si)
    if all_idx is None or len(all_idx) < 5:
        raise ValueError("Không đủ dữ liệu lịch để mô phỏng rotation.")
    all_idx = all_idx[(all_idx >= start) & (all_idx <= end)]
    if len(all_idx) < 5:
        raise ValueError("Không đủ dữ liệu trong giai đoạn rotation.")

    price_tbl = pd.DataFrame({k: pd.to_numeric(v, errors="coerce") for k, v in closes_by_symbol.items()})
    price_tbl.index = pd.to_datetime(price_tbl.index).normalize()
    price_tbl = price_tbl.reindex(all_idx).sort_index().ffill().bfill().dropna(how="any")
    if len(price_tbl) < max(mom_lookback + 5, ma_window + 5):
        raise ValueError("Không đủ dữ liệu cho lookback momentum/MA.")

    cash = float(initial_cash)
    holdings: dict[str, float] = {}
    eq_vals: list[float] = []
    eq_dates: list[pd.Timestamp] = []
    months_rebalanced = 0
    invested_days = 0

    for i, d in enumerate(price_tbl.index):
        row = price_tbl.iloc[i]
        is_first_trading_day_month = i == 0 or d.month != price_tbl.index[i - 1].month
        if is_first_trading_day_month:
            months_rebalanced += 1
            # Liquidate current holdings at current close.
            if holdings:
                cash = sum(float(sh) * float(row[sym]) for sym, sh in holdings.items())
                holdings = {}

            # Rank by momentum + trend filter.
            candidates: list[tuple[str, float]] = []
            if i >= max(mom_lookback, ma_window):
                for sym in price_tbl.columns:
                    s = price_tbl[sym].iloc[: i + 1]
                    px = float(s.iloc[-1])
                    prev = float(s.iloc[-1 - mom_lookback])
                    if prev <= 0 or px <= 0:
                        continue
                    mom = px / prev - 1.0
                    ma = float(s.tail(ma_window).mean())
                    if mom > 0 and px > ma:
                        candidates.append((sym, mom))
            candidates.sort(key=lambda x: x[1], reverse=True)
            selected = [sym for sym, _ in candidates[: max(1, int(top_n))]]
            if selected:
                alloc = cash / float(len(selected))
                for sym in selected:
                    px = float(row[sym])
                    if px > 0:
                        holdings[sym] = alloc / px
                cash = 0.0

        eq = cash + sum(float(sh) * float(row[sym]) for sym, sh in holdings.items())
        if holdings:
            invested_days += 1
        eq_vals.append(eq)
        eq_dates.append(pd.Timestamp(d))

    eq_series = pd.Series(eq_vals, index=pd.to_datetime(eq_dates)).sort_index()
    diag = {
        "months_rebalanced": months_rebalanced,
        "invested_ratio_pct": round((invested_days / max(1, len(eq_series))) * 100.0, 2),
        "top_n": int(top_n),
        "momentum_lookback": int(mom_lookback),
        "ma_window": int(ma_window),
    }
    return eq_series, diag


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="FPT,VNM,HPG,VCB", help="Danh sách mã, cách nhau bởi dấu phẩy.")
    ap.add_argument("--capital", type=float, default=100_000_000.0, help="Vốn mô phỏng ban đầu (VND).")
    ap.add_argument("--start", default="2025-01-01", help="Ngày bắt đầu (YYYY-MM-DD).")
    ap.add_argument("--end", default="2026-01-31", help="Ngày kết thúc (YYYY-MM-DD).")
    ap.add_argument("--stop-loss-pct", type=float, default=0.05, help="Stop-loss cứng theo entry (ví dụ 0.05 = 5%).")
    ap.add_argument("--rotation-top-n", type=int, default=2, help="Số mã giữ mỗi lần tái cân bằng rotation.")
    ap.add_argument("--rotation-mom-lookback", type=int, default=60, help="Số phiên lookback momentum.")
    ap.add_argument("--rotation-ma-window", type=int, default=50, help="Số phiên MA filter.")
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    if end <= start:
        raise SystemExit("Ngày kết thúc phải lớn hơn ngày bắt đầu.")

    symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
    if not symbols:
        raise SystemExit("Danh sách mã rỗng.")

    from core.strategy_backtest import fetch_long_ohlcv_for_backtest, fetch_vn_benchmark_series

    benchmark_series, benchmark_label = fetch_vn_benchmark_series("max")
    macro: dict[str, Any] = {}
    if benchmark_series is not None and len(benchmark_series) > 5:
        b = benchmark_series.sort_index()
        b = b[(b.index >= start) & (b.index <= end)]
        if len(b) >= 2:
            b_ret = float(b.iloc[-1] / b.iloc[0] - 1.0)
            b_daily = b.pct_change().dropna()
            macro = {
                "benchmark_label": benchmark_label,
                "benchmark_return_pct": round(b_ret * 100.0, 2),
                "benchmark_annualized_vol_pct": _to_pct(float(b_daily.std() * np.sqrt(252.0))) if len(b_daily) else 0.0,
                "benchmark_max_drawdown_pct": round(_max_drawdown(b) * 100.0, 2),
            }

    per_symbol_capital = float(args.capital) / float(len(symbols))
    symbol_reports: list[dict[str, Any]] = []
    eq_components: list[pd.Series] = []
    eq_buyhold_components: list[pd.Series] = []
    closes_for_rotation: dict[str, pd.Series] = {}

    for sym in symbols:
        ohlcv, _ = fetch_long_ohlcv_for_backtest(sym, range_preference="max")
        eq_series, invested_ratio, trade_log = _simulate_strategy_from_start(
            ohlcv,
            start=start,
            end=end,
            initial_cash=per_symbol_capital,
            warmup=60,
            stop_loss_pct=float(args.stop_loss_pct),
        )
        if len(eq_series) < 2:
            raise SystemExit(f"Không đủ dữ liệu mô phỏng trong giai đoạn cho {sym}.")
        eq_norm = eq_series.copy()
        eq_components.append(eq_norm.rename(sym))
        ohlcv["date"] = pd.to_datetime(ohlcv["date"], errors="coerce")
        p = _period_slice(ohlcv, start, end)
        if len(p) < 2:
            raise SystemExit(f"Không đủ OHLCV giai đoạn cho {sym}.")
        close = pd.to_numeric(p["close"], errors="coerce").dropna()
        closes_for_rotation[sym] = pd.Series(close.values, index=pd.to_datetime(p["date"]).dt.normalize(), name=sym)
        close_eq = close / float(close.iloc[0]) * per_symbol_capital
        eq_buyhold_components.append(pd.Series(close_eq.values, index=pd.to_datetime(p["date"]).dt.normalize(), name=sym))

        app_ret = float(eq_norm.iloc[-1] / eq_norm.iloc[0] - 1.0)
        daily_ret = close.pct_change().dropna()
        micro = {
            "price_change_pct": round(float(close.iloc[-1] / close.iloc[0] - 1.0) * 100.0, 2),
            "annualized_vol_pct": _to_pct(float(daily_ret.std() * np.sqrt(252.0))) if len(daily_ret) else 0.0,
            "max_drawdown_pct": round(_max_drawdown(close) * 100.0, 2),
            "avg_volume": round(float(pd.to_numeric(p["volume"], errors="coerce").fillna(0.0).mean()), 2),
        }

        symbol_reports.append(
            {
                "symbol": sym,
                "strategy_return_pct": round(app_ret * 100.0, 2),
                "strategy_end_value_vnd": round(float(eq_norm.iloc[-1]), 2),
                "invested_ratio_pct": round(invested_ratio * 100.0, 2),
                "trade_count": int(len(trade_log)),
                "trades": trade_log,
                "benchmark_label": f"Mua & giữ {sym}",
                "micro_factors": micro,
            }
        )

    # Gộp danh mục theo ngày giao dịch chung (forward-fill khi lệch lịch nhỏ).
    portfolio = pd.concat(eq_components, axis=1).sort_index().ffill().dropna(how="any")
    if len(portfolio) < 2:
        raise SystemExit("Không tạo được chuỗi danh mục hợp lệ.")
    portfolio_bh = pd.concat(eq_buyhold_components, axis=1).sort_index().ffill().dropna(how="any")
    portfolio_bh_value = portfolio_bh.sum(axis=1)
    portfolio_value = portfolio.sum(axis=1)
    initial_value = float(portfolio_value.iloc[0])
    final_value = float(portfolio_value.iloc[-1])
    pnl = final_value - initial_value
    ret_pct = (final_value / initial_value - 1.0) * 100.0
    bh_ret_pct = (float(portfolio_bh_value.iloc[-1]) / float(portfolio_bh_value.iloc[0]) - 1.0) * 100.0

    # Enhanced mode: monthly momentum rotation across symbol universe.
    rotation_eq, rotation_diag = _simulate_momentum_rotation_from_start(
        closes_for_rotation,
        start=start,
        end=end,
        initial_cash=float(args.capital),
        top_n=int(args.rotation_top_n),
        mom_lookback=int(args.rotation_mom_lookback),
        ma_window=int(args.rotation_ma_window),
    )
    rotation_ret_pct = (float(rotation_eq.iloc[-1]) / float(rotation_eq.iloc[0]) - 1.0) * 100.0

    status = "TĂNG" if pnl >= 0 else "GIẢM"
    result = {
        "scenario": {
            "capital_vnd": float(args.capital),
            "start": str(start.date()),
            "end": str(end.date()),
            "symbols": symbols,
            "method": "Equal-weight portfolio, rule tín hiệu pha của app (strategy_backtest).",
            "notes": "Đã reset vốn tại đúng ngày bắt đầu; không carry vị thế từ trước kỳ đo.",
            "risk_guardrail": {"stop_loss_pct": float(args.stop_loss_pct)},
            "enhanced_model": {
                "name": "monthly_momentum_rotation",
                "rotation_top_n": int(args.rotation_top_n),
                "momentum_lookback": int(args.rotation_mom_lookback),
                "ma_window": int(args.rotation_ma_window),
            },
        },
        "macro_factors": macro,
        "portfolio_result": {
            "initial_value_vnd": round(initial_value, 2),
            "final_value_vnd": round(final_value, 2),
            "pnl_vnd": round(pnl, 2),
            "return_pct": round(ret_pct, 2),
            "equal_weight_buyhold_return_pct": round(bh_ret_pct, 2),
            "status": status,
        },
        "enhanced_result": {
            "return_pct": round(rotation_ret_pct, 2),
            "end_value_vnd": round(float(rotation_eq.iloc[-1]), 2),
            "improve_vs_base_pct_point": round(rotation_ret_pct - ret_pct, 2),
            **rotation_diag,
        },
        "per_symbol": symbol_reports,
        "disclaimer": "Mô phỏng học tập; không cam kết hiệu quả tương lai.",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"app_effectiveness_{start.date()}_{end.date()}.json"
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== KIỂM TRA HIỆU QUẢ ỨNG DỤNG ===")
    print(f"Giai đoạn: {start.date()} -> {end.date()}")
    print(f"Vốn ban đầu: {initial_value:,.0f} VND")
    print(f"Giá trị cuối kỳ: {final_value:,.0f} VND")
    print(f"Lãi/Lỗ: {pnl:,.0f} VND ({ret_pct:.2f}%)")
    print(
        f"Enhanced rotation: {float(rotation_eq.iloc[-1]):,.0f} VND "
        f"({rotation_ret_pct:.2f}%, cải thiện {rotation_ret_pct - ret_pct:.2f} điểm %)"
    )
    print(f"Trạng thái: {status}")
    if macro:
        print(
            f"Vĩ mô ({macro.get('benchmark_label','benchmark')}): "
            f"Return={macro.get('benchmark_return_pct', 0):.2f}% | "
            f"Vol={macro.get('benchmark_annualized_vol_pct', 0):.2f}% | "
            f"MaxDD={macro.get('benchmark_max_drawdown_pct', 0):.2f}%"
        )
    print(f"Đã lưu báo cáo: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

