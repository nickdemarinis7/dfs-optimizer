from __future__ import annotations

from html import escape

import streamlit as st


def apply_app_style() -> None:
    """Apply a small, stable layer of product styling over the native theme."""
    st.html(
        """
        <style>
        :root {
            --ls-primary: #0071e3;
            --ls-primary-dark: #0055b8;
            --ls-secondary: #667eea;
            --ls-primary-rgb: 0, 113, 227;
            --ls-secondary-rgb: 102, 126, 234;
            --ls-soft: rgba(0, 113, 227, .08);
            --ls-mark-start: #1888f5;
            --ls-mark-end: #0055b8;
        }
        /* Keep the interface focused and phone-like on large displays. */
        .stMainBlockContainer {
            max-width: 48rem;
            padding-top: 1.5rem;
            padding-bottom: 5rem;
        }

        /* A quiet canvas and crisp type hierarchy. */
        .stApp {
            background:
                radial-gradient(circle at 84% -5rem, rgba(var(--ls-primary-rgb), .10), transparent 24rem),
                radial-gradient(circle at -8rem 28rem, rgba(var(--ls-secondary-rgb), .06), transparent 25rem),
                #fcfcfd;
        }
        h1, h2, h3, p, label, button, input {
            letter-spacing: -0.012em;
        }
        h1 { letter-spacing: -0.035em; }
        h2, h3 { letter-spacing: -0.025em; }
        [data-testid="stCaptionContainer"] { color: #6e6e73; }

        .lineup-studio-nav {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 0 0 2.2rem;
        }
        .lineup-studio-brand {
            display: flex;
            align-items: center;
            gap: .65rem;
            color: #1d1d1f;
            font-size: .78rem;
            font-weight: 650;
            letter-spacing: .04em;
            white-space: nowrap;
        }
        .lineup-studio-mark {
            display: grid;
            place-items: center;
            width: 2rem;
            height: 2rem;
            border-radius: 50%;
            color: white;
            background: linear-gradient(145deg, var(--ls-mark-start), var(--ls-mark-end));
            box-shadow: 0 7px 18px rgba(var(--ls-primary-rgb), .22);
            font-size: .68rem;
            letter-spacing: -.04em;
        }
        .lineup-studio-steps {
            display: flex;
            align-items: center;
            gap: .35rem;
        }
        .lineup-studio-step {
            width: 1.7rem;
            height: .28rem;
            border-radius: 999px;
            background: #e4e4e8;
        }
        .lineup-studio-step.complete { background: rgba(var(--ls-primary-rgb), .38); }
        .lineup-studio-step.active {
            width: 2.8rem;
            background: var(--ls-primary);
        }
        .lineup-studio-step-label {
            margin-left: .4rem;
            color: #6e6e73;
            font-size: .74rem;
            font-weight: 550;
        }
        .lineup-studio-summary {
            padding: 1rem 1.15rem;
            margin: .4rem 0 1.8rem;
            border-radius: 18px;
            background: linear-gradient(120deg, var(--ls-soft), rgba(var(--ls-secondary-rgb), .07));
        }
        .lineup-studio-summary strong {
            display: block;
            margin-bottom: .15rem;
            color: #1d1d1f;
            font-size: .95rem;
            font-weight: 620;
        }
        .lineup-studio-summary span {
            color: #626267;
            font-size: .82rem;
        }
        .lineup-studio-hero {
            margin: .2rem 0 2.25rem;
        }
        .lineup-studio-hero h1 {
            max-width: 11ch;
            margin: 0 0 .65rem;
            color: #111113;
            font-size: clamp(2.65rem, 7vw, 4.4rem);
            font-weight: 680;
            line-height: .98;
            letter-spacing: -.065em;
        }
        .lineup-studio-hero p {
            max-width: 34rem;
            margin: 0;
            color: #6e6e73;
            font-size: 1.05rem;
            line-height: 1.5;
            letter-spacing: -.018em;
        }

        /* Soft cards instead of dashboard-style boxes. */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border: 0;
            background: rgba(245, 245, 247, .72);
            box-shadow: none;
            border-radius: 22px;
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
            border-width: 0;
            transition: transform 120ms ease, box-shadow 120ms ease;
        }
        [data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, var(--ls-primary), var(--ls-primary-dark));
            box-shadow: 0 8px 20px rgba(var(--ls-primary-rgb), .18);
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 5px 14px rgba(var(--ls-primary-rgb), .16);
        }
        .stButton > button:active, .stDownloadButton > button:active {
            transform: translateY(0);
        }

        /* Let secondary information recede. */
        [data-testid="stExpander"] {
            border: 0;
            border-radius: 0;
            background: transparent;
            box-shadow: inset 0 -1px rgba(0, 0, 0, .075);
        }
        [data-testid="stExpander"] summary { padding-left: .1rem; padding-right: .1rem; }
        [data-testid="stPopover"] > button {
            border: 0;
            background: color-mix(in srgb, var(--ls-primary) 8%, #f0f0f3);
            color: #3a3a3c;
        }
        [data-testid="stFileUploaderDropzone"] {
            background: linear-gradient(135deg, rgba(255,255,255,.96), rgba(245,248,253,.96));
            border: 1px dashed #b7c8dc;
            border-radius: 20px;
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
            .lineup-studio-nav { margin-bottom: 1.65rem; }
            .lineup-studio-step-label { display: none; }
            .lineup-studio-hero { margin-bottom: 1.7rem; }
            .lineup-studio-hero h1 { font-size: 2.8rem; }
        }
        </style>
        """
    )


