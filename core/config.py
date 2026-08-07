"""
Cấu hình tập trung (biến môi trường). Dùng cho định giá và hiển thị mặc định.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

# Graham Growth: V = EPS × (8.5 + 2g) × (GRAHAM_CLASSIC_AAA / Y)
# Numerator 4.4 giữ nguyên theo sách Graham (AAA Mỹ thời đó).
GRAHAM_CLASSIC_AAA_YIELD_PCT = 4.4
# Y động = lợi suất TPCP VN 10 năm (điều chỉnh theo chu kỳ NHNN).
VN_10Y_BOND_YIELD_DEFAULT_PCT = 6.5
# Trần tăng trưởng EPS dùng trong Graham Growth (tránh g đỉnh chu kỳ).
GRAHAM_GROWTH_G_CAP_PCT = 15.0


@dataclass(frozen=True)
class AppSettings:
    """Cài đặt đọc một lần từ môi trường."""

    default_bond_yield_pct: float  # alias: VN_10Y_BOND_YIELD (%/năm)
    merge_live_fundamentals: bool
    skip_mock_snapshot: bool

    @property
    def vn_10y_bond_yield_pct(self) -> float:
        """Lợi suất TPCP VN ~10Y dùng làm Y trong Graham Growth."""
        return float(self.default_bond_yield_pct)


def _parse_yield(raw: str | None, *, default: float = VN_10Y_BOND_YIELD_DEFAULT_PCT) -> float:
    if not raw or not str(raw).strip():
        return float(default)
    try:
        y = float(str(raw).strip().replace(",", "."))
    except ValueError:
        return float(default)
    return max(0.5, min(y, 25.0))


def _env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def resolve_vn_10y_bond_yield_pct(explicit: float | None = None) -> float:
    """
    Y cho Graham Growth: snapshot override → env → mặc định VN 10Y (~6.5%).

    Env (ưu tiên trái → phải):
      VN_10Y_BOND_YIELD | II_VN_10Y_BOND_YIELD | II_DEFAULT_BOND_YIELD_PCT | BOND_YIELD_PCT
    """
    if explicit is not None:
        try:
            y = float(explicit)
            if y > 0:
                return max(0.5, min(y, 25.0))
        except (TypeError, ValueError):
            pass
    return float(get_settings().default_bond_yield_pct)


@lru_cache
def get_settings() -> AppSettings:
    """
    VN_10Y_BOND_YIELD / II_VN_10Y_BOND_YIELD / II_DEFAULT_BOND_YIELD_PCT / BOND_YIELD_PCT:
    lợi suất trái phiếu tham chiếu Y (%/năm) cho Graham Growth V = EPS×(8.5+2g)×(4.4/Y).
    Mặc định 6.5 (TPCP VN ~10 năm) — điều chỉnh theo chu kỳ lãi suất NHNN.

    II_MERGE_LIVE_FUNDAMENTALS: 1 (mặc định) — với mã có trong mock_financials.json, vẫn thử gộp EPS/BVPS…
    từ scrape live để định giá sát thực tế hơn.

    II_SKIP_MOCK: 1 — bỏ qua hoàn toàn mock; chỉ dùng scrape/API (thất bại nếu không có mạng).

    II_FETCH_FINANCIAL_STATEMENTS: 1 — gọi API BCTC nhiều kỳ (VNDirect Finfo) và gộp vào snapshot.
    Trong test mặc định tắt (conftest). II_FSTATEMENT_TIMEOUT: giây chờ (mặc định 20).

    II_SKIP_PEER_FETCH: 1 — không gọi snapshot peer (test nhanh). Production: unset hoặc 0.

    Kịch bản Bear/Bull (elite): II_SCENARIO_BEAR_G_DELTA, II_SCENARIO_BULL_G_DELTA (mặc định -3 / +4),
    II_SCENARIO_BEAR_Y_DELTA, II_SCENARIO_BULL_Y_DELTA (± lợi suất %). DCF: II_DCF_CAPEX_RATIO,
    II_DCF_EQUITY_RISK_PREMIUM, II_PEER_LIMIT.

    Cache snapshot đĩa: II_SNAPSHOT_DISK_CACHE (1=bật), II_SNAPSHOT_CACHE_TTL_SEC (mặc định 1800).
    II_READ_STALE_DISK=1 — đọc snapshot trên đĩa kể cả khi quá TTL (bồn “cạn” vẫn dùng được) trước mock/scrape.
    Listing VN: II_VN_LISTING_API (1=gọi Finfo lấy danh sách mã). Extra: data/vn_universe_extra.txt (mỗi dòng một mã).
    Refresh nền: scripts/snapshot_disk_refresh.py, snapshot_disk_refresh_loop.py, start_data_tank.bat (II_REFRESH_INTERVAL_SEC).

    UI tự làm mới khi đĩa đổi: II_UI_DISK_POLL_SEC (giây, mặc định 45) — fragment soi cached_at, không cần F5.

    Scanner (core/scanner_service): II_SCAN_MAX_WORKERS (default 4, max 8), II_SCAN_PREFILTER_MAX_WORKERS
    (default 4, max 8), II_SCAN_SYMBOL_BATCH_SIZE, II_SCAN_PRESELECT_LIMIT_CAP — giới hạn song song
    và số mã sau prefilter (giảm timeout/rate-limit Vietcap khi quét song song).

    Luân phiên universe: II_UNIVERSE_AUTO_ROTATE=1 (mặc định) — dịch cửa sổ quét trên full listing theo ngày
    (Auto Pilot, scan cơ hội, prefetch nền) thay vì luôn lấy N mã đầu danh sách.
    """
    raw = (
        os.environ.get("VN_10Y_BOND_YIELD")
        or os.environ.get("II_VN_10Y_BOND_YIELD")
        or os.environ.get("II_DEFAULT_BOND_YIELD_PCT")
        or os.environ.get("BOND_YIELD_PCT")
    )
    return AppSettings(
        default_bond_yield_pct=_parse_yield(raw),
        merge_live_fundamentals=_env_flag("II_MERGE_LIVE_FUNDAMENTALS", True),
        skip_mock_snapshot=_env_flag("II_SKIP_MOCK", False),
    )


@lru_cache
def http_timeout_seconds() -> float:
    """
    Timeout HTTP mặc định (requests). II_HTTP_TIMEOUT hoặc VALUE_INVESTOR_PORTAL_TIMEOUT.
    Giới hạn 3–60 giây.
    """
    raw = os.environ.get("II_HTTP_TIMEOUT") or os.environ.get("VALUE_INVESTOR_PORTAL_TIMEOUT", "12")
    try:
        t = float(str(raw).strip().replace(",", "."))
    except ValueError:
        t = 12.0
    return max(3.0, min(60.0, t))
