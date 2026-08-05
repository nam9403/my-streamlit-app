from __future__ import annotations

import streamlit as st


def inject_custom_styles() -> None:
    st.markdown(
        """
        <style>
        /* ==== Nền trắng + chữ/số nổi bật (ép sáng, ghi đè dark theme Streamlit) ==== */
        :root {
            color-scheme: light;
        }

        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stHeader"],
        section.main,
        section.main .block-container {
            background-color: #ffffff !important;
            color: #0f172a !important;
        }

        .stApp {
            font-family: Roboto, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .main .block-container {
            max-width: 1080px;
            padding-top: 0.5rem;
            padding-bottom: 1.2rem;
        }

        /* Tiêu đề & văn bản chính */
        h1, h2, h3, h4,
        .stMarkdown h1, .stMarkdown h2, .stMarkdown h3,
        [data-testid="stMarkdownContainer"] h1,
        [data-testid="stMarkdownContainer"] h2,
        [data-testid="stMarkdownContainer"] h3 {
            color: #030712 !important;
            font-weight: 800 !important;
        }

        .stMarkdown p,
        .stMarkdown li,
        .stMarkdown span,
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li {
            color: #0f172a !important;
        }

        .stCaption,
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {
            color: #334155 !important;
            font-weight: 600 !important;
        }

        /* Sidebar trắng */
        div[data-testid="stSidebar"],
        div[data-testid="stSidebar"] > div:first-child {
            background: #ffffff !important;
            border-right: 2px solid #e2e8f0;
        }

        div[data-testid="stSidebar"] h1,
        div[data-testid="stSidebar"] h2,
        div[data-testid="stSidebar"] h3,
        div[data-testid="stSidebar"] label,
        div[data-testid="stSidebar"] p,
        div[data-testid="stSidebar"] .stMarkdown,
        div[data-testid="stSidebar"] span {
            color: #0f172a !important;
            font-weight: 600;
        }

        div[data-testid="stSidebar"] label {
            font-weight: 700 !important;
            color: #1e293b !important;
        }

        /* Số liệu metric — to, đậm, màu đỏ nổi */
        div[data-testid="stMetric"] {
            background: #ffffff !important;
            border-radius: 16px;
            padding: 12px 16px;
            border: 2px solid #e2e8f0;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.08);
        }

        div[data-testid="stMetricLabel"] {
            color: #1e293b !important;
            font-weight: 700 !important;
            font-size: 0.9rem !important;
        }

        div[data-testid="stMetricValue"] {
            color: #b91c1c !important;
            font-weight: 800 !important;
            font-size: 1.85rem !important;
            letter-spacing: -0.02em;
        }

        div[data-testid="stMetricDelta"] svg {
            stroke-width: 2.5;
        }

        /* Nút primary */
        div[data-testid="stSidebar"] .stButton button[kind="primary"],
        .stButton button[kind="primary"] {
            background: linear-gradient(135deg, #dc2626, #b91c1c);
            color: #ffffff !important;
            border: none;
            font-weight: 800;
            border-radius: 999px;
            padding-top: 0.45rem;
            padding-bottom: 0.45rem;
            box-shadow: 0 6px 16px rgba(185, 28, 28, 0.35);
        }

        .stButton button:hover[kind="primary"] {
            background: linear-gradient(135deg, #ef4444, #b91c1c);
            transform: translateY(-1px);
        }

        .stButton button {
            border-radius: 999px;
            border: 2px solid #cbd5e1;
            background: #ffffff !important;
            color: #0f172a !important;
            font-weight: 700;
            padding-top: 0.4rem;
            padding-bottom: 0.4rem;
        }

        .stButton button:hover {
            border-color: #dc2626;
            color: #b91c1c !important;
        }

        /* Input — nền trắng, chữ đậm */
        .stTextInput>div>div>input,
        .stNumberInput input,
        .stSelectbox>div>div>div,
        .stTextArea textarea,
        div[data-testid="stSidebar"] input,
        div[data-testid="stSidebar"] textarea {
            background-color: #ffffff !important;
            color: #0f172a !important;
            font-weight: 600 !important;
            border-radius: 12px;
            border: 2px solid #cbd5e1 !important;
            padding-top: 0.4rem;
            padding-bottom: 0.4rem;
        }

        .stTextInput>div>div>input:focus,
        .stNumberInput input:focus,
        .stSelectbox>div>div>div:focus,
        .stTextArea textarea:focus {
            outline: none;
            border-color: #dc2626 !important;
            box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.2);
            background-color: #ffffff !important;
        }

        /* Bảng dữ liệu */
        div[data-testid="stDataFrame"] {
            background: #ffffff !important;
            border-radius: 14px;
            border: 2px solid #e2e8f0;
            padding-top: 4px;
        }

        div[data-testid="stDataFrame"] table {
            font-size: 14px;
            color: #0f172a !important;
            font-weight: 600;
        }

        div[data-testid="stDataFrame"] thead tr {
            background: #f1f5f9 !important;
            border-bottom: 2px solid #cbd5e1;
        }

        div[data-testid="stDataFrame"] thead th {
            color: #1e293b !important;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        div[data-testid="stDataFrame"] tbody td {
            color: #0f172a !important;
            font-weight: 600;
        }

        div[data-testid="stDataFrame"] tbody tr:nth-child(even) {
            background: #ffffff !important;
        }

        div[data-testid="stDataFrame"] tbody tr:nth-child(odd) {
            background: #f8fafc !important;
        }

        div[data-testid="stDataFrame"] tbody tr:hover {
            background: #fef2f2 !important;
        }

        /* Alert / info boxes */
        [data-testid="stAlert"] {
            border-radius: 12px;
            font-weight: 600;
        }

        /* Box rủi ro & badge */
        .risk-box {
            background: #ffffff;
            color: #0f172a;
            border-radius: 16px;
            padding: 14px;
            border: 2px solid #e2e8f0;
        }

        .badge-ok {
            display: inline-block;
            background: #dcfce7;
            color: #14532d;
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 12px;
            font-weight: 800;
            border: 2px solid #16a34a;
        }

        .badge-warn {
            display: inline-block;
            background: #fee2e2;
            color: #7f1d1d;
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 12px;
            font-weight: 800;
            border: 2px solid #dc2626;
        }

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
        }

        .stTabs [data-baseweb="tab"] {
            background-color: #f1f5f9 !important;
            border-radius: 999px;
            padding: 6px 14px;
            color: #475569 !important;
            font-weight: 700;
            border: 2px solid #cbd5e1;
            min-height: 38px;
        }

        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background-color: #ffffff !important;
            color: #b91c1c !important;
            border-color: #dc2626;
            font-weight: 800;
        }

        .js-plotly-plot .plotly .main-svg {
            background-color: #ffffff !important;
        }

        .streamlit-expanderHeader {
            background: #ffffff !important;
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            color: #0f172a !important;
            font-weight: 700 !important;
        }

        [data-testid="stExpander"] .streamlit-expanderContent {
            background: #ffffff !important;
            color: #0f172a !important;
        }

        .quick-card {
            background: #ffffff;
            border: 2px solid #e2e8f0;
            border-radius: 16px;
            padding: 12px 14px;
            min-height: 118px;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
        }

        .quick-title {
            color: #475569;
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 6px;
        }

        .quick-value {
            color: #b91c1c;
            font-size: 26px;
            font-weight: 800;
            line-height: 1.2;
        }

        .quick-sub {
            color: #334155;
            font-size: 13px;
            font-weight: 600;
            margin-top: 6px;
        }

        .quick-pill {
            display: inline-block;
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 12px;
            font-weight: 800;
            border: 2px solid #cbd5e1;
            margin-top: 4px;
            color: #0f172a;
        }

        /* Siêu thị: dải nhãn kệ */
        .shop-aisle-band {
            margin: 0.35rem 0 0.5rem 0;
        }

        .shop-aisle-inner {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 0.35rem 0.6rem;
            background: #ffffff;
            border: 2px solid #e2e8f0;
            border-left: 5px solid #dc2626;
            border-radius: 14px;
            padding: 0.5rem 0.9rem;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
        }

        .shop-aisle-dot {
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: #dc2626;
            display: inline-block;
            flex-shrink: 0;
            margin-top: 2px;
        }

        .shop-aisle-title {
            font-weight: 800;
            font-size: 1rem;
            color: #030712;
            letter-spacing: -0.01em;
        }

        .shop-aisle-sub {
            margin: 0;
            width: 100%;
            flex-basis: 100%;
            padding-left: 1.1rem;
            font-size: 0.85rem;
            color: #334155;
            font-weight: 600;
            line-height: 1.4;
        }

        .shop-welcome-wrap {
            background: #ffffff;
            border: 2px solid #e2e8f0;
            border-radius: 18px;
            padding: 12px 14px 14px 14px;
            margin-bottom: 0.35rem;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
        }

        .shop-welcome-head {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            margin-bottom: 10px;
        }

        .shop-welcome-title {
            font-size: 1.08rem;
            font-weight: 800;
            color: #030712;
        }

        .shop-welcome-badges {
            font-size: 0.78rem;
            font-weight: 800;
            color: #1e293b;
            background: #f1f5f9;
            border-radius: 999px;
            padding: 4px 12px;
            border: 2px solid #cbd5e1;
        }

        .shop-step-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
        }

        @media (max-width: 900px) {
            .shop-step-grid {
                grid-template-columns: 1fr;
            }
        }

        .shop-step-card {
            background: #ffffff;
            border: 2px solid #e2e8f0;
            border-radius: 16px;
            padding: 10px 12px;
            min-height: 108px;
        }

        .shop-step-num {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 26px;
            height: 26px;
            border-radius: 999px;
            background: #b91c1c;
            color: #fff;
            font-size: 13px;
            font-weight: 800;
            margin-bottom: 6px;
        }

        .shop-step-title {
            font-size: 0.9rem;
            font-weight: 800;
            color: #030712;
            margin-bottom: 4px;
        }

        .shop-step-body {
            font-size: 0.82rem;
            color: #334155;
            font-weight: 600;
            line-height: 1.45;
        }

        .quick-card.status-buy {
            border-color: #16a34a;
            box-shadow: 0 0 0 1px #16a34a33 inset;
        }

        .quick-card.status-hold {
            border-color: #d97706;
            box-shadow: 0 0 0 1px #d9770633 inset;
        }

        .quick-card.status-watch {
            border-color: #dc2626;
            box-shadow: 0 0 0 1px #dc262633 inset;
        }

        /* Radio / toggle labels */
        .stRadio label,
        .stCheckbox label,
        .stToggle label {
            color: #0f172a !important;
            font-weight: 700 !important;
        }

        /* Responsive */
        @media (max-width: 1400px) {
            .main .block-container {
                max-width: 100%;
                padding-left: 0.7rem;
                padding-right: 0.7rem;
            }
            div[data-testid="stMetric"] {
                padding: 8px 10px;
                border-radius: 14px;
            }
        }

        @media (max-width: 1080px) {
            .stTabs [data-baseweb="tab-list"] {
                flex-wrap: wrap;
                row-gap: 6px;
            }
            .stTabs [data-baseweb="tab"] {
                min-height: 34px;
                padding: 4px 10px;
            }
            div[data-testid="stHorizontalBlock"] {
                flex-wrap: wrap;
                gap: 0.5rem;
            }
            div[data-testid="stHorizontalBlock"] > div {
                min-width: 220px;
                flex: 1 1 220px;
            }
            div[data-testid="stMetricValue"] {
                font-size: 1.5rem !important;
                line-height: 1.15;
                word-break: break-word;
            }
            div[data-testid="stMetricLabel"] {
                font-size: 0.85rem !important;
            }
        }

        @media (max-width: 1280px) {
            div[data-testid="stSidebar"] .block-container {
                padding-left: 0.6rem;
                padding-right: 0.6rem;
            }
            div[data-testid="stSidebar"] .stTextInput input,
            div[data-testid="stSidebar"] .stNumberInput input,
            div[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div {
                min-height: 34px;
                font-size: 0.92rem;
            }
            div[data-testid="stSidebar"] .stButton button {
                min-height: 34px;
                padding: 0.25rem 0.65rem;
                font-size: 0.88rem;
                white-space: normal;
                line-height: 1.2;
            }
            div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
                flex-wrap: wrap;
                gap: 0.35rem;
            }
            div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div {
                min-width: 120px;
                flex: 1 1 120px;
            }
        }

        @media (max-width: 980px) {
            div[data-testid="stSidebar"] label,
            div[data-testid="stSidebar"] p {
                font-size: 0.88rem !important;
            }
            div[data-testid="stSidebar"] .stMarkdown {
                font-size: 0.88rem;
            }
            div[data-testid="stSidebar"] .stButton button {
                border-radius: 12px;
            }
        }

        </style>
        """,
        unsafe_allow_html=True,
    )
