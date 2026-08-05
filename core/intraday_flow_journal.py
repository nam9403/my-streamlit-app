"""Persistence layer cho ``FlowSignal`` — JSON-Lines append-only.

Mục đích:
- **Audit**: trả lời "vì sao alert FPT lúc 10:35 hôm qua phát" sau nhiều ngày.
- **Backtest**: dữ liệu nền để chạy chiến lược "Big Boy → giữ N ngày" rồi
  đo P&L thực tế ⇒ tune ``min_intensity`` empirically.
- **Compliance**: ghi nhận decision-trail cho mọi cảnh báo gửi đi.

Định dạng: 1 JSON object/line (JSONL) — append-only, không xoá row cũ.
File rotate theo tuần ISO (e.g. ``flow_signals_2026W19.jsonl``) để
``read_recent_flow_signals`` không phải mở file 100MB.

**Cross-process safety (C4)**: khi nhiều process cùng ghi (app.py + background
scheduler), POSIX append nguyên tử <4KB. Nếu payload vượt 4KB hoặc chạy trên
Windows, ta dùng `_acquire_file_lock` (msvcrt trên Windows, fcntl trên POSIX)
để serialize. Lock per-file → throughput không bị nghẽn ở instance khác file.

Không có dependency mới: chỉ stdlib + pandas (đã có).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any, Iterable, Iterator

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

_IS_WINDOWS = sys.platform.startswith("win")
if _IS_WINDOWS:
    try:
        import msvcrt
    except ImportError:  # pragma: no cover - đảm bảo Linux build vẫn import
        msvcrt = None  # type: ignore[assignment]
    fcntl = None  # type: ignore[assignment]
else:
    try:
        import fcntl  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        fcntl = None  # type: ignore[assignment]
    msvcrt = None  # type: ignore[assignment]


def _file_lock_enabled() -> bool:
    """Bật file lock chỉ khi cần cross-process safety (default ON).

    Có thể tắt qua ``II_FLOW_JOURNAL_FILE_LOCK=0`` nếu chắc chắn chỉ có 1
    process ghi (vd. demo / dev), để tránh overhead lock trên Windows.
    """
    raw = (os.environ.get("II_FLOW_JOURNAL_FILE_LOCK") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


_WINDOWS_LOCK_TIMEOUT_SEC = float(
    os.environ.get("II_FLOW_JOURNAL_LOCK_TIMEOUT_SEC") or "2.0"
)
_WINDOWS_LOCK_INTERVAL_SEC = float(
    os.environ.get("II_FLOW_JOURNAL_LOCK_INTERVAL_SEC") or "0.01"
)


@contextmanager
def _acquire_file_lock(fh: IO[Any]) -> Iterator[None]:
    """Cross-platform exclusive file lock (best-effort).

    - POSIX: dùng ``fcntl.flock`` với ``LOCK_EX`` (blocking, native).
    - Windows: ``msvcrt.locking(LK_NBLCK, 1)`` polling
      ``_WINDOWS_LOCK_INTERVAL_SEC`` mỗi lần — nhanh hơn ``LK_LOCK`` mặc định
      (retry 10s/lần) ~1000x khi có contention.
    - Disabled qua env ``II_FLOW_JOURNAL_FILE_LOCK=0`` ⇒ chỉ dùng thread
      RLock (đủ cho single-process; KHÔNG an toàn cross-process).
    """
    if not _file_lock_enabled():
        yield
        return
    locked = False
    try:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
            locked = True
        elif msvcrt is not None:
            import time as _time

            # Note: msvcrt.locking lock theo OFFSET HIỆN TẠI của file pointer.
            # Để unlock đúng phải nằm cùng offset → seek về 0 trước khi
            # lock, write ở mode "a" (auto-seek end), rồi seek lại 0 trước
            # unlock. Lock 1 byte tại offset 0 đủ làm mutex cross-process.
            deadline = _time.time() + _WINDOWS_LOCK_TIMEOUT_SEC
            while _time.time() < deadline:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                    locked = True
                    break
                except OSError:
                    _time.sleep(_WINDOWS_LOCK_INTERVAL_SEC)
            if not locked:
                logger.info("flow_journal_msvcrt_lock_timeout")
        yield
    finally:
        if locked:
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
                elif msvcrt is not None:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            except OSError:
                pass

_DEFAULT_DIR = Path(
    str(os.environ.get("II_FLOW_JOURNAL_DIR") or "data/runtime/flow_journal")
)
_DEFAULT_MAX_FILE_MB = float(os.environ.get("II_FLOW_JOURNAL_MAX_FILE_MB", "25") or "25")
_DEFAULT_RETENTION_WEEKS = int(os.environ.get("II_FLOW_JOURNAL_RETENTION_WEEKS", "8") or "8")


def _journal_dir() -> Path:
    raw = os.environ.get("II_FLOW_JOURNAL_DIR")
    return Path(str(raw)) if raw else _DEFAULT_DIR


def _file_for_week(ts: datetime, *, base_dir: Path | None = None) -> Path:
    iso_year, iso_week, _ = ts.isocalendar()
    base = base_dir or _journal_dir()
    return base / f"flow_signals_{iso_year}W{iso_week:02d}.jsonl"


def _coerce_payload(signal: Any) -> dict[str, Any]:
    """Convert ``FlowSignal``/dict/other → plain dict ghi được JSON.

    Hỗ trợ:
    - dataclass có ``to_dict()``  → ưu tiên gọi để giữ rounding & field order.
    - dataclass thường           → ``asdict()``.
    - dict                       → copy nông.
    - other                      → wrap ``{"raw": str(signal)}`` (fallback an toàn).
    """
    if hasattr(signal, "to_dict") and callable(signal.to_dict):
        try:
            payload = signal.to_dict()
            if isinstance(payload, dict):
                return dict(payload)
        except Exception:  # noqa: BLE001
            pass
    if is_dataclass(signal):
        try:
            return asdict(signal)
        except Exception:  # noqa: BLE001
            pass
    if isinstance(signal, dict):
        return dict(signal)
    return {"raw": str(signal)}


def append_flow_signal(
    signal: Any,
    *,
    base_dir: Path | None = None,
    extra_context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Path:
    """Ghi 1 ``FlowSignal`` (hoặc dict tương đương) vào file tuần hiện tại.

    Args:
        signal: ``FlowSignal`` instance hoặc dict đã serialize từ ``to_dict``.
        base_dir: Override thư mục lưu (chủ yếu dùng cho test).
        extra_context: Dict merge thêm (e.g. ``{"phase": "background_cycle"}``).
        now: Override timestamp (chủ yếu dùng cho test).

    Returns:
        Đường dẫn file đã ghi.

    Raises:
        OSError: khi không thể tạo thư mục hoặc ghi file.
    """
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = _coerce_payload(signal)
    if extra_context:
        for k, v in extra_context.items():
            if k not in payload:
                payload[k] = v
    payload.setdefault("journaled_at_utc", ts.isoformat())
    file_path = _file_for_week(ts, base_dir=base_dir)
    with _LOCK:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as fh:
            with _acquire_file_lock(fh):
                fh.write(json.dumps(payload, ensure_ascii=False, default=str))
                fh.write("\n")
                fh.flush()
    return file_path


def append_flow_signals_batch(
    signals: Iterable[Any],
    *,
    base_dir: Path | None = None,
    extra_context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> int:
    """Ghi nhiều signal một lần. Trả về số bản ghi đã ghi."""
    count = 0
    for sig in signals:
        try:
            append_flow_signal(sig, base_dir=base_dir, extra_context=extra_context, now=now)
            count += 1
        except OSError as exc:
            logger.warning("flow_journal_write_failed error=%s", exc.__class__.__name__)
    return count


def read_recent_flow_signals(
    *,
    hours: int = 24,
    symbol: str | None = None,
    base_dir: Path | None = None,
    limit: int = 5000,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Đọc các signal trong vòng N giờ gần đây.

    Quét tối đa 2 file tuần (tuần hiện tại + tuần trước) để cover edge case
    "đang ở thứ 2 sáng, muốn xem 48h".
    """
    cutoff_ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc) - timedelta(hours=max(1, hours))
    sym_filter = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None
    base = base_dir or _journal_dir()

    files_to_scan: list[Path] = []
    ref_now = now or datetime.now(timezone.utc)
    for delta_weeks in (0, 1):
        ts_anchor = ref_now - timedelta(days=7 * delta_weeks)
        files_to_scan.append(_file_for_week(ts_anchor, base_dir=base))

    seen: set[Path] = set()
    out: list[dict[str, Any]] = []
    for p in files_to_scan:
        if p in seen or not p.exists():
            continue
        seen.add(p)
        try:
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    ts_raw = row.get("journaled_at_utc") or row.get("ts") or row.get("timestamp")
                    try:
                        ts_row = datetime.fromisoformat(str(ts_raw)) if ts_raw else None
                    except ValueError:
                        ts_row = None
                    if ts_row is not None:
                        if ts_row.tzinfo is None:
                            ts_row = ts_row.replace(tzinfo=timezone.utc)
                        if ts_row < cutoff_ts:
                            continue
                    if sym_filter and str(row.get("symbol") or "").strip().upper() != sym_filter:
                        continue
                    out.append(row)
                    if len(out) >= int(limit):
                        break
        except OSError as exc:
            logger.warning("flow_journal_read_failed file=%s error=%s", p.name, exc.__class__.__name__)
            continue
        if len(out) >= int(limit):
            break
    out.sort(key=lambda r: str(r.get("journaled_at_utc") or ""), reverse=True)
    return out[: int(limit)]


