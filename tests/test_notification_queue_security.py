"""
Hàng đợi notification: không lưu credential trong payload + claim nguyên tử
(status 'processing', PostgreSQL dùng SELECT ... FOR UPDATE SKIP LOCKED).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core import notification_queue_repository as repo


def _init(pl, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()


def _insert_job(pl, *, user_id: str, kind: str, payload_json: str, status: str = "pending", updated_at: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with pl._conn() as c:
        c.execute(
            """
            INSERT INTO notification_queue(user_id, kind, payload_json, attempts, status, last_error, next_retry_at, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, '', ?, ?, ?)
            """,
            (user_id, kind, payload_json, status, now, now, updated_at or now),
        )


def test_enqueue_strips_credentials_from_payload(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    _init(pl, tmp_path, monkeypatch)
    pl.enqueue_notification(
        "u1",
        "text",
        {
            "text": "hello",
            "telegram_bot_token": "SECRET_TOKEN",
            "telegram_chat_id": "12345",
            "smtp_password": "SECRET_PASS",
            "smtp_user": "mailer",
            "webhook_url": "https://hook",
        },
        delay_seconds=1,
    )

    with pl._conn() as c:
        raw = str(c.execute("SELECT payload_json FROM notification_queue").fetchone()["payload_json"])
    stored = json.loads(raw)
    assert stored == {"text": "hello"}
    assert "SECRET_TOKEN" not in raw
    assert "SECRET_PASS" not in raw


def test_dispatch_resolves_credentials_from_secret_store_not_payload(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    _init(pl, tmp_path, monkeypatch)
    pl.save_secret("u1", "telegram_bot_token", "VAULT_TOKEN")
    pl.save_secret("u1", "telegram_chat_id", "VAULT_CHAT")

    # Row cũ (trước migration) còn sót credential trong payload — phải bị bỏ qua.
    _insert_job(
        pl,
        user_id="u1",
        kind="text",
        payload_json='{"text":"hi","telegram_bot_token":"STALE_PAYLOAD_TOKEN","telegram_chat_id":"999"}',
    )

    seen: list[dict] = []

    def fake_dispatch(text, **kwargs):
        seen.append({"text": text, **kwargs})
        return {"sent": 1, "failed": 0}

    monkeypatch.setattr(pl, "dispatch_text_notifications", fake_dispatch)
    stat = pl.process_notification_queue(max_jobs=5)

    assert int(stat["sent"]) == 1
    assert seen[0]["text"] == "hi"
    assert seen[0]["telegram_bot_token"] == "VAULT_TOKEN"
    assert seen[0]["telegram_chat_id"] == "VAULT_CHAT"
    with pl._conn() as c:
        row = c.execute("SELECT status FROM notification_queue").fetchone()
    assert str(row["status"]) == "done"


def test_claim_moves_job_to_processing_atomically_no_double_pick(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    _init(pl, tmp_path, monkeypatch)
    _insert_job(pl, user_id="u1", kind="text", payload_json='{"text":"a"}')
    _insert_job(pl, user_id="u1", kind="text", payload_json='{"text":"b"}')

    first = repo.claim_pending_notifications(
        conn_factory=pl._conn, utcnow_iso=pl._utcnow_iso, max_jobs=1, backend="sqlite"
    )
    assert len(first) == 1
    with pl._conn() as c:
        row = c.execute("SELECT status FROM notification_queue WHERE id=?", (int(first[0]["id"]),)).fetchone()
    assert str(row["status"]) == "processing"

    # Worker thứ hai quét ngay sau đó: không được nhặt lại job đã claim.
    second = repo.claim_pending_notifications(
        conn_factory=pl._conn, utcnow_iso=pl._utcnow_iso, max_jobs=10, backend="sqlite"
    )
    second_ids = {int(r["id"]) for r in second}
    assert int(first[0]["id"]) not in second_ids
    assert len(second) == 1

    # Không còn job pending → lần ba trắng tay.
    third = repo.claim_pending_notifications(
        conn_factory=pl._conn, utcnow_iso=pl._utcnow_iso, max_jobs=10, backend="sqlite"
    )
    assert third == []


def test_postgresql_claim_uses_for_update_skip_locked() -> None:
    executed: list[str] = []

    class _FakeConn:
        def execute(self, sql: str, params=None):
            executed.append(" ".join(sql.split()))
            return self

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    repo.claim_pending_notifications(
        conn_factory=_FakeConn,
        utcnow_iso=lambda: "2026-01-01T00:00:00+00:00",
        max_jobs=5,
        backend="postgresql",
    )
    sql = executed[0]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "SET status='processing'" in sql
    assert "RETURNING" in sql


def test_stale_processing_job_is_requeued_and_resent(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    _init(pl, tmp_path, monkeypatch)
    stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=repo.PROCESSING_LEASE_SECONDS + 60)).isoformat()
    _insert_job(pl, user_id="u1", kind="text", payload_json='{"text":"stuck"}', status="processing", updated_at=stale_ts)

    monkeypatch.setattr(pl, "dispatch_text_notifications", lambda *a, **k: {"sent": 1, "failed": 0})
    stat = pl.process_notification_queue(max_jobs=5)

    assert int(stat["processed"]) == 1
    assert int(stat["sent"]) == 1
    with pl._conn() as c:
        row = c.execute("SELECT status FROM notification_queue").fetchone()
    assert str(row["status"]) == "done"


def test_fresh_processing_job_is_not_stolen_by_other_worker(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    _init(pl, tmp_path, monkeypatch)
    _insert_job(pl, user_id="u1", kind="text", payload_json='{"text":"in-flight"}', status="processing")

    monkeypatch.setattr(pl, "dispatch_text_notifications", lambda *a, **k: {"sent": 1, "failed": 0})
    stat = pl.process_notification_queue(max_jobs=5)

    assert int(stat["processed"]) == 0
    with pl._conn() as c:
        row = c.execute("SELECT status FROM notification_queue").fetchone()
    assert str(row["status"]) == "processing"


def test_retry_after_dispatch_error_returns_job_to_pending(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    _init(pl, tmp_path, monkeypatch)
    _insert_job(pl, user_id="u1", kind="text", payload_json='{"text":"x"}')

    monkeypatch.setattr(
        pl,
        "dispatch_text_notifications",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("telegram down")),
    )
    stat = pl.process_notification_queue(max_jobs=5)

    assert int(stat["retried"]) == 1
    with pl._conn() as c:
        row = c.execute("SELECT status, attempts FROM notification_queue").fetchone()
    # Không kẹt ở 'processing': lỗi gửi → về 'pending' chờ backoff.
    assert str(row["status"]) == "pending"
    assert int(row["attempts"]) == 1
