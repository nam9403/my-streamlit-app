"""In-process TTL cache for list_tradable_vn_symbols (giảm đọc lặp khi scan / Auto Pilot)."""

from __future__ import annotations

from unittest.mock import patch

from scrapers import vn_listing as vl


def test_list_tradable_mem_cache_reuses_listing_load() -> None:
    vl.clear_tradable_vn_symbol_cache()
    calls: list[int] = []

    def fake_load() -> tuple[list[str], str]:
        calls.append(1)
        return (["ZZZ999"], "ok")

    with (
        patch.object(vl, "load_or_refresh_listing_cache", side_effect=fake_load),
        patch.object(vl, "_load_metadata_symbols", return_value=[]),
        patch.object(vl, "_load_extra_txt", return_value=[]),
    ):
        a = vl.list_tradable_vn_symbols()
        b = vl.list_tradable_vn_symbols()
    assert len(calls) == 1
    assert a == b == ["ZZZ999"]


def test_clear_tradable_invalidates_mem_cache() -> None:
    vl.clear_tradable_vn_symbol_cache()
    calls: list[int] = []

    def fake_load() -> tuple[list[str], str]:
        calls.append(1)
        return (["AAA"], "")

    with (
        patch.object(vl, "load_or_refresh_listing_cache", side_effect=fake_load),
        patch.object(vl, "_load_metadata_symbols", return_value=[]),
        patch.object(vl, "_load_extra_txt", return_value=[]),
    ):
        assert vl.list_tradable_vn_symbols() == ["AAA"]
        vl.clear_tradable_vn_symbol_cache()
        assert vl.list_tradable_vn_symbols() == ["AAA"]
    assert len(calls) == 2


def test_tradable_vn_symbol_count_uses_mem_without_second_listing_load() -> None:
    vl.clear_tradable_vn_symbol_cache()
    calls: list[int] = []

    def fake_load() -> tuple[list[str], str]:
        calls.append(1)
        return (["ZZZ999"], "ok")

    with (
        patch.object(vl, "load_or_refresh_listing_cache", side_effect=fake_load),
        patch.object(vl, "_load_metadata_symbols", return_value=[]),
        patch.object(vl, "_load_extra_txt", return_value=[]),
    ):
        assert vl.list_tradable_vn_symbols() == ["ZZZ999"]
        assert vl.tradable_vn_symbol_count() == 1
        assert vl.tradable_vn_symbol_count() == 1
    assert len(calls) == 1
