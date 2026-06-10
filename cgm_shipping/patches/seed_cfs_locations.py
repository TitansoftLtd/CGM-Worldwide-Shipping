# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Seed CFS Location masters and (re)link Clearance Stations.

The original `seed_clearance_stations` patch has already run on existing sites,
so this patch re-runs the (idempotent) seed now that locations are normalised
into the CFS Location doctype and names use Title Case.
"""

from cgm_shipping.patches.seed_clearance_stations import seed


def execute():
	seed()
