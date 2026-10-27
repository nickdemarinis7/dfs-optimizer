from __future__ import annotations

from collections.abc import MutableMapping

from dfs_optimizer.services.player_context import import_final_status_csv
from dfs_optimizer.services.run_history import (
    RunRecord,
    load_run_context_inputs,
    restore_run,
)


def restore_run_session(state: MutableMapping, record: RunRecord) -> None:
    """Restore an archived run into per-browser application state."""
    slate, projections, lineups, salary_content, settings = restore_run(record)
    context_inputs = load_run_context_inputs(record)
    restored_final_status = (
        import_final_status_csv(slate, context_inputs.final_status_content)
        if context_inputs.final_status_content else ()
    )

    state["slate"] = slate
    state["source_name"] = slate.source_name
    state["salary_content"] = salary_content
    state["salary_loaded_at"] = record.created_at
    state["projections"] = projections
    state["base_projections"] = projections
    state["lineups"] = lineups
    state["lineup_settings"] = settings
    state["run_archive"] = record.path.read_bytes()
    state["run_archive_name"] = record.path.name
    state["saved_run_path"] = str(record.path)
    state["current_run_id"] = record.run_id
    state["scenario_analysis"] = ()
    state["player_context"] = context_inputs.player_context
    state["player_context_source"] = context_inputs.source
    state["player_context_error"] = None
    state["player_context_built_at"] = context_inputs.checked_at
    state["player_context_attempted"] = bool(context_inputs.player_context)
    final_content = context_inputs.final_status_content
    if final_content:
        state["final_status_context"] = restored_final_status
        state["final_status_content"] = final_content
        state["final_status_name"] = "final-status.csv"
        state["final_status_hash"] = None
        state["final_status_checked_at"] = context_inputs.checked_at
    else:
        for key in (
            "final_status_context", "final_status_content", "final_status_name",
            "final_status_hash", "final_status_checked_at",
        ):
            state.pop(key, None)
    state["submission_snapshot_key"] = None
    state["submission_snapshot"] = None
    state["saved_submission_path"] = None
    state["lineup_config_key"] = None
    state["current_config_key"] = None
