"""The Container Updates grid showed the wrong columns until the page was reloaded.

Frappe's `grid.update_docfield_property` does nothing at all while `grid.grid_rows`
is still undefined, and it throws for a field the child table does not carry. The
app configures these grids once per form open, behind a "ready" flag. Put together:
a configurator could run before the rows existed, change nothing, mark itself done,
and never run again - so the grid kept whatever it first rendered.

The sea-sequence config arrives asynchronously and re-triggers refresh, which is
what should have given the configurators their second chance. It reset only two of
the six flags.

The column behaviour itself is JavaScript, so reading the source proves nothing;
`tests/js/container_grid_columns.test.js` runs it against a grid stub that mimics
Frappe's own early return and throw.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

import frappe

JS = Path(__file__).resolve().parent.parent / "public" / "js"


def _source(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


class TestTheGridColumnsBehave(unittest.TestCase):
    def test_the_javascript_behaves(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not available")
        script = (
            Path(frappe.get_app_path("cgm_shipping"))
            / "tests"
            / "js"
            / "container_grid_columns.test.js"
        )
        result = subprocess.run(
            [node, str(script)], capture_output=True, text=True, timeout=120
        )
        self.assertEqual(
            result.returncode,
            0,
            f"container grid behaviour test failed:\n{result.stdout}\n{result.stderr}",
        )
        self.assertIn("passed", result.stdout)
        self.assertNotIn("FAILED", result.stdout)


class TestEveryConfigureOnceGridCanRunAgain(unittest.TestCase):
    """A flag that is never cleared is the bug; these pin the clearing."""

    READY_FLAGS = (
        "_cgm_sea_layout_ready",
        "_cgm_finance_grid_ready",
        "_cgm_shipping_line_deposit_grid_ready",
        "_cgm_shipping_line_finance_container_grid_ready",
        "_cgm_entry_arrival_mirror_grid_ready",
        "_cgm_status_grids_ready",
    )

    def test_the_async_config_clears_every_ready_flag(self):
        """It used to clear two of six, so four grids never reconfigured."""
        src = _source("task.js")
        start = src.index("function apply_cached_sea_ui_sequences")
        body = src[start : src.index("\n}", start)]
        for flag in self.READY_FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(
                    f"frm.{flag} = false", body, f"{flag} is never cleared, so its grid cannot retry"
                )

    def test_no_ready_flag_is_set_without_a_rendered_grid(self):
        """Each configure-once grid checks the rows exist before claiming it ran."""
        src = _source("task.js")
        self.assertGreaterEqual(src.count("container_grid_is_rendered"), 5)

    def test_the_project_container_grid_marks_loaded_only_after_it_applied(self):
        """It set the flag first, so a no-op was never retried."""
        src = _source("project.js")
        start = src.index("function configure_project_container_grid")
        body = src[start : src.index("\nfunction ", start + 10)]
        self.assertIn("if (!grid.grid_rows)", body)
        self.assertLess(
            body.index("update_docfield_property"),
            body.index("_cgm_container_modes_loaded = frm.doc.name"),
            "the loaded flag must be set after the columns are applied, not before",
        )

    def test_the_task_template_picker_waits_for_rows(self):
        src = _source("cgm_task_template.js")
        start = src.index("function apply_document_type_picker")
        body = src[start : src.index("\n}", start)]
        self.assertIn("if (!grid.grid_rows)", body)


class TestTheThrowIsContained(unittest.TestCase):
    """update_docfield_property throws for a field the table lacks.

    An uncaught throw abandons the rest of the layout half-applied, which looks
    exactly like a disarranged table.
    """

    def test_the_container_columns_are_set_through_a_guarded_helper(self):
        src = _source("task.js")
        start = src.index("function restrict_container_grid_columns")
        body = src[start : src.index("\n}", start)]
        self.assertNotIn("grid.update_docfield_property", body)
        self.assertIn("set_grid_column_property", body)

    def test_the_project_grid_catches_it_too(self):
        src = _source("project.js")
        start = src.index("function configure_project_container_grid")
        body = src[start : src.index("\nfunction ", start + 10)]
        self.assertIn("try {", body)
