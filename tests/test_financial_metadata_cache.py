"""Cache metadata JSON / subtype map theo mtime — không đổi hành vi chỉ giảm đọc lặp."""

from __future__ import annotations

from unittest.mock import patch

from scrapers import financial_data as fd


def test_universe_subtype_map_reuses_build_when_mtime_unchanged() -> None:
    fd.clear_stock_metadata_cache()
    fixed_mtime = 1_700_000_000.0
    meta = {"FPT": {"industry_subtype": "tech"}}
    with (
        patch.object(fd, "_meta_path_mtime", return_value=fixed_mtime),
        patch.object(fd, "_load_stock_metadata", return_value=meta),
    ):
        a = fd.universe_subtype_map()
        b = fd.universe_subtype_map()
    assert a is b
    assert a.get("FPT") == "tech"


def test_peer_symbols_same_cluster_order_matches_legacy_scan() -> None:
    fd.clear_stock_metadata_cache()
    meta = {
        "ZZZ": {"industry_cluster": "steel"},
        "AAA": {"industry_cluster": "steel"},
        "BBB": {"industry_cluster": "steel"},
        "CCC": {"other": 1},
    }
    with patch.object(fd, "_load_stock_metadata", return_value=meta):
        assert fd.peer_symbols_same_cluster("AAA", limit=10) == ["AAA", "BBB", "ZZZ"]
        assert fd.peer_symbols_same_cluster("CCC", limit=10) == ["CCC"]


def test_peer_symbols_same_cluster_reuses_buckets_same_mtime() -> None:
    fd.clear_stock_metadata_cache()
    mt = 99.0
    meta = {"X": {"industry_cluster": "k"}, "Y": {"industry_cluster": "k"}}
    builds: list[int] = []

    real_build = fd._build_peer_cluster_buckets

    def wrapped(m: dict) -> dict:
        builds.append(1)
        return real_build(m)

    with (
        patch.object(fd, "_meta_path_mtime", return_value=mt),
        patch.object(fd, "_load_stock_metadata", return_value=meta),
        patch.object(fd, "_build_peer_cluster_buckets", side_effect=wrapped),
    ):
        fd.peer_symbols_same_cluster("X", limit=5)
        fd.peer_symbols_same_cluster("Y", limit=5)
    assert len(builds) == 1
