// Copyright (c) 2026, Titansoft Limited and contributors
/**
 * Operational Updates — shared list cards + standard Frappe Dialog (Desk + portal).
 */
frappe.provide("cgm.updates");

(() => {
	const DETAIL_METHOD =
		"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_update_detail";

	function cintSafe(value) {
		if (typeof cint === "function") {
			return cint(value);
		}
		const n = parseInt(value, 10);
		return Number.isNaN(n) ? 0 : n;
	}

	function esc(value) {
		if (frappe.utils && frappe.utils.escape_html) {
			return frappe.utils.escape_html(value == null ? "" : String(value));
		}
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;");
	}

	function relativeTime(postedOn) {
		if (!postedOn) {
			return "";
		}
		if (frappe.datetime && frappe.datetime.prettyDate) {
			return frappe.datetime.prettyDate(postedOn);
		}
		if (frappe.datetime && frappe.datetime.str_to_user) {
			return frappe.datetime.str_to_user(postedOn);
		}
		return String(postedOn);
	}

	function previewMessage(message, maxLines = 3, maxLen = 180) {
		const text = (message || "").trim();
		if (!text) {
			return "";
		}
		const rawLines = text.split(/\r?\n/).filter(Boolean);
		const joined = rawLines.slice(0, maxLines).join(" ");
		const truncated =
			joined.length > maxLen || rawLines.length > maxLines
				? `${joined.slice(0, maxLen).trim()}…`
				: joined;
		return truncated;
	}

	function sourcePillClass(source) {
		const map = { Customer: "blue", Transporter: "orange", Internal: "gray" };
		return map[source] || "gray";
	}

	function sectionsToDialogFields(sections) {
		const fields = [];
		const values = {};

		(sections || []).forEach((section, sidx) => {
			if (section.label || sidx > 0) {
				fields.push({
					fieldtype: "Section Break",
					fieldname: `section_${sidx}`,
					label: section.label || "",
				});
			}

			(section.fields || []).forEach((f, fidx) => {
				if (f.fieldtype === "Column Break") {
					fields.push({
						fieldtype: "Column Break",
						fieldname: f.fieldname || `column_${sidx}_${fidx}`,
					});
					return;
				}

				const fieldname = f.fieldname || `field_${sidx}_${fidx}`;
				const fieldtype = f.fieldtype || "Data";
				fields.push({
					fieldname,
					label: f.label,
					fieldtype: fieldtype === "Attach" ? "Data" : fieldtype,
					options: fieldtype === "Attach" ? undefined : f.options || undefined,
					read_only: 1,
				});
				if (f.value != null && f.value !== "") {
					values[fieldname] = f.value;
				}
			});
		});

		return { fields, values };
	}

	function stripControlFieldnameTips(dialog) {
		// Website does not load desk form.scss (opacity:0 for .tooltip-content).
		// Same cleanup as portal FieldGroup forms — remove Control fieldname tips.
		Object.values(dialog.fields_dict || {}).forEach((ctrl) => {
			if (!ctrl) {
				return;
			}
			if (ctrl.tooltip && ctrl.tooltip.remove) {
				ctrl.tooltip.remove();
			}
			if (ctrl.$wrapper) {
				ctrl.$wrapper.find(".tooltip-content").remove();
			}
		});
		if (dialog.$wrapper) {
			dialog.$wrapper.find(".tooltip-content").remove();
		}
	}

	function nl2brSafe(value) {
		return esc(value).replace(/\r?\n/g, "<br>");
	}

	/**
	 * The conversation a message belongs to, rendered as a transcript: who said
	 * what, when, and - on a question - who at CGM answered it.
	 */
	function renderTranscript(messages, currentName) {
		const bubbles = (messages || [])
			.map((msg) => {
				const fromCgm = msg.from_cgm;
				const author = fromCgm
					? msg.posted_by_name
						? __("CGM · {0}", [msg.posted_by_name])
						: __("CGM")
					: msg.posted_by_name || msg.posted_by || msg.update_source;
				const answered =
					msg.response_status === "Answered" && msg.responded_by_name
						? `<div class="cgm-thread-note">${__("Answered by {0}", [
								esc(msg.responded_by_name),
							])}${msg.responded_on ? ` · ${esc(relativeTime(msg.responded_on))}` : ""}</div>`
						: msg.awaiting_response
							? `<div class="cgm-thread-note">${__("Awaiting a reply from CGM")}</div>`
							: "";
				return `<div class="cgm-thread-msg ${fromCgm ? "is-cgm" : "is-party"}${
					msg.name === currentName ? " is-current" : ""
				}">
					<div class="cgm-thread-head">
						<span class="cgm-thread-author">${esc(author)}</span>
						${
							!fromCgm
								? `<span class="indicator-pill ${sourcePillClass(
										msg.update_source
									)} no-indicator-dot">${esc((msg.update_source || "").toUpperCase())}</span>`
								: ""
						}
						<span class="cgm-thread-ref text-muted small">${esc(msg.name)}</span>
						<span class="cgm-thread-when text-muted small">${esc(relativeTime(msg.posted_on))}</span>
					</div>
					<div class="cgm-thread-subject">${esc(msg.subject || "")}</div>
					${msg.message ? `<div class="cgm-thread-body">${nl2brSafe(msg.message)}</div>` : ""}
					${
						msg.attachment
							? `<a href="${esc(msg.attachment)}" target="_blank" rel="noopener">${__(
									"View attachment"
								)}</a>`
							: ""
					}
					${answered}
				</div>`;
			})
			.join("");
		return `<div class="cgm-thread">${bubbles}</div>`;
	}

	cgm.updates.renderTranscript = renderTranscript;

	const PARTY_SOURCES = ["Customer", "Transporter"];

	/** The message in this thread that CGM owes an answer to, if any. */
	function answerableQuestion(thread) {
		return (thread || []).find((m) => PARTY_SOURCES.includes(m.update_source));
	}

	function scrollTranscript(d) {
		const control = d.fields_dict.conversation;
		const el = control && control.$wrapper.find(".cgm-thread")[0];
		if (el) {
			el.scrollTop = el.scrollHeight;
		}
	}

	/** Pull the thread again so a reply appears without closing the dialog. */
	function refreshTranscript(d, name) {
		frappe.call({
			method: DETAIL_METHOD,
			args: { name, include_source: 1 },
			callback(r) {
				if (r.exc || !d.fields_dict.conversation) {
					return;
				}
				const fresh = (r.message && r.message.thread) || [];
				d.fields_dict.conversation.$wrapper.html(renderTranscript(fresh, name));
				const section = d.fields_dict.section_conversation;
				if (section && section.$wrapper) {
					section.$wrapper
						.find(".section-head")
						.text(__("Conversation ({0} messages)", [fresh.length]));
				}
				scrollTranscript(d);
			},
		});
	}

	function sendReply(d, detail, question, v, options) {
		const message = (v.reply_message || "").trim();
		if (!message) {
			frappe.msgprint({
				title: __("Reply"),
				indicator: "orange",
				message: __("Type a reply before sending."),
			});
			return;
		}
		d.disable_primary_action();
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.reply_to_update",
			// No audience args: post_update_reply sends it back to whoever raised
			// the question.
			args: { name: question.name, message },
			freeze: true,
			callback(r) {
				if (r.exc) {
					return;
				}
				frappe.show_alert({ message: __("Reply sent."), indicator: "green" });
				d.set_value("reply_message", "");
				refreshTranscript(d, detail.name);
				if (typeof options.onReplied === "function") {
					options.onReplied(r.message, detail.name);
				}
			},
			always() {
				d.enable_primary_action();
			},
		});
	}

	/**
	 * One dialog for the whole exchange: the details, the conversation, and a
	 * reply box. Replying re-renders the transcript in place, so the dialog
	 * stays open and the exchange can carry on.
	 */
	function showDialogDetail(detail, options = {}) {
		const { fields, values } = sectionsToDialogFields(detail.sections);
		const thread = detail.thread || [];
		const question = answerableQuestion(thread);

		if (!fields.length && !thread.length) {
			frappe.msgprint(__("No details available."));
			return;
		}

		if (thread.length) {
			fields.push(
				{
					fieldtype: "Section Break",
					fieldname: "section_conversation",
					label:
						thread.length > 1
							? __("Conversation ({0} messages)", [thread.length])
							: __("Message"),
				},
				{
					fieldtype: "HTML",
					fieldname: "conversation",
					options: renderTranscript(thread, detail.name),
				}
			);
		}

		if (question) {
			// A reply goes back to whoever asked - the server works the audience
			// out from the question, so there is nothing to choose here.
			fields.push(
				{
					fieldtype: "Section Break",
					fieldname: "section_reply",
					label: __("Reply to {0}", [question.update_source.toLowerCase()]),
				},
				{
					fieldtype: "Small Text",
					fieldname: "reply_message",
					label: __("Your reply"),
				}
			);
		}

		const d = new frappe.ui.Dialog({
			// The reference is what a customer quotes back at you.
			title: `${detail.name} · ${detail.subject || __("Message")}`,
			fields,
			size: "extra-large",
			primary_action_label: question ? __("Send reply") : __("Close"),
			primary_action(v) {
				if (!question) {
					d.hide();
					return;
				}
				sendReply(d, detail, question, v, options);
			},
			secondary_action_label: question ? __("Close") : undefined,
			secondary_action: question ? () => d.hide() : undefined,
		});

		// Tooltips are created in Control.make() during Dialog construction.
		stripControlFieldnameTips(d);
		d.set_values(values);
		d.show();
		stripControlFieldnameTips(d);
		scrollTranscript(d);
	}

	function metaChips(row, options = {}) {
		const chips = [];
		if (!options.hideShipment && (row.project_ref || row.project)) {
			chips.push(
				`<span class="cgm-upd-chip is-ref">${esc(row.project_ref || row.project)}</span>`
			);
		}
		if (!options.hideCustomer && (row.customer_name || row.customer)) {
			chips.push(`<span class="cgm-upd-chip">${esc(row.customer_name || row.customer)}</span>`);
		}
		if (row.container_number) {
			chips.push(`<span class="cgm-upd-chip is-ref">${esc(row.container_number)}</span>`);
		}
		return chips.length ? `<div class="cgm-upd-meta">${chips.join("")}</div>` : "";
	}

	cgm.updates.renderListItem = function (row, options = {}) {
		const unread = !cintSafe(row.is_read);
		const awaiting = row.response_status === "Open";
		const answered = row.response_status === "Answered";
		const closed = row.response_status === "Closed";
		const subject = row.subject || row.update_type || __("Update");
		const source = options.showSource === false ? "" : row.update_source || "";
		const when = relativeTime(row.posted_on);
		const preview = previewMessage(row.message);
		const name = row.name || "";

		// Only a party's message carries response state - CGM's own posts are
		// not questions anyone owes an answer to.
		const state = closed
			? `<span class="cgm-upd-tag is-closed">${esc(__("Closed"))}</span>`
			: awaiting
				? `<span class="cgm-upd-tag is-awaiting">${esc(__("Awaiting reply"))}</span>`
				: answered
					? `<span class="cgm-upd-tag is-answered">${esc(__("Answered"))}</span>`
					: "";

		// The whole row opens the conversation, so there is no button marooned
		// at the far edge of a wide screen and the width can be used for the
		// message itself.
		return `<div class="cgm-upd-card${unread ? " is-unread" : ""}${
			awaiting ? " is-awaiting" : ""
		}${answered ? " is-answered" : ""}${
			closed ? " is-closed" : ""
		}" data-update="${esc(name)}" role="button" tabindex="0"
			aria-label="${esc(__("Open {0}", [subject]))}">
			<div class="cgm-upd-headline">
				<span class="cgm-upd-title">${esc(subject)}</span>
				${
					source
						? `<span class="cgm-upd-tag is-source is-${esc(
								source.toLowerCase()
							)}">${esc(source)}</span>`
						: ""
				}
				${state}
				<span class="cgm-upd-stamp">
					<span class="cgm-upd-ref">${esc(name)}</span>
					${when ? `<span class="cgm-upd-when">${esc(when)}</span>` : ""}
				</span>
			</div>
			${metaChips(row, options)}
			${preview ? `<p class="cgm-upd-preview">${esc(preview)}</p>` : ""}
			${
				answered && row.responded_by_name
					? `<div class="cgm-upd-answer">${esc(
							__("Answered by {0}", [row.responded_by_name])
						)}${row.responded_on ? ` · ${esc(relativeTime(row.responded_on))}` : ""}</div>`
					: ""
			}
		</div>`;
	};

	cgm.updates.renderCard = cgm.updates.renderListItem;

	cgm.updates.renderList = function (rows, options = {}) {
		const items = (rows || []).map((row) => cgm.updates.renderListItem(row, options));
		return `<div class="cgm-updates-list">${items.join("")}</div>`;
	};

	cgm.updates.openDetail = function (name, options = {}) {
		if (!name) {
			return;
		}

		const portal = options.showSource === false;
		const open = (detail) => {
			const run = () => {
				showDialogDetail(detail, options);
				if (typeof options.onOpened === "function") {
					options.onOpened(detail);
				}
			};
			if (frappe.ui && frappe.ui.Dialog) {
				run();
			} else {
				frappe.require("dialog.bundle.js", run);
			}
		};

		frappe.call({
			method: options.method || DETAIL_METHOD,
			args: {
				name,
				include_source: portal ? 0 : 1,
			},
			freeze: true,
			callback(r) {
				if (r.exc) {
					return;
				}
				open(r.message || {});
			},
		});
	};

	/**
	 * Desk: reply to a customer or transporter message inside its thread.
	 * The reply is published back to whoever started the thread, so it lands
	 * in that party's portal conversation and is emailed to them.
	 */
	/** Desk: publish an update to the customer and/or transporter portal. */
	cgm.updates.openPublishDialog = function (options = {}) {
		const d = new frappe.ui.Dialog({
			title: __("Post update to portal"),
			fields: [
				{
					fieldname: "project",
					label: __("Shipment"),
					fieldtype: "Link",
					options: "Project",
					reqd: 1,
					default: options.project || "",
				},
				{
					fieldname: "container_tracker",
					label: __("Container (optional)"),
					fieldtype: "Link",
					options: "Container Tracker",
					default: options.container_tracker || "",
					get_query() {
						const project = d.get_value("project");
						return project ? { filters: { project } } : {};
					},
				},
				{ fieldtype: "Section Break", fieldname: "content_section" },
				{
					fieldname: "subject",
					label: __("Subject"),
					fieldtype: "Data",
					reqd: 1,
				},
				{
					fieldname: "message",
					label: __("Message"),
					fieldtype: "Small Text",
					reqd: 1,
				},
				{ fieldtype: "Section Break", fieldname: "audience_section", label: __("Send to") },
				{
					fieldname: "to_customer",
					label: __("Customer portal"),
					fieldtype: "Check",
					default: 1,
				},
				{ fieldtype: "Column Break", fieldname: "audience_column" },
				{
					fieldname: "to_transporter",
					label: __("Transporter portal"),
					fieldtype: "Check",
					default: 0,
				},
			],
			primary_action_label: __("Post update"),
			primary_action(values) {
				if (!values.to_customer && !values.to_transporter) {
					frappe.msgprint({
						title: __("Send to"),
						indicator: "orange",
						message: __("Pick at least one portal to post this update to."),
					});
					return;
				}
				frappe.call({
					method:
						"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.publish_update",
					args: {
						subject: values.subject,
						message: values.message,
						project: values.project,
						container_tracker: values.container_tracker || "",
						to_customer: values.to_customer ? 1 : 0,
						to_transporter: values.to_transporter ? 1 : 0,
					},
					freeze: true,
					callback(r) {
						if (r.exc) {
							return;
						}
						d.hide();
						frappe.show_alert({
							message: (r.message && r.message.message) || __("Update posted."),
							indicator: "green",
						});
						if (typeof options.onSent === "function") {
							options.onSent(r.message);
						}
					},
				});
			},
		});
		d.show();
	};

	cgm.updates.markListItemRead = function ($root, name) {
		if (!$root || !name) {
			return;
		}
		const root = $root.jquery ? $root : $($root);
		root
			.find(`.cgm-upd-card[data-update="${esc(name)}"]`)
			.removeClass("is-unread");
	};

	cgm.updates.bindListClicks = function ($root, options = {}) {
		const root = $root && $root.jquery ? $root : $($root || document);
		root.off("click.cgmUpdates").off("keydown.cgmUpdates");
		root.on("keydown.cgmUpdates", ".cgm-upd-card", function (e) {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				$(this).trigger("click.cgmUpdates");
			}
		});
		root.on("click.cgmUpdates", ".cgm-upd-card, .cgm-upd-view-more", function (e) {
			e.preventDefault();
			e.stopPropagation();
			const name = $(this).data("update");
			cgm.updates.openDetail(name, {
				showSource: options.showSource,
				method: options.method,
				onOpened(detail) {
					cgm.updates.markListItemRead(root, name);
					if (typeof options.onOpened === "function") {
						options.onOpened(detail, name);
					}
				},
				onReplied(result) {
					cgm.updates.markListItemRead(root, name);
					if (typeof options.onReplied === "function") {
						options.onReplied(result, name);
					}
				},
			});
		});
	};

	cgm.updates.mount = function (root, rows, options = {}) {
		const $root = root && root.jquery ? root : $(root);
		if (!$root.length) {
			return;
		}
		$root.html(cgm.updates.renderList(rows || [], options));
		cgm.updates.bindListClicks($root, options);
	};

	cgm.updates.bindCardClicks = cgm.updates.bindListClicks;
})();