def prune_old_journal_files(
    *,
    retention_weeks: int | None = None,
    base_dir: Path | None = None,
    now: datetime | None = None,
) -> list[Path]:
    """Xoá file JSONL cũ hơn ``retention_weeks`` tuần.

    Trả về list path đã xoá (chủ yếu cho test/observability).
    """
    weeks = int(retention_weeks) if retention_weeks is not None else _DEFAULT_RETENTION_WEEKS
    weeks = max(1, weeks)
    base = base_dir or _journal_dir()
    if not base.exists():
        return []
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    keep_iso: set[str] = set()
    for d in range(weeks * 7):
        anchor = ts - timedelta(days=d)
        iso_year, iso_week, _ = anchor.isocalendar()
        keep_iso.add(f"{iso_year}W{iso_week:02d}")
    pruned: list[Path] = []
    for p in base.glob("flow_signals_*.jsonl"):
        stem = p.stem.replace("flow_signals_", "")
        if stem not in keep_iso:
            try:
                p.unlink()
                pruned.append(p)
            except OSError as exc:
                logger.warning("flow_journal_prune_failed file=%s error=%s", p.name, exc.__class__.__name__)
    return pruned


def summarize_recent_flow_signals(
    *,
    hours: int = 24,
    base_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tổng hợp nhanh cho dashboard: số signal, % big_boy, top symbol theo intensity."""
    rows = read_recent_flow_signals(hours=hours, base_dir=base_dir, now=now, limit=10_000)
    total = len(rows)
    big = sum(1 for r in rows if bool(r.get("is_big_boy")))
    bullish = sum(1 for r in rows if str(r.get("delta_status") or "") == "bullish")
    bearish = sum(1 for r in rows if str(r.get("delta_status") or "") == "bearish")
    top_by_intensity: dict[str, float] = {}
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        try:
            score = float(r.get("intensity_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score > top_by_intensity.get(sym, -1.0):
            top_by_intensity[sym] = score
    top_sorted = sorted(top_by_intensity.items(), key=lambda kv: kv[1], reverse=True)[:10]
    return {
        "hours": int(hours),
        "total": total,
        "big_boy_count": big,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "top_symbols": [{"symbol": s, "max_intensity": round(score, 2)} for s, score in top_sorted],
    }


__all__ = [
    "append_flow_signal",
    "append_flow_signals_batch",
    "prune_old_journal_files",
    "read_recent_flow_signals",
    "summarize_recent_flow_signals",
]
