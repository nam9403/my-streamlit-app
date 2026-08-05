from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)
MAX_RETRY_ATTEMPTS: int = 5
BACKOFF_BASE_SECONDS: int = 60
BACKOFF_CAP_SECONDS: int = 15 * 60

# Khóa credential/cấu hình kênh gửi — TUYỆT ĐỐI không được nằm trong payload_json.
# Hàng đợi chỉ giữ user_id + nội dung thô; credential được resolve ngược từ kho
# secret mã hóa (theo user_id) tại thời điểm gửi.
CREDENTIAL_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "telegram_bot_token",
        "telegram_chat_id",
        "webhook_url",
        "email_to",
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_password",
        "smtp_from",
    }
)

# Job kẹt ở 'processing' quá lease này (worker chết giữa chừng) sẽ được trả về 'pending'.
PROCESSING_LEASE_SECONDS: int = 600


def sanitize_notification_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Loại mọi credential/cấu hình kênh khỏi payload trước khi ghi vào hàng đợi."""
    return {k: v for k, v in dict(payload or {}).items() if k not in CREDENTIAL_PAYLOAD_KEYS}


def _next_retry_delay_seconds(attempts: int) -> int:
    step = max(1, int(attempts))
    return int(min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (step - 1))))


def _mark_retry_or_failed(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    jid: int,
    attempts: int,
    error: str,
) -> tuple[int, int]:
    if attempts >= MAX_RETRY_ATTEMPTS:
        with conn_factory() as c:
            c.execute(
                "UPDATE notification_queue SET status='failed', attempts=?, last_error=?, updated_at=? WHERE id=?",
                (attempts, error, utcnow_iso(), jid),
            )
        return (0, 1)

    next_retry = datetime.now(timezone.utc) + timedelta(seconds=_next_retry_delay_seconds(attempts))
    with conn_factory() as c:
        c.execute(
            """
            UPDATE notification_queue
            SET status='pending', attempts=?, last_error=?, next_retry_at=?, updated_at=?
            WHERE id=?
            """,
            (attempts, f"retry_scheduled:{error}", next_retry.isoformat(), utcnow_iso(), jid),
        )
    return (1, 0)


def enqueue_notification(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    kind: str,
    payload: dict[str, Any],
    delay_seconds: int = 60,
) -> None:
    """
    Ghi job vào hàng đợi. Payload được sanitize tại biên (defense-in-depth):
    dù caller có lỡ truyền token Telegram / mật khẩu SMTP, chúng KHÔNG bao giờ
    được persist — worker sẽ resolve credential từ kho secret theo user_id khi gửi.
    """
    now = datetime.now(timezone.utc)
    next_retry = now + timedelta(seconds=max(1, int(delay_seconds)))
    safe_payload = sanitize_notification_payload(payload)
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO notification_queue(user_id, kind, payload_json, attempts, status, last_error, next_retry_at, created_at, updated_at)
            VALUES (?, ?, ?, 0, 'pending', '', ?, ?, ?)
            """,
            (user_id, kind, json.dumps(safe_payload, ensure_ascii=False), next_retry.isoformat(), now.isoformat(), now.isoformat()),
        )


