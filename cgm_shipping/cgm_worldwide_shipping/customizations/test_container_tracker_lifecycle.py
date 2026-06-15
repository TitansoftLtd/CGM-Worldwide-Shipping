# Copyright (c) 2026, Titansoft Limited and contributors
"""Unit tests for per-container Container Tracker lifecycle resolution."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	ContainerEventResolutionError,
	create_container_trackers_for_project,
	find_tracker_by_identity,
	handle_sea_task_container_event,
	is_bulk_container_event,
	is_container_specific_event,
	resolve_single_tracker,
)


class TestContainerEventClassification(unittest.TestCase):
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.get_container_task_sequence",
		side_effect=lambda f: {
			"custom_track_eta_task_seq": 8,
			"custom_gate_out_task_seq": 20,
			"custom_book_trucks_task_seq": 19,
		}.get(f, 0),
	)
	def test_bulk_vs_container_specific_sequences(self, _mock_seq):
		frappe.cache().delete_value(
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker._bulk_task_sequences"
		)
		frappe.cache().delete_value(
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker._container_specific_task_sequences"
		)
		self.assertTrue(is_bulk_container_event(8))
		self.assertTrue(is_bulk_container_event(19))
		self.assertTrue(is_container_specific_event(20))
		self.assertFalse(is_container_specific_event(8))


class TestResolveSingleTracker(unittest.TestCase):
	@patch("frappe.db.exists", return_value=True)
	@patch("frappe.get_doc")
	def test_resolve_by_container_tracker_link(self, mock_get_doc, _mock_exists):
		tracker = MagicMock()
		tracker.project = "PROJ-001"
		mock_get_doc.return_value = tracker

		result = resolve_single_tracker(
			"PROJ-001", container_tracker="CT-00001"
		)
		self.assertIs(result, tracker)

	@patch("frappe.get_all")
	def test_resolve_by_number_and_type(self, mock_get_all):
		mock_get_all.return_value = ["CT-00002"]
		tracker = MagicMock()
		with patch("frappe.get_doc", return_value=tracker):
			result = resolve_single_tracker(
				"PROJ-001",
				container_number="234567890",
				type_of_container="40FT",
			)
		self.assertIs(result, tracker)
		mock_get_all.assert_called_once()

	def test_missing_identifier_raises(self):
		with self.assertRaises(ContainerEventResolutionError):
			resolve_single_tracker("PROJ-001")

	@patch("frappe.get_all", return_value=["CT-A", "CT-B"])
	def test_ambiguous_number_raises(self, _mock_get_all):
		with self.assertRaises(ContainerEventResolutionError):
			resolve_single_tracker(
				"PROJ-001",
				container_number="234567890",
			)


class TestHandleSeaTaskContainerEvent(unittest.TestCase):
	def _task(self, **kwargs):
		doc = MagicMock()
		for key, value in kwargs.items():
			setattr(doc, key, value)
		doc.get = lambda field, default=None: kwargs.get(field, default)
		return doc

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker._apply_bulk_eta"
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.is_bulk_container_event",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.is_container_specific_event",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.get_container_task_sequence",
		return_value=8,
	)
	@patch("frappe.get_cached_doc")
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker._trackers_for_project",
		return_value=[],
	)
	def test_bulk_eta_updates_all_trackers_path(
		self,
		_mock_trackers,
		_mock_project,
		_mock_seq,
		_mock_specific,
		_mock_bulk,
		mock_bulk_eta,
	):
		handle_sea_task_container_event("PROJ-001", 8, task_doc=self._task())
		mock_bulk_eta.assert_called_once()

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker._apply_container_specific_event"
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.is_container_specific_event",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.is_bulk_container_event",
		return_value=False,
	)
	def test_container_specific_requires_resolution_path(
		self,
		_mock_bulk,
		_mock_specific,
		mock_apply_specific,
	):
		task = self._task(
			custom_container_tracker="CT-00001",
			custom_container_number="234567890",
			custom_type_of_container="40FT",
		)
		handle_sea_task_container_event("PROJ-001", 20, task_doc=task)
		mock_apply_specific.assert_called_once()

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.resolve_single_tracker",
		side_effect=ContainerEventResolutionError("missing"),
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.is_container_specific_event",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.is_bulk_container_event",
		return_value=False,
	)
	def test_container_specific_without_identifier_raises(
		self,
		_mock_bulk,
		_mock_specific,
		_mock_resolve,
	):
		with self.assertRaises(ContainerEventResolutionError):
			handle_sea_task_container_event("PROJ-001", 20, task_doc=self._task())


class TestTrackerCreationIdentity(unittest.TestCase):
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker._link_container_row"
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker._populate_tracker_from_project_and_row"
	)
	@patch("frappe.get_doc")
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.find_tracker_by_identity",
		return_value="CT-EXISTING",
	)
	def test_reuses_existing_tracker_by_identity(
		self,
		_mock_find,
		mock_get_doc,
		_mock_populate,
		_mock_link,
	):
		project = MagicMock()
		project.name = "PROJ-001"
		row = MagicMock()
		row.container_number = "234567890"
		row.get = lambda f, default=None: {"type_of_container": "40FT"}.get(f, default)

		tracker = MagicMock()
		tracker.name = "CT-EXISTING"
		mock_get_doc.return_value = tracker

		from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
			create_or_sync_tracker_for_row,
		)

		name = create_or_sync_tracker_for_row(project, row)
		self.assertEqual(name, "CT-EXISTING")
		tracker.save.assert_called_once()

	@patch("frappe.db.get_value")
	def test_find_tracker_by_identity_includes_type(self, mock_get_value):
		find_tracker_by_identity("PROJ-001", "234567890", "20FT")
		mock_get_value.assert_called_once_with(
			"Container Tracker",
			{
				"project": "PROJ-001",
				"container_number": "234567890",
				"type_of_container": "20FT",
			},
			"name",
		)


class TestCreateContainerTrackersForProject(unittest.TestCase):
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.create_or_sync_tracker_for_row",
		side_effect=["CT-1", "CT-2", "CT-3"],
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.get_container_table_field_for_doctype",
		return_value="custom_container_information",
	)
	@patch("frappe.db.exists", return_value=True)
	@patch("frappe.get_doc")
	@patch("frappe.db.commit")
	def test_creates_one_tracker_per_row(
		self,
		_mock_commit,
		mock_get_doc,
		_mock_exists,
		_mock_field,
		mock_sync,
	):
		project = MagicMock()
		row_a = MagicMock(container_number="A")
		row_b = MagicMock(container_number="B")
		row_c = MagicMock(container_number="C")
		project.get = lambda f: [row_a, row_b, row_c] if f == "custom_container_information" else []
		mock_get_doc.return_value = project

		result = create_container_trackers_for_project("PROJ-001")
		self.assertEqual(result, ["CT-1", "CT-2", "CT-3"])
		self.assertEqual(mock_sync.call_count, 3)
