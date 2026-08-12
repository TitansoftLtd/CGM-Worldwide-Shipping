"""Re-complete finance payment tasks stuck Open after payment was already done.

Recurring form=Completed / list=Open mismatch: auto-complete writes Completed via
set_value, then a concurrent stale save still carrying Open overwrites the DB.
settle_stale_open_finance_tasks may already be in Patch Log — this run heals
again under the hardened before_save / on_update guards.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.patches.settle_stale_open_finance_tasks import execute as settle

	settle()
