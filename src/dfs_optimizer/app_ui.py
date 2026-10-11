from __future__ import annotations

from html import escape

import streamlit as st


def apply_app_style() -> None:
    """Apply a small, stable layer of product styling over the native theme."""
    st.html(
        """
        <style>
        :root {
            --ls-primary: #6d28d9;
            --ls-primary-dark: #3b0764;
            --ls-secondary: #111827;
            --ls-primary-rgb: 109, 40, 217;
            --ls-secondary-rgb: 17, 24, 39;
            --ls-soft: rgba(109, 40, 217, .09);
            --ls-mark-start: #111827;
            --ls-mark-end: #6d28d9;
        }
        /* A focused workspace that still gives dense lineup tables room. */
        .stMainBlockContainer,
        [data-testid="stMainBlockContainer"] {
            max-width: 64rem;
            /* Streamlit Cloud's toolbar overlays the document. Reserve its
               height plus the iPhone safe area so navigation is never hidden. */
            padding-top: calc(4.75rem + env(safe-area-inset-top)) !important;
            padding-bottom: 6rem;
        }

        /* A restrained product canvas and crisp type hierarchy. */
        .stApp {
            background: #f7f8fa;
        }
        h1, h2, h3, p, label, button, input {
            letter-spacing: -0.012em;
        }
        h1 { letter-spacing: -0.035em; }
        h2, h3 { letter-spacing: -0.025em; }
        [data-testid="stCaptionContainer"] {
            color: #6b7280;
            line-height: 1.45;
        }

        .st-key-lineup-studio-topbar {
            position: relative;
            width: 100%;
            max-width: 100%;
            box-sizing: border-box;
            padding: .55rem .65rem;
            margin: 0 0 2.5rem;
            border: 1px solid #e5e7eb;
            border-top: 3px solid var(--ls-secondary);
            border-radius: 18px;
            background: rgba(255, 255, 255, .94);
            box-shadow: 0 1px 2px rgba(15, 23, 42, .04), 0 8px 30px rgba(15, 23, 42, .045);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
        }
        .st-key-lineup-studio-topbar .stButton > button {
            min-height: 2.25rem;
            padding: .35rem .75rem;
            border: 1px solid #e5e7eb;
            background: #fff;
            color: #374151;
            box-shadow: none;
            white-space: nowrap;
        }
        .lineup-studio-brand {
            display: flex;
            align-items: center;
            gap: .7rem;
            color: #111827;
            font-size: .8rem;
            font-weight: 700;
            letter-spacing: .025em;
            white-space: nowrap;
        }
        .lineup-studio-platform {
            display: inline-flex;
            align-items: center;
            min-height: 1.55rem;
            padding: .2rem .55rem;
            border: 1px solid rgba(var(--ls-primary-rgb), .16);
            border-radius: 999px;
            color: var(--ls-primary-dark);
            background: var(--ls-soft);
            font-size: .68rem;
            font-weight: 700;
            letter-spacing: .015em;
        }
        .lineup-studio-mark {
            display: grid;
            place-items: center;
            width: 2.1rem;
            height: 2.1rem;
            border-radius: 10px;
            color: white;
            background: linear-gradient(145deg, var(--ls-mark-start), var(--ls-mark-end));
            box-shadow: 0 5px 14px rgba(var(--ls-primary-rgb), .2);
            font-size: .68rem;
            letter-spacing: -.04em;
        }
        .lineup-studio-steps {
            display: flex;
            align-items: center;
            gap: .35rem;
        }
        .lineup-studio-utility-label {
            padding: .25rem .65rem;
            border-radius: 999px;
            color: #6e6e73;
            background: #f1f1f4;
            font-size: .74rem;
            font-weight: 600;
        }
        .lineup-studio-step {
            width: 1.5rem;
            height: .22rem;
            border-radius: 999px;
            background: #e4e4e8;
        }
        .lineup-studio-step.complete { background: rgba(var(--ls-primary-rgb), .38); }
        .lineup-studio-step.active {
            width: 2.35rem;
            background: var(--ls-primary);
        }
        .lineup-studio-step-label {
            margin-left: .4rem;
            color: #6e6e73;
            font-size: .74rem;
            font-weight: 550;
        }
        .lineup-studio-summary {
            padding: .95rem 1.1rem;
            margin: .25rem 0 1.75rem;
            border: 1px solid rgba(var(--ls-primary-rgb), .14);
            border-left: 4px solid var(--ls-primary);
            border-radius: 14px;
            background: linear-gradient(
                110deg,
                var(--ls-soft),
                rgba(var(--ls-secondary-rgb), .035) 58%,
                #fff
            );
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
            margin: .1rem 0 2rem;
        }
        .lineup-studio-hero h1 {
            max-width: 18ch;
            margin: 0 0 .55rem;
            color: #111827;
            font-size: clamp(2.25rem, 5vw, 3.45rem);
            font-weight: 720;
            line-height: 1.02;
            letter-spacing: -.052em;
        }
        .lineup-studio-hero p {
            max-width: 34rem;
            margin: 0;
            color: #64748b;
            font-size: 1rem;
            line-height: 1.55;
            letter-spacing: -.018em;
        }
        .lineup-studio-features {
            display: flex;
            flex-wrap: wrap;
            gap: .5rem;
            margin: -1rem 0 2rem;
        }
        .lineup-studio-guide {
            display: flex;
            align-items: flex-start;
            gap: .75rem;
            padding: .75rem .15rem;
            margin: .15rem 0 1rem;
            border-top: 1px solid #e5e7eb;
            border-bottom: 1px solid #e5e7eb;
            background: transparent;
        }
        .lineup-studio-guide-number {
            display: grid;
            flex: 0 0 auto;
            place-items: center;
            width: 1.75rem;
            height: 1.75rem;
            border-radius: 8px;
            color: var(--ls-primary-dark);
            background: var(--ls-soft);
            font-size: .76rem;
            font-weight: 700;
        }
        .lineup-studio-guide strong {
            display: block;
            margin: .05rem 0 .18rem;
            color: #111827;
            font-size: .92rem;
        }
        .lineup-studio-guide p {
            margin: 0;
            color: #64748b;
            font-size: .83rem;
            line-height: 1.45;
        }
        .lineup-studio-section-label {
            margin: 1.5rem 0 .55rem;
            color: #86868b;
            font-size: .72rem;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .lineup-studio-feature {
            padding: .5rem .75rem;
            border: 1px solid rgba(var(--ls-primary-rgb), .10);
            border-radius: 999px;
            color: #505055;
            background: rgba(255,255,255,.74);
            font-size: .78rem;
            font-weight: 560;
            box-shadow: 0 4px 14px rgba(30, 45, 65, .045);
        }

        /* Quiet, consistent surfaces instead of a stack of decorative boxes. */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid #e5e7eb;
            background: #fff;
            box-shadow: 0 1px 2px rgba(15, 23, 42, .025), 0 8px 24px rgba(15, 23, 42, .035);
            border-radius: 16px;
        }
        [data-testid="stMetric"] { padding: .15rem 0; }
        [data-testid="stMetricValue"] {
            font-weight: 620;
            letter-spacing: -0.035em;
        }

        /* Large, calm touch targets. */
        .stButton > button, .stDownloadButton > button {
            min-height: 2.75rem;
            font-weight: 620;
            border-width: 0;
            transition: transform 120ms ease, box-shadow 120ms ease;
        }
        [data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, var(--ls-primary), var(--ls-primary-dark));
            box-shadow: 0 5px 14px rgba(var(--ls-primary-rgb), .16);
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
            border-radius: 14px;
        }
        [data-testid="stDataFrame"] {
            border: 1px solid rgba(210, 210, 215, .5);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(30, 45, 65, .04);
        }
        [data-testid="stAlert"] {
            border: 0;
            border-radius: 12px;
        }
        [data-testid="stSegmentedControl"] {
            padding: .25rem;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            background: #fff;
        }
        [data-testid="stSegmentedControl"] button[aria-pressed="true"] {
            color: #fff;
            background: var(--ls-primary);
            box-shadow: 0 3px 10px rgba(var(--ls-primary-rgb), .18);
        }
        [data-baseweb="input"]:focus-within,
        [data-baseweb="select"]:focus-within,
        [data-testid="stFileUploaderDropzone"]:focus-within {
            border-color: rgba(var(--ls-primary-rgb), .55) !important;
            box-shadow: 0 0 0 3px var(--ls-soft);
        }
        a { color: var(--ls-primary); }

        @media (max-width: 640px) {
            .stMainBlockContainer,
            [data-testid="stMainBlockContainer"] {
                padding: calc(4.25rem + env(safe-area-inset-top)) 1rem 5rem !important;
            }
            h1 { font-size: 2rem !important; }
            [data-testid="stMetricValue"] { font-size: 1.5rem; }
            .st-key-lineup-studio-topbar {
                margin-bottom: 1.65rem;
            }
            .lineup-studio-brand { gap: 0; }
            .lineup-studio-brand-name { display: none; }
            .lineup-studio-platform { margin-left: .45rem; }
            .st-key-lineup-studio-topbar .stButton > button {
                padding: .35rem .62rem;
                transform: none;
            }
            .lineup-studio-step-label { display: none; }
            .lineup-studio-hero { margin-bottom: 1.7rem; }
            .lineup-studio-hero h1 { font-size: 2.35rem; }
        }
        </style>
        """
    )


