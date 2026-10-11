from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from dfs_optimizer.importers import match_projections
from dfs_optimizer.optimization import optimize_classic_lineup
from dfs_optimizer.projections import build_platform_average_projections
from dfs_optimizer.services.slates import load_uploaded_salary_file


class StreamlitAppTests(unittest.TestCase):
    @staticmethod
    def _entrypoint() -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "src"
            / "dfs_optimizer"
            / "web_app.py"
        )

    def test_home_page_starts_without_an_exception(self) -> None:
        app = AppTest.from_file(self._entrypoint(), default_timeout=10).run()

        self.assertFalse(app.exception)
        uploaders = app.get("file_uploader")
        self.assertEqual(len(uploaders), 1)
        self.assertEqual(
            uploaders[0].label,
            "Choose a DraftKings or FanDuel salary CSV",
        )

    def test_runs_navigation_opens_without_an_exception(self) -> None:
        app = AppTest.from_file(self._entrypoint(), default_timeout=10).run()

        app.button[0].click().run()

        self.assertFalse(app.exception)
        self.assertTrue(any(button.label == "Back to lineup builder" for button in app.button))

    def test_loaded_slate_build_page_opens_without_an_exception(self) -> None:
        root = Path(__file__).resolve().parents[1]
        salary_file = root / "samples" / "DKSalaries.csv"
        slate = load_uploaded_salary_file(
            salary_file.name, salary_file.read_bytes()
        )
        projections = build_platform_average_projections(slate)
        app = AppTest.from_file(self._entrypoint(), default_timeout=10).run()
        app.session_state["slate"] = slate
        app.session_state["projections"] = projections
        app.session_state["base_projections"] = projections

        app.switch_page("app_pages/build.py").run(timeout=10)

        self.assertFalse(app.exception)
        self.assertTrue(any(
            button.label == "Generate 3 lineups and review"
            for button in app.button
        ))

    def test_generated_lineup_results_page_is_submission_ready(self) -> None:
        root = Path(__file__).resolve().parents[1]
        salary_file = root / "samples" / "DKSalaries.csv"
        slate = load_uploaded_salary_file(
            salary_file.name, salary_file.read_bytes()
        )
        projections = build_platform_average_projections(slate)
        lineup = optimize_classic_lineup(
            slate, match_projections(slate, projections)
        )
        app = AppTest.from_file(self._entrypoint(), default_timeout=10).run()
        app.session_state["slate"] = slate
        app.session_state["projections"] = projections
        app.session_state["lineups"] = (lineup,)
        app.session_state["lineup_settings"] = {"lineups": 1}

        app.switch_page("app_pages/results.py").run(timeout=10)

        self.assertFalse(app.exception)
        self.assertTrue(any(
            message.value.startswith("Ready to submit")
            for message in app.success
        ))
        self.assertTrue(any(
            button.label == "Download lineup CSV"
            for button in app.get("download_button")
        ))
