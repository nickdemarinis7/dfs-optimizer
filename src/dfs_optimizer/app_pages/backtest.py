from __future__ import annotations

import pandas as pd
import streamlit as st

from dfs_optimizer.app_ui import apply_platform_theme, hero
from dfs_optimizer.services.results_review import review_contest_results


slate = st.session_state.get("slate")
lineups = st.session_state.get("lineups", ())
if slate is not None:
    apply_platform_theme(slate.platform)

hero(
    "How did they finish?",
    "Drop in the contest standings after it ends. We’ll find your generated lineups and grade the run automatically.",
)

if slate is None or not lineups:
    st.warning("Generate lineups before reviewing contest results.", icon=":material/arrow_back:")
    if st.button("Back to lineup builder", icon=":material/arrow_back:", width="stretch"):
        st.switch_page("app_pages/build.py")
    st.stop()

st.caption(
    f"{slate.platform.value.title()} · {slate.contest_format.value.replace('_', ' ').title()} · "
    f"{len(lineups)} generated lineups"
)
results_file = st.file_uploader(
    "Contest standings",
    type=("csv", "zip"),
    help="Use the final contest standings export from DraftKings or FanDuel.",
)
entry_filter = st.text_input(
    "Entry name contains (optional)",
    placeholder="Your username",
    help="Use this when an identical lineup appears more than once with different scores.",
)

if results_file is not None:
    try:
        review = review_contest_results(
            results_file.getvalue(),
            results_file.name,
            lineups,
            slate.platform,
            slate.contest_format,
            entry_filter,
        )
    except ValueError as exc:
        st.error(str(exc), icon=":material/error:")
    else:
        metrics = st.columns(3)
        metrics[0].metric("Field", f"{review.field_size:,}")
        metrics[1].metric("Winning score", f"{review.winning_score:.2f}")
        metrics[2].metric("Matched", f"{len(review.lineups)}/{len(lineups)}")

        if review.lineups:
            st.dataframe(
                pd.DataFrame([
                    {
                        "Lineup": item.lineup_number,
                        "Score": item.score,
                        "Rank": item.rank,
                        "Top %": round(item.top_percent, 2),
                        "Duplicates": item.duplication,
                        "Entry": item.entry_name,
                    }
                    for item in review.lineups
                ]),
                hide_index=True,
                width="stretch",
            )
        if review.unmatched_lineups:
            numbers = ", ".join(map(str, review.unmatched_lineups))
            st.warning(f"Could not find generated lineup(s): {numbers}.")
        if review.ambiguous_lineups:
            numbers = ", ".join(map(str, review.ambiguous_lineups))
            st.warning(
                f"Lineup(s) {numbers} matched entries with different scores. Add your username above to identify yours."
            )

if st.button("Back to results", icon=":material/arrow_back:", width="stretch"):
    st.switch_page("app_pages/results.py")