def _requeue_stale_processing_jobs(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
) -> None:
    """Worker chết giữa chừng để lại job 'processing' — quá lease thì trả về 'pending'."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=PROCESSING_LEASE_SECONDS)).isoformat()
    with conn_factory() as c:
        c.execute(
            """
            UPDATE notification_queue
            SET status='pending', last_error='requeued:stale_processing', updated_at=?
            WHERE status='processing' AND updated_at<=?
            """,
            (utcnow_iso(), cutoff),
        )


def claim_pending_notifications(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    max_jobs: int,
    backend: str = "sqlite",
) -> list[dict[str, Any]]:
    """
    Chiếm quyền xử lý job một cách NGUYÊN TỬ: chọn job pending đến hạn và chuyển
    ngay sang 'processing' trong cùng một statement/transaction, nên nhiều worker
    song song không bao giờ nhặt trùng một job.

    - PostgreSQL: `SELECT ... FOR UPDATE SKIP LOCKED` trong subquery — worker khác
      đang giữ row-lock sẽ bị bỏ qua thay vì chờ, không trùng cũng không nghẽn.
    - SQLite: một UPDATE duy nhất với guard `status='pending'`; SQLite chỉ có một
      writer tại một thời điểm nên UPDATE này là nguyên tử.
    """
    now = datetime.now(timezone.utc).isoformat()
    if str(backend).strip().lower() == "postgresql":
        claim_sql = """
            UPDATE notification_queue
            SET status='processing', updated_at=?
            WHERE id IN (
                SELECT id FROM notification_queue
                WHERE status='pending' AND next_retry_at<=?
                ORDER BY id ASC
                LIMIT ?
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, user_id, kind, payload_json, attempts
            """
    else:
        claim_sql = """
            UPDATE notification_queue
            SET status='processing', updated_at=?
            WHERE status='pending' AND id IN (
                SELECT id FROM notification_queue
                WHERE status='pending' AND next_retry_at<=?
                ORDER BY id ASC
                LIMIT ?
            )
            RETURNING id, user_id, kind, payload_json, attempts
            """
    with conn_factory() as c:
        rows = c.execute(claim_sql, (utcnow_iso(), now, int(max_jobs))).fetchall()
    return [dict(r) for r in rows]


def process_notification_queue(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    short_error: Callable[[str, Exception], str],
    dispatch_text_notifications: Callable[..., dict[str, Any]],
    dispatch_alert_notifications: Callable[..., dict[str, Any]],
    resolve_channels: Callable[[str], dict[str, Any]],
    max_jobs: int = 20,
    backend: str = "sqlite",
) -> dict[str, int]:
    """
    Gửi các job đã claim. Credential KHÔNG đọc từ payload — luôn resolve ngược
    từ kho secret mã hóa theo user_id qua `resolve_channels` tại thời điểm gửi.
    """
    sent = 0
    failed = 0
    retried = 0
    _requeue_stale_processing_jobs(conn_factory=conn_factory, utcnow_iso=utcnow_iso)
    jobs = claim_pending_notifications(
        conn_factory=conn_factory,
        utcnow_iso=utcnow_iso,
        max_jobs=int(max_jobs),
        backend=backend,
    )
    for j in jobs:
        jid = int(j["id"])
        kind = str(j["kind"] or "")
        attempts = int(j["attempts"] or 0)
        try:
            payload = json.loads(str(j["payload_json"] or "{}"))
        except ValueError as e:
            attempts += 1
            logger.warning("process_notification_queue invalid payload id=%s error=%s", jid, short_error("payload_json", e))
            with conn_factory() as c:
                c.execute(
                    "UPDATE notification_queue SET status='failed', attempts=?, last_error=?, updated_at=? WHERE id=?",
                    (attempts, short_error("invalid_payload", e), utcnow_iso(), jid),
                )
            failed += 1
            continue

        ok = False
        fail_reason = "delivery_failed"
        try:
            # Credential lấy từ kho secret mã hóa theo user_id; payload cũ (nếu còn
            # sót token từ dữ liệu trước migration) bị bỏ qua hoàn toàn.
            channels = dict(resolve_channels(str(j["user_id"])) or {})
            if kind == "text":
                stat = dispatch_text_notifications(
                    payload.get("text", ""),
                    telegram_bot_token=str(channels.get("telegram_bot_token", "") or ""),
                    telegram_chat_id=str(channels.get("telegram_chat_id", "") or ""),
                    webhook_url=str(channels.get("webhook_url", "") or ""),
                    email_to=str(channels.get("email_to", "") or ""),
                    smtp_host=str(channels.get("smtp_host", "") or ""),
                    smtp_port=int(channels.get("smtp_port", 587) or 587),
                    smtp_user=str(channels.get("smtp_user", "") or ""),
                    smtp_password=str(channels.get("smtp_password", "") or ""),
                    smtp_from=str(channels.get("smtp_from", "") or ""),
                )
                # No configured delivery channel should be treated as non-failing no-op.
                ok = int(stat.get("failed") or 0) == 0
            elif kind == "alerts":
                stat = dispatch_alert_notifications(
                    str(j["user_id"]),
                    payload.get("fired_alerts", []),
                    telegram_bot_token=str(channels.get("telegram_bot_token", "") or ""),
                    telegram_chat_id=str(channels.get("telegram_chat_id", "") or ""),
                )
                # Alert dispatch can be intentionally skipped when channels are not configured.
                ok = int(stat.get("failed") or 0) == 0
            else:
                fail_reason = "unsupported_kind"
        except Exception as e:
            logger.warning("process_notification_queue dispatch failed id=%s error=%s", jid, short_error("dispatch", e))
            fail_reason = short_error("dispatch", e)
            ok = False

        if ok:
            with conn_factory() as c:
                c.execute(
                    "UPDATE notification_queue SET status='done', updated_at=? WHERE id=?",
                    (utcnow_iso(), jid),
                )
            sent += 1
        else:
            attempts += 1
            if fail_reason == "unsupported_kind":
                with conn_factory() as c:
                    c.execute(
                        "UPDATE notification_queue SET status='failed', attempts=?, last_error=?, updated_at=? WHERE id=?",
                        (attempts, fail_reason, utcnow_iso(), jid),
                    )
                failed += 1
                continue
            retried_inc, failed_inc = _mark_retry_or_failed(
                conn_factory=conn_factory,
                utcnow_iso=utcnow_iso,
                jid=jid,
                attempts=attempts,
                error=fail_reason,
            )
            retried += retried_inc
            failed += failed_inc
    return {"sent": sent, "failed": failed, "retried": retried, "processed": len(jobs)}


def get_notification_queue_diagnostics(*, conn_factory: Callable[[], Any], limit: int = 20) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 200))
    with conn_factory() as c:
        rows = c.execute(
            """
            SELECT id, user_id, kind, attempts, status, last_error, next_retry_at, updated_at
            FROM notification_queue
            ORDER BY
                CASE status WHEN 'failed' THEN 0 WHEN 'processing' THEN 1 WHEN 'pending' THEN 2 WHEN 'done' THEN 3 ELSE 4 END ASC,
                updated_at DESC,
                id DESC
            LIMIT ?
            """,
            (cap,),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "user_id": str(r["user_id"] or ""),
            "kind": str(r["kind"] or ""),
            "attempts": int(r["attempts"] or 0),
            "status": str(r["status"] or ""),
            "last_error": str(r["last_error"] or ""),
            "next_retry_at": str(r["next_retry_at"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def retry_failed_notifications(*, conn_factory: Callable[[], Any], utcnow_iso: Callable[[], str], max_rows: int = 20) -> int:
    cap = max(1, min(int(max_rows), 500))
    now = utcnow_iso()
    with conn_factory() as c:
        ids = [int(r["id"]) for r in c.execute(
            "SELECT id FROM notification_queue WHERE status='failed' ORDER BY id DESC LIMIT ?",
            (cap,),
        ).fetchall()]
        if not ids:
            return 0
        q_marks = ",".join("?" for _ in ids)
        c.execute(
            f"""
            UPDATE notification_queue
            SET status='pending', attempts=0, last_error='', next_retry_at=?, updated_at=?
            WHERE id IN ({q_marks})
            """,
            (now, now, *ids),
        )
    return len(ids)


def get_notification_fail_reason_summary(
    *,
    conn_factory: Callable[[], Any],
    days: int = 14,
    limit: int = 10,
) -> list[dict[str, Any]]:
    d = max(1, min(int(days), 90))
    cap = max(1, min(int(limit), 50))
    since = (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()
    with conn_factory() as c:
        rows = c.execute(
            """
            SELECT last_error, COUNT(*) AS n
            FROM notification_queue
            WHERE status='failed' AND updated_at>=?
            GROUP BY last_error
            ORDER BY n DESC, last_error ASC
            LIMIT ?
            """,
            (since, cap),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        raw = str(r["last_error"] or "").strip()
        if not raw:
            reason = "unknown"
        elif ":" in raw:
            reason = raw.split(":", 1)[0].strip().lower() or "unknown"
        else:
            reason = raw.strip().lower()
        out.append({"reason": reason, "count": int(r["n"] or 0), "sample_error": raw[:120]})
    return out


def get_notification_retry_tier_summary(
    *,
    conn_factory: Callable[[], Any],
    days: int = 14,
    limit: int = 20,
) -> list[dict[str, Any]]:
    d = max(1, min(int(days), 90))
    cap = max(1, min(int(limit), 50))
    since = (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()
    with conn_factory() as c:
        rows = c.execute(
            """
            SELECT status, attempts, COUNT(*) AS n
            FROM notification_queue
            WHERE updated_at>=?
            GROUP BY status, attempts
            ORDER BY n DESC, status ASC, attempts DESC
            """,
            (since,),
        ).fetchall()

    bucket: dict[tuple[str, str], int] = {}
    for r in rows:
        status = str(r["status"] or "").strip().lower() or "unknown"
        attempts = int(r["attempts"] or 0)
        if attempts <= 0:
            tier = "t0"
        elif attempts <= 2:
            tier = "t1_2"
        elif attempts <= 4:
            tier = "t3_4"
        else:
            tier = "t5_plus"
        key = (status, tier)
        bucket[key] = int(bucket.get(key, 0)) + int(r["n"] or 0)

    out = [
        {"status": status, "retry_tier": tier, "count": count}
        for (status, tier), count in sorted(bucket.items(), key=lambda x: (-x[1], x[0][0], x[0][1]))
    ]
    return out[:cap]


def get_notification_runtime_health(
    *,
    conn_factory: Callable[[], Any],
) -> dict[str, float | int]:
    with conn_factory() as c:
        row_pending = c.execute("SELECT COUNT(*) AS n FROM notification_queue WHERE status='pending'").fetchone()
        row_failed = c.execute("SELECT COUNT(*) AS n FROM notification_queue WHERE status='failed'").fetchone()
        row_high_retry = c.execute(
            "SELECT COUNT(*) AS n FROM notification_queue WHERE status IN ('pending','failed') AND attempts>=3"
        ).fetchone()
        try:
            row_oldest = c.execute(
                """
                SELECT COALESCE(MAX((julianday('now') - julianday(next_retry_at)) * 24.0 * 60.0), 0.0) AS age_m
                FROM notification_queue
                WHERE status='pending'
                """
            ).fetchone()
        except Exception:
            row_oldest = c.execute(
                """
                SELECT COALESCE(MAX(EXTRACT(EPOCH FROM (NOW() - CAST(next_retry_at AS TIMESTAMPTZ))) / 60.0), 0.0) AS age_m
                FROM notification_queue
                WHERE status='pending'
                """
            ).fetchone()
        pending = int(row_pending["n"]) if row_pending is not None else 0
        failed = int(row_failed["n"]) if row_failed is not None else 0
        high_retry = int(row_high_retry["n"]) if row_high_retry is not None else 0
        oldest_pending_age_minutes = float(row_oldest["age_m"]) if row_oldest is not None else 0.0
    queue_total = pending + failed
    high_retry_ratio = (high_retry / queue_total) if queue_total > 0 else 0.0
    return {
        "pending_jobs": pending,
        "failed_jobs": failed,
        "high_retry_jobs": high_retry,
        "high_retry_ratio": round(high_retry_ratio, 4),
        "oldest_pending_age_minutes": round(max(0.0, oldest_pending_age_minutes), 2),
    }
