from __future__ import annotations

import streamlit as st


def apply_app_style() -> None:
    """Apply a small, stable layer of product styling over the native theme."""
    st.html(
        """
        <style>
        /* Keep the interface focused and phone-like on large displays. */
        .stMainBlockContainer {
            max-width: 46rem;
            padding-top: 2.25rem;
            padding-bottom: 5rem;
        }

        /* A quiet canvas and crisp type hierarchy. */
        .stApp {
            background:
                radial-gradient(circle at 50% -12rem, #f2f7ff 0, #ffffff 28rem);
        }
        h1, h2, h3, p, label, button, input {
            letter-spacing: -0.012em;
        }
        h1 { letter-spacing: -0.035em; }
        h2, h3 { letter-spacing: -0.025em; }
        [data-testid="stCaptionContainer"] { color: #6e6e73; }

        /* Soft cards instead of dashboard-style boxes. */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: rgba(0, 0, 0, 0.08);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.025),
                        0 10px 30px rgba(0, 0, 0, 0.035);
        }
        [data-testid="stMetric"] { padding: .15rem 0; }
        [data-testid="stMetricValue"] {
            font-weight: 620;
            letter-spacing: -0.035em;
        }

        /* Large, calm touch targets. */
        .stButton > button, .stDownloadButton > button {
            min-height: 2.85rem;
            font-weight: 590;
            transition: transform 120ms ease, box-shadow 120ms ease;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 5px 14px rgba(0, 113, 227, 0.16);
        }
        .stButton > button:active, .stDownloadButton > button:active {
            transform: translateY(0);
        }

        /* Let secondary information recede. */
        [data-testid="stExpander"] {
            border-color: rgba(0, 0, 0, 0.08);
            background: rgba(250, 250, 252, 0.72);
        }
        [data-testid="stFileUploaderDropzone"] {
            background: #fbfbfd;
            border-color: #d2d2d7;
        }
        [data-testid="stDataFrame"] {
            border-radius: 14px;
            overflow: hidden;
        }

        @media (max-width: 640px) {
            .stMainBlockContainer {
                padding: 1.25rem 1rem 4.5rem;
            }
            h1 { font-size: 2rem !important; }
            [data-testid="stMetricValue"] { font-size: 1.5rem; }
        }
        </style>
        """
    )


def page_kicker(step: int, label: str) -> None:
    st.caption(f"NFL LINEUP STUDIO  ·  {step} OF 3  ·  {label.upper()}")

