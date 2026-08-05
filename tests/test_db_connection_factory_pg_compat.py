from __future__ import annotations

from core.db_connection_factory import PgCompatConnection


class _FakeConn:
    def __init__(self) -> None:
        self.last_sql = ""
        self.last_params = None

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_pg_compat_rewrites_question_placeholders() -> None:
    fake = _FakeConn()
    conn = PgCompatConnection(fake)
    conn.execute("SELECT * FROM t WHERE a=? AND b=?", (1, 2))
    assert fake.last_sql == "SELECT * FROM t WHERE a=%s AND b=%s"
    assert fake.last_params == (1, 2)