def page_kicker(step: int, label: str) -> None:
    steps = "".join(
        f'<span class="lineup-studio-step {"complete" if number < step else "active" if number == step else ""}"></span>'
        for number in range(1, 4)
    )
    st.html(
        f"""
        <div class="lineup-studio-nav">
            <div class="lineup-studio-brand">
                <span class="lineup-studio-mark">LS</span>
                LINEUP STUDIO
            </div>
            <div class="lineup-studio-steps">
                {steps}
                <span class="lineup-studio-step-label">{escape(label)} · {step}/3</span>
            </div>
        </div>
        """
    )


def summary_strip(title: str, detail: str) -> None:
    st.html(
        f"""
        <div class="lineup-studio-summary">
            <strong>{escape(title)}</strong>
            <span>{escape(detail)}</span>
        </div>
        """
    )


def hero(title: str, subtitle: str) -> None:
    st.html(
        f"""
        <div class="lineup-studio-hero">
            <h1>{escape(title)}</h1>
            <p>{escape(subtitle)}</p>
        </div>
        """
    )


def apply_platform_theme(platform) -> None:
    """Set branded visual tokens after a salary slate identifies the platform."""
    platform_name = getattr(platform, "value", str(platform)).lower()
    if platform_name == "draftkings":
        tokens = {
            "primary": "#218C2A",
            "primary_dark": "#101712",
            "secondary": "#F46A1F",
            "primary_rgb": "33, 140, 42",
            "secondary_rgb": "244, 106, 31",
            "soft": "rgba(33, 140, 42, .10)",
            "mark_start": "#101712",
            "mark_end": "#218C2A",
        }
    else:
        tokens = {
            "primary": "#147CD1",
            "primary_dark": "#07549A",
            "secondary": "#0A3E78",
            "primary_rgb": "20, 124, 209",
            "secondary_rgb": "10, 62, 120",
            "soft": "rgba(20, 124, 209, .10)",
            "mark_start": "#2A9AF4",
            "mark_end": "#07549A",
        }
    st.html(
        f"""
        <style>
        :root {{
            --ls-primary: {tokens['primary']};
            --ls-primary-dark: {tokens['primary_dark']};
            --ls-secondary: {tokens['secondary']};
            --ls-primary-rgb: {tokens['primary_rgb']};
            --ls-secondary-rgb: {tokens['secondary_rgb']};
            --ls-soft: {tokens['soft']};
            --ls-mark-start: {tokens['mark_start']};
            --ls-mark-end: {tokens['mark_end']};
        }}
        </style>
        """
    )
