"""Superseded - does nothing.

This used to require DO on Sea Import's Lodge Delivery Order step and FIELD /
Delivery Note on its field clearance step. Neither step should block on an
upload, so stop_requiring_sea_import_step_documents undoes it on sites where it
already ran, and this no longer adds the requirements where it has not.

Retire per docs/guides/patches.md (remove from patches.txt and delete) once
staging and production Patch Log show stop_requiring_sea_import_step_documents.
"""


def execute():
	pass
