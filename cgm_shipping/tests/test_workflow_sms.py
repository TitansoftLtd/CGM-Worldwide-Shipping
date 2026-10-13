"""Workflow SMS rules.

Rules pinned here:

* Numbers reach the gateway as 2547XXXXXXXX however staff typed them.
* Only sea import steps listed in STEP_SMS text anyone, and only on completion
  of that exact step.
* Nothing is queued while the Notification is disabled, the gateway is not set
  up, or no recipient has a mobile number - and a failure never reaches the save.
* An email handoff is texted from its subject line; an SMS Notification from its
  message. Either is cut to one 160-character text.
* The opportunity text goes once, on entering Pending Approval.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import workflow_sms as sms


class TestNormaliseMobile(unittest.TestCase):
	def test_formats(self):
		for typed in ("0702822379", "+254 702 822 379", "254702822379", "702822379", "0702-822-379"):
			self.assertEqual(sms.normalise_mobile(typed), "254702822379", typed)

	def test_empty(self):
		self.assertEqual(sms.normalise_mobile(None), "")
		self.assertEqual(sms.normalise_mobile(" "), "")

	def test_foreign_number_passes_through(self):
		self.assertEqual(sms.normalise_mobile("+255 712 345 678"), "255712345678")


class TestStepLookup(unittest.TestCase):
	def test_listed_sea_step(self):
		task = frappe._dict(custom_task_flow_key="Sea Import Workflow", custom_sequence_no=21)
		self.assertEqual(sms.step_sms_notification(task), "CGM SMS - Trucks Exited Port")

	def test_unlisted_step(self):
		task = frappe._dict(custom_task_flow_key="Sea Import Workflow", custom_sequence_no=4)
		self.assertIsNone(sms.step_sms_notification(task))

	def test_other_workflow_with_same_sequence(self):
		task = frappe._dict(custom_task_flow_key="Air Import Workflow", custom_sequence_no=21)
		self.assertIsNone(sms.step_sms_notification(task))

	def test_names_and_steps_are_unique(self):
		self.assertEqual(len({s[0] for s in sms.STEP_SMS}), len(sms.STEP_SMS))
		self.assertEqual(len({s[1] for s in sms.STEP_SMS}), len(sms.STEP_SMS))


def _notification(**fields):
	doc = MagicMock()
	doc.name = fields.get("name", "N")
	doc.enabled = fields.get("enabled", 1)
	doc.channel = fields.get("channel", "SMS")
	doc.message = fields.get("message", "Hello {{ doc.name }}")
	doc.subject = fields.get("subject", "Subject {{ doc.name }}")
	doc.get_receiver_list.return_value = fields.get("numbers", ["0702822379", "254702822379", ""])
	return doc


class TestQueue(unittest.TestCase):
	def _queue(self, notification, *, gateway=True):
		enqueue = MagicMock()
		with (
			patch.object(sms, "sms_gateway_configured", return_value=gateway),
			patch("frappe.email.doctype.notification.notification.get_context", return_value={"doc": frappe._dict(name="T1")}),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications.stamp_shipment_name_on_doc"
			),
			patch.object(frappe, "enqueue", enqueue),
		):
			count = sms.queue_notification_sms(notification, frappe._dict(name="T1"))
		return count, enqueue

	def test_queues_once_per_distinct_number(self):
		count, enqueue = self._queue(_notification())
		self.assertEqual(count, 1)
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["numbers"], ["254702822379"])
		self.assertEqual(kwargs["text"], "Hello T1")
		self.assertTrue(kwargs["enqueue_after_commit"])

	def test_email_notification_is_texted_from_its_subject(self):
		_count, enqueue = self._queue(_notification(channel="Email", message="<p>Long body</p>"))
		self.assertEqual(enqueue.call_args.kwargs["text"], "Subject T1")

	def test_long_text_is_cut_to_one_sms(self):
		_count, enqueue = self._queue(_notification(message="x" * 400))
		self.assertEqual(len(enqueue.call_args.kwargs["text"]), sms.SMS_MAX_LENGTH)

	def test_disabled_notification_sends_nothing(self):
		count, enqueue = self._queue(_notification(enabled=0))
		self.assertEqual(count, 0)
		enqueue.assert_not_called()

	def test_no_gateway_sends_nothing(self):
		count, enqueue = self._queue(_notification(), gateway=False)
		self.assertEqual(count, 0)
		enqueue.assert_not_called()

	def test_no_mobile_numbers_sends_nothing(self):
		count, enqueue = self._queue(_notification(numbers=[]))
		self.assertEqual(count, 0)
		enqueue.assert_not_called()

	def test_failure_does_not_raise(self):
		notification = _notification()
		notification.get_receiver_list.side_effect = RuntimeError("boom")
		with patch.object(frappe, "log_error") as log:
			count, _enqueue = self._queue(notification)
		self.assertEqual(count, 0)
		log.assert_called_once()


class TestHandoffEvent(unittest.TestCase):
	WF = "cgm_shipping.cgm_worldwide_shipping.customizations.workflow_notifications"

	def _fire(self, default_name, *, ticked=True, sms_exists=True):
		with (
			patch(f"{self.WF}.sms_enabled_for_notification", return_value=ticked),
			patch.object(frappe.db, "exists", return_value=sms_exists),
			patch.object(sms, "queue_notification_sms", return_value=1) as queue,
		):
			sms.send_sms_for_workflow_event(default_name, "EMAIL-DOC", frappe._dict(name="T1"))
		return queue

	def test_handoff_uses_its_own_sms_notification(self):
		queue = self._fire("CGM Task - UCR Invoice to Finance")
		self.assertEqual(queue.call_args.args[0], "CGM SMS - UCR Invoice to Finance")

	def test_event_without_one_falls_back_to_the_email(self):
		queue = self._fire("CGM Task - UCR Receipt Verify Finance")
		self.assertEqual(queue.call_args.args[0], "EMAIL-DOC")

	def test_missing_sms_notification_falls_back_to_the_email(self):
		queue = self._fire("CGM Task - UCR Invoice to Finance", sms_exists=False)
		self.assertEqual(queue.call_args.args[0], "EMAIL-DOC")

	def test_unticked_event_sends_nothing(self):
		self._fire("CGM Task - UCR Invoice to Finance", ticked=False).assert_not_called()

	def test_every_handoff_names_a_real_event_once(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_notifications import (
			WORKFLOW_NOTIFICATION_DEFAULTS,
		)

		events = {name for _event, name, _notes in WORKFLOW_NOTIFICATION_DEFAULTS}
		emails = [h[0] for h in sms.HANDOFF_SMS]
		self.assertTrue(set(emails) <= events)
		self.assertEqual(len(set(emails)), len(emails))
		names = [h[1] for h in sms.HANDOFF_SMS] + [s[1] for s in sms.STEP_SMS]
		self.assertEqual(len(set(names)), len(names))


class TestDeliver(unittest.TestCase):
	def test_one_bad_number_does_not_stop_the_rest(self):
		sent = []

		def fake_send(numbers, text, success_msg=True):
			if numbers == ["254700000001"]:
				raise RuntimeError("rejected")
			sent.extend(numbers)

		with (
			patch("frappe.core.doctype.sms_settings.sms_settings._send_sms", fake_send),
			patch.object(frappe, "log_error") as log,
		):
			sms.deliver_sms(["254700000001", "254700000002"], "hi", "N")
		self.assertEqual(sent, ["254700000002"])
		log.assert_called_once()


class TestOpportunityTrigger(unittest.TestCase):
	def _run(self, state, previous):
		doc = MagicMock()
		doc.get.side_effect = lambda key: {"workflow_state": state}.get(key)
		prev = None
		if previous is not None:
			prev = MagicMock()
			prev.get.side_effect = lambda key: {"workflow_state": previous}.get(key)
		doc.get_doc_before_save.return_value = prev
		with patch.object(sms, "queue_notification_sms") as queue:
			sms.notify_opportunity_approval_sms(doc)
		return queue

	def test_entering_pending_approval_texts(self):
		self._run("Pending Approval", "Ops Intake").assert_called_once()

	def test_resaving_while_pending_does_not_text_again(self):
		self._run("Pending Approval", "Pending Approval").assert_not_called()

	def test_other_states_do_not_text(self):
		self._run("Approved", "Pending Approval").assert_not_called()
