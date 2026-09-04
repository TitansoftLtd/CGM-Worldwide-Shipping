// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt
/**
 * Work a whole exchange from the one record.
 *
 * A reply is still its own Shipment Update linked by `parent_update` - that is
 * what lets a thread run past a single answer and what the portals render -
 * but ops never has to open it: the conversation and the reply box both live
 * here, and replies are kept out of the ops feed so a thread is one row.
 */
frappe.ui.form.on("Shipment Update", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		show_response_indicator(frm);
		add_thread_links(frm);
		render_conversation(frm);
	},
});

const PARTY_SOURCES = ["Customer", "Transporter"];

function is_question(frm) {
	return PARTY_SOURCES.includes(frm.doc.update_source);
}

function show_response_indicator(frm) {
	if (!is_question(frm)) {
		return;
	}
	if (frm.doc.response_status === "Answered") {
		const who = frm.doc.responded_by
			? frappe.user.full_name(frm.doc.responded_by)
			: __("CGM");
		frm.dashboard.set_headline(
			__("Answered by {0}", [frappe.utils.escape_html(who)]),
			"green"
		);
	} else {
		frm.dashboard.set_headline(__("Awaiting a reply from CGM"), "orange");
	}
}

function add_thread_links(frm) {
	if (frm.doc.parent_update) {
		frm.add_custom_button(__("Open the Question"), () =>
			frappe.set_route("Form", "Shipment Update", frm.doc.parent_update)
		);
	}
}

function render_conversation(frm) {
	const wrapper = frm.fields_dict.conversation_html;
	if (!wrapper) {
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_update_thread",
		args: { name: frm.doc.name },
		callback(r) {
			if (r.exc) {
				return;
			}
			paint(frm, wrapper, r.message || []);
		},
	});
}

function paint(frm, wrapper, thread) {
	const $body = $(wrapper.wrapper).empty();

	if (thread.length) {
		$body.append(cgm.updates.renderTranscript(thread, frm.doc.name));
	}

	// The thread's root is what a reply attaches to, so replying from a CGM
	// message in the middle still answers the original question.
	const question = thread.find((m) => PARTY_SOURCES.includes(m.update_source));
	if (!question) {
		// Nothing was asked here - offer a fresh portal post instead.
		$body.append(
			$(`<button type="button" class="btn btn-default btn-sm">${__(
				"Post Update to Portal"
			)}</button>`).on("click", () =>
				cgm.updates.openPublishDialog({
					project: frm.doc.project,
					container_tracker: frm.doc.container_tracker,
					onSent: () => frm.reload_doc(),
				})
			)
		);
		return;
	}

	// The reply goes back to whoever asked; the server works that out from the
	// question, so there is no audience to pick.
	const $reply = $(`
		<div class="cgm-reply-box">
			<div class="cgm-reply-label">${__("Reply to {0}", [
				frappe.utils.escape_html(question.update_source.toLowerCase()),
			])}</div>
			<textarea class="form-control cgm-reply-message" rows="3"
				placeholder="${frappe.utils.escape_html(__("Type your reply"))}"></textarea>
			<div class="cgm-reply-actions">
				<button type="button" class="btn btn-primary btn-sm cgm-reply-send">${__("Send reply")}</button>
			</div>
		</div>`).appendTo($body);

	$reply.find(".cgm-reply-send").on("click", function () {
		const $btn = $(this);
		const message = ($reply.find(".cgm-reply-message").val() || "").trim();

		if (!message) {
			frappe.msgprint({
				title: __("Reply"),
				indicator: "orange",
				message: __("Type a reply before sending."),
			});
			return;
		}

		$btn.prop("disabled", true);
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.reply_to_update",
			args: { name: question.name, message },
			freeze: true,
			callback(r) {
				if (r.exc) {
					return;
				}
				frappe.show_alert({ message: __("Reply sent."), indicator: "green" });
				frm.reload_doc();
			},
			always() {
				$btn.prop("disabled", false);
			},
		});
	});
}