def page_kicker(
    step: int | None,
    label: str,
    *,
    home: bool = True,
    total_steps: int = 3,
) -> None:
    slate = st.session_state.get("slate")
    detected_platform = getattr(getattr(slate, "platform", None), "value", None)
    platform_label = (
        "DraftKings" if detected_platform == "draftkings"
        else "FanDuel" if detected_platform == "fanduel"
        else "DFS"
    )
    steps = "".join(
        f'<span class="lineup-studio-step {"complete" if step and number < step else "active" if number == step else ""}"></span>'
        for number in range(1, total_steps + 1)
    )
    with st.container(
        key="lineup-studio-topbar",
        horizontal=True,
        wrap=False,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    ):
        st.html(
            f"""
            <div class="lineup-studio-brand">
                <span class="lineup-studio-mark">LS</span>
                <span class="lineup-studio-brand-name">LINEUP STUDIO</span>
                <span class="lineup-studio-platform">{platform_label}</span>
            </div>
            """
        )
        if step is not None:
            st.html(
                f"""
            <div class="lineup-studio-steps">
                {steps}
                <span class="lineup-studio-step-label">{escape(label)} · {step}/{total_steps}</span>
            </div>
                """
            )
        else:
            st.html(f'<span class="lineup-studio-utility-label">{escape(label)}</span>')
        if home and st.button(
            "Home",
            icon=":material/home:",
            key=f"home-{label.casefold().replace(' ', '-')}",
        ):
            st.switch_page("app_pages/setup.py")
        if label != "Run history":
            if st.button(
                "Runs",
                icon=":material/history:",
                key=f"runs-{label.casefold().replace(' ', '-')}",
            ):
                st.switch_page("app_pages/run_history.py")


def feature_strip(*features: str) -> None:
    items = "".join(
        f'<span class="lineup-studio-feature">{escape(feature)}</span>'
        for feature in features
    )
    st.html(f'<div class="lineup-studio-features">{items}</div>')


def action_guide(number: int | str, title: str, detail: str) -> None:
    """Show the single action that moves the workflow forward."""
    st.html(
        f"""
        <div class="lineup-studio-guide">
            <span class="lineup-studio-guide-number">{escape(str(number))}</span>
            <div>
                <strong>{escape(title)}</strong>
                <p>{escape(detail)}</p>
            </div>
        </div>
        """
    )


def optional_label(label: str = "Optional") -> None:
    st.html(f'<div class="lineup-studio-section-label">{escape(label)}</div>')


def section_intro(title: str, detail: str, *, icon: str | None = None) -> None:
    """Introduce a visible section in plain language."""
    st.subheader(title, icon=icon)
    st.caption(detail)


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
            "soft": "rgba(33, 140, 42, .11)",
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
            "soft": "rgba(20, 124, 209, .11)",
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
