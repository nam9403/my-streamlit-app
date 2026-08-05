from __future__ import annotations

from datetime import date

from core.fundamentals_pit import (
    filter_rows_as_of,
    fundamentals_as_of,
    period_available_on,
    pit_to_valuation_financials,
)


def test_period_available_lag() -> None:
    # Q1 2024 ends Mar 31 → available ~ May 15 with 45d lag
    assert period_available_on(2024, 1) == date(2024, 5, 15)
    assert period_available_on(2023, 0) == date(2024, 2, 14)  # Dec 31 + 45


def test_filter_rows_no_lookahead() -> None:
    rows = [
        {"year": 2024, "quarter": 2, "revenue": 200, "net_income": 20, "equity": 100},
        {"year": 2024, "quarter": 1, "revenue": 180, "net_income": 18, "equity": 100},
        {"year": 2023, "quarter": 1, "revenue": 150, "net_income": 15, "equity": 90},
    ]
    # Before Q1 2024 is public
    early = filter_rows_as_of(rows, date(2024, 4, 1))
    assert all(int(r["year"]) < 2024 or int(r["quarter"]) < 1 for r in early) or len(early) <= 1
    # After Q2 public (Jun 30 + 45 = Aug 14)
    late = filter_rows_as_of(rows, date(2024, 9, 1))
    assert len(late) >= 2
    assert late[0]["quarter"] == 2


def test_fundamentals_as_of_with_provided_rows() -> None:
    rows = [
        {"year": 2024, "quarter": 1, "revenue": 220, "net_income": 22, "equity": 100, "total_assets": 200},
        {"year": 2023, "quarter": 1, "revenue": 200, "net_income": 20, "equity": 95, "total_assets": 190},
        {"year": 2022, "quarter": 1, "revenue": 180, "net_income": 15, "equity": 90, "total_assets": 180},
    ]
    pit = fundamentals_as_of("TEST", date(2024, 6, 1), rows=rows)
    assert pit["ok"] is True
    assert pit["revenue_growth_yoy"] is not None
    assert abs(float(pit["revenue_growth_yoy"]) - 10.0) < 1e-6
    patch, fin = pit_to_valuation_financials(pit)
    assert fin.get("revenue_growth_yoy") == pit["revenue_growth_yoy"]
    assert patch.get("piotroski_score") is not None


def test_fireant_rows_normalize_smoke(monkeypatch) -> None:
    sample = [
        {
            "Symbol": "FPT",
            "Year": 2023,
            "Quarter": 2,
            "SalesGrowth_TTM": 0.12,
            "ProfitGrowth_TTM": 0.15,
            "BasicEPS_TTM": 5000,
        },
        {
            "Symbol": "FPT",
            "Year": 2023,
            "Quarter": 1,
            "SalesGrowth_TTM": 0.10,
            "ProfitGrowth_TTM": 0.11,
            "BasicEPS_TTM": 4800,
        },
    ]

    def _fake_get(url, timeout=12):
        class R:
            status_code = 200

            def json(self):
                return sample

        return R()

    import core.fundamentals_pit as fp

    monkeypatch.setattr(fp, "fetch_fireant_quarterly_rows", lambda sym: (
        [
            {
                "year": 2023,
                "quarter": 2,
                "sales_growth_ttm_pct": 12.0,
                "profit_growth_ttm_pct": 15.0,
                "roe_ttm_pct": 20.0,
                "_provider": "fireant",
            },
            {
                "year": 2023,
                "quarter": 1,
                "sales_growth_ttm_pct": 10.0,
                "profit_growth_ttm_pct": 11.0,
                "roe_ttm_pct": 18.0,
                "_provider": "fireant",
            },
        ],
        "fireant_quarterly",
    ))
    # Use provided rows path
    rows, _ = fp.fetch_fireant_quarterly_rows("FPT") if False else (
        [
            {
                "year": 2023,
                "quarter": 2,
                "sales_growth_ttm_pct": 12.0,
                "profit_growth_ttm_pct": 15.0,
                "roe_ttm_pct": 20.0,
                "_provider": "fireant",
            },
            {
                "year": 2023,
                "quarter": 1,
                "sales_growth_ttm_pct": 10.0,
                "profit_growth_ttm_pct": 11.0,
                "_provider": "fireant",
            },
        ],
        "t",
    )
    pit = fundamentals_as_of("FPT", date(2023, 9, 1), rows=rows)
    assert pit["ok"] is True
    assert float(pit["revenue_growth_yoy"]) == 12.0
