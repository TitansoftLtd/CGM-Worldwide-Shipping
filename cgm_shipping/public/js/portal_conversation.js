// Copyright (c) 2026, Titansoft Limited and contributors
/**
 * Portal conversation + feedback widgets (customer and transporter portals).
 *
 * Plain DOM rather than frappe.ui.FieldGroup: these render inside the website
 * bundle, where desk form styling is not loaded, and a message thread wants
 * chat bubbles rather than a form layout.
 */
frappe.provide("cgm.portal");

(() => {
	const MAX_STARS = 5;

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

	function nl2br(value) {
		return esc(value).replace(/\r?\n/g, "<br>");
	}

	function when(postedOn) {
		if (!postedOn) {
			return "";
		}
		if (frappe.datetime && frappe.datetime.prettyDate) {
			return frappe.datetime.prettyDate(postedOn);
		}
		return String(postedOn);
	}

	function el(html) {
		const wrap = document.createElement("div");
		wrap.innerHTML = html.trim();
		return wrap.firstElementChild;
	}

	function toNode(root) {
		if (!root) {
			return null;
		}
		return root.jquery ? root[0] : root;
	}

	// ─── Conversation thread ─────────────────────────────────────────────

	function renderMessage(msg) {
		const outgoing = msg.direction === "out" || (!msg.from_cgm && msg.direction !== "in");
		// CGM messages are signed by the person who wrote them, so a party can
		// see who picked their question up.
		const author = msg.from_cgm
			? msg.posted_by_name
				? __("CGM Worldwide Shipping · {0}", [msg.posted_by_name])
				: __("CGM Worldwide Shipping")
			: msg.posted_by_name || msg.posted_by || __("You");
		const attachment = msg.attachment
			? `<a class="cp-msg-attach" href="${esc(msg.attachment)}" target="_blank" rel="noopener">
					${__("View attachment")}
				</a>`
			: "";
		const container = msg.container_number
			? `<span class="cp-msg-tag">${esc(msg.container_number)}</span>`
			: "";
		return `<div class="cp-msg ${outgoing ? "out" : "in"}${msg.unread ? " unread" : ""}" data-update="${esc(msg.name)}">
			<div class="cp-msg-head">
				<span class="cp-msg-author">${esc(author)}</span>
				${container}
				<span class="cp-msg-ref">${esc(msg.name)}</span>
				<span class="cp-msg-when">${esc(when(msg.posted_on))}</span>
			</div>
			<div class="cp-msg-subject">${esc(msg.subject || __("Update"))}</div>
			${msg.message ? `<div class="cp-msg-body">${nl2br(msg.message)}</div>` : ""}
			${attachment}
			${
				msg.response_status === "Answered" && msg.responded_by_name
					? `<div class="cp-msg-responder">${esc(
							__("Answered by {0}", [msg.responded_by_name])
						)}${msg.responded_on ? ` · ${esc(when(msg.responded_on))}` : ""}</div>`
					: msg.awaiting_response
						? `<div class="cp-msg-responder">${esc(__("Awaiting a reply from CGM"))}</div>`
						: ""
			}
		</div>`;
	}

	function renderThread(messages, options = {}) {
		if (!(messages || []).length) {
			return `<div class="cp-thread-empty">${esc(
				options.emptyText || __("No messages yet. Start the conversation below.")
			)}</div>`;
		}
		return `<div class="cp-thread">${messages.map(renderMessage).join("")}</div>`;
	}

	/** The message a thread hangs off - its status lives there. */
	function rootOf(messages) {
		if (!(messages || []).length) {
			return null;
		}
		const last = messages[messages.length - 1];
		const rootName = last.parent_update || last.name;
		return messages.find((m) => m.name === rootName) || messages[0];
	}

	/**
	 * The party owns their own question, so they decide when it is settled -
	 * and writing again reopens it, which the server does on its own.
	 */
	function renderStatusBar(messages, options = {}) {
		if (!options.statusMethod) {
			return "";
		}
		const root = rootOf(messages);
		if (!root || root.from_cgm) {
			return "";
		}
		const closed = root.response_status === "Closed";
		const state = closed
			? `<span class="cp-thread-state is-closed">${__("Closed")}</span>`
			: root.response_status === "Answered"
				? `<span class="cp-thread-state is-answered">${__("Answered")}</span>`
				: `<span class="cp-thread-state is-open">${__("Awaiting reply from CGM")}</span>`;
		const note =
			closed && root.closed_on
				? `<span class="cp-thread-closed-note">${esc(
						__("Closed {0}", [when(root.closed_on)])
					)}</span>`
				: "";
		return `<div class="cp-thread-bar" data-root="${esc(root.name)}">
			${state}${note}
			<button type="button" class="cp-thread-toggle" data-action="${closed ? "Open" : "Closed"}">
				${closed ? __("Reopen conversation") : __("Mark as resolved")}
			</button>
		</div>`;
	}

	/**
	 * Render a thread and, when `markReadMethod` is given, tell the server which
	 * CGM messages the party has now seen.
	 */
	cgm.portal.mountThread = function (root, messages, options = {}) {
		const node = toNode(root);
		if (!node) {
			return null;
		}
		let current = messages || [];

		function paint() {
			node.innerHTML = renderStatusBar(current, options) + renderThread(current, options);
			bindStatusToggle();
			if (options.scrollToLatest !== false) {
				const thread = node.querySelector(".cp-thread");
				if (thread) {
					thread.scrollTop = thread.scrollHeight;
				}
			}
		}

		function bindStatusToggle() {
			const btn = node.querySelector(".cp-thread-toggle");
			if (!btn) {
				return;
			}
			btn.addEventListener("click", () => {
				const bar = btn.closest(".cp-thread-bar");
				btn.disabled = true;
				frappe.call({
					method: options.statusMethod,
					args: Object.assign({}, options.statusArgs || {}, {
						name: bar.dataset.root,
						status: btn.dataset.action,
					}),
					freeze: true,
					callback(r) {
						if (r.exc) {
							return;
						}
						frappe.show_alert({
							message: (r.message && r.message.message) || __("Updated."),
							indicator: "green",
						});
						if (typeof options.onStatusChanged === "function") {
							options.onStatusChanged(r.message);
						}
					},
					always() {
						btn.disabled = false;
					},
				});
			});
		}

		function markRead() {
			if (!options.markReadMethod) {
				return;
			}
			const unread = current.filter((m) => m.unread).map((m) => m.name);
			if (!unread.length) {
				return;
			}
			frappe.call({
				method: options.markReadMethod,
				args: Object.assign({}, options.markReadArgs || {}, {
					names: JSON.stringify(unread),
				}),
				callback() {
					current = current.map((m) => Object.assign({}, m, { unread: false }));
				},
			});
		}

		paint();
		markRead();

		return {
			setMessages(next) {
				current = next || [];
				paint();
				markRead();
			},
			get messages() {
				return current;
			},
		};
	};

	// ─── Message composer ────────────────────────────────────────────────

	/**
	 * Message box.
	 *
	 * Starting a conversation asks for a subject, so it arrives in the ops feed
	 * as something they can pick up. Continuing one is just a message - the
	 * subject carries over server-side, and nobody retypes it.
	 */
	cgm.portal.mountComposer = function (root, options = {}) {
		const node = toNode(root);
		if (!node) {
			return null;
		}
		const containers = options.containers || [];
		const replying = Boolean(options.replyTo);
		const subjectControl = replying
			? ""
			: `<label class="cp-composer-label">${esc(
					options.subjectLabel || __("Subject")
				)} <span class="cp-reqd">*</span></label>
				<input type="text" class="form-control cp-composer-subject" maxlength="140"
					placeholder="${esc(options.subjectPlaceholder || __("What is this about?"))}">`;

		const containerControl = containers.length
			? `<label class="cp-composer-label">${esc(options.containerLabel || __("Container"))}</label>
				<select class="form-control cp-composer-container">
					<option value="">${__("All containers on this allocation")}</option>
					${containers
						.map(
							(c) =>
								`<option value="${esc(c.value || c.name)}">${esc(
									c.label || c.container_number || c.value || c.name
								)}</option>`
						)
						.join("")}
				</select>`
			: "";

		node.innerHTML = `
			<div class="cp-composer${replying ? " is-reply" : ""}">
				${containerControl}
				${subjectControl}
				${replying ? "" : `<label class="cp-composer-label">${__("Message")}</label>`}
				<textarea class="form-control cp-composer-message" rows="${replying ? 3 : 4}"
					placeholder="${esc(
						options.messagePlaceholder ||
							(replying
								? __("Write your reply…")
								: __("Type your message to the operations team"))
					)}"></textarea>
				<div class="cp-composer-actions">
					<button type="button" class="cp-btn cp-btn-primary cp-composer-send">
						${esc(options.sendLabel || (replying ? __("Send reply") : __("Send message")))}
					</button>
				</div>
			</div>`;

		const $message = node.querySelector(".cp-composer-message");
		const $send = node.querySelector(".cp-composer-send");
		const $container = node.querySelector(".cp-composer-container");
		const $subject = node.querySelector(".cp-composer-subject");

		function values() {
			return {
				// Blank on a reply: the server carries the subject over.
				subject: $subject ? ($subject.value || "").trim() : "",
				message: ($message.value || "").trim(),
				parent_update: options.replyTo || "",
				item_name: $container ? ($container.value || "").trim() : "",
			};
		}

		function validate() {
			const v = values();
			if ($subject && !v.subject) {
				frappe.msgprint({
					title: __("Subject"),
					indicator: "orange",
					message: __("Give this message a subject so we can pick it up."),
				});
				return null;
			}
			if (!v.message) {
				frappe.msgprint({
					title: __("Message"),
					indicator: "orange",
					message: __("Type a message before sending."),
				});
				return null;
			}
			return v;
		}

		$send.addEventListener("click", () => {
			const v = validate();
			if (!v || typeof options.onSend !== "function") {
				return;
			}
			$send.disabled = true;
			options.onSend(v, function done(ok) {
				$send.disabled = false;
				if (ok) {
					$message.value = "";
					if ($subject) {
						$subject.value = "";
					}
				}
			});
		});

		return { values, validate, clear() { $message.value = ""; } };
	};

	// ─── Feedback ────────────────────────────────────────────────────────

	// Frappe's Rating control markup, so the portal star row looks and behaves
	// exactly like the one in Desk. The website bundle does not load desk
	// controls.scss, so the matching styles live in customer_portal.css.
	const STAR_PATHS =
		'<path class="right-half" d="M11.9987 3.00011C12.177 3.00011 12.3554 3.09303 12.4471 3.27888L14.8213 8.09112C14.8941 8.23872 15.0349 8.34102 15.1978 8.3647L20.5069 9.13641C20.917 9.19602 21.0807 9.69992 20.7841 9.9892L16.9421 13.7354C16.8243 13.8503 16.7706 14.0157 16.7984 14.1779L17.7053 19.4674C17.7753 19.8759 17.3466 20.1874 16.9798 19.9945L12.2314 17.4973C12.1586 17.459 12.0786 17.4398 11.9987 17.4398V3.00011Z" fill="var(--star-fill)" stroke="var(--star-fill)"/>' +
		'<path class="left-half" d="M11.9987 3.00011C11.8207 3.00011 11.6428 3.09261 11.5509 3.27762L9.15562 8.09836C9.08253 8.24546 8.94185 8.34728 8.77927 8.37075L3.42887 9.14298C3.01771 9.20233 2.85405 9.70811 3.1525 9.99707L7.01978 13.7414C7.13858 13.8564 7.19283 14.0228 7.16469 14.1857L6.25116 19.4762C6.18071 19.8842 6.6083 20.1961 6.97531 20.0045L11.7672 17.5022C11.8397 17.4643 11.9192 17.4454 11.9987 17.4454V3.00011Z" fill="var(--star-fill)" stroke="var(--star-fill)"/>';

	function starsMarkup(readonly = false) {
		let stars = "";
		for (let i = 1; i <= MAX_STARS; i++) {
			stars += `<svg class="icon icon-md" data-rating="${i}" viewBox="0 0 24 24" fill="none"
				role="${readonly ? "presentation" : "button"}"${
					readonly ? "" : ' tabindex="0"'
				}>${STAR_PATHS}</svg>`;
		}
		return `<div class="rating cp-rating${readonly ? " cp-rating-static" : ""}"${
			readonly ? "" : ` role="slider" aria-valuemin="0" aria-valuemax="${MAX_STARS}"`
		}>${stars}</div>`;
	}

	/**
	 * Paint `value` stars, halves included - the same left-half / right-half
	 * split Frappe's Rating control uses, so 4.5 shows as four full stars and
	 * a half.
	 */
	function paintStars($rating, value, cls) {
		$rating.find("svg").each(function (index) {
			const $left = $(this).find(".left-half");
			const $right = $(this).find(".right-half");
			$left.removeClass("star-hover star-click");
			$right.removeClass("star-hover star-click");
			if (index + 0.5 <= value) {
				$left.addClass(cls);
			}
			if (index + 1 <= value) {
				$right.addClass(cls);
			}
		});
	}

	/** Whole star, or half, depending on which side of the star was hit. */
	function starValueAt(svg, pageX) {
		const $svg = $(svg);
		const whole = parseInt($svg.data("rating"), 10) || 0;
		if (pageX == null) {
			return whole;
		}
		const leftHalf = pageX - $svg.offset().left < $svg.width() / 2;
		return leftHalf ? whole - 0.5 : whole;
	}

	cgm.portal.mountFeedback = function (root, options = {}) {
		const node = toNode(root);
		if (!node) {
			return null;
		}
		const existing = options.value || null;
		let stars = existing ? existing.stars || 0 : 0;
		const categories = options.categories || ["Overall Service"];
		const picked = new Set(
			((existing && existing.containers) || []).map((c) => c.container_tracker)
		);

		node.innerHTML = `
			<div class="cp-feedback">
				${
					existing
						? `<div class="cp-feedback-note">${esc(
								__("You rated this on {0}. Submitting again updates your rating.", [
									frappe.datetime && frappe.datetime.str_to_user
										? frappe.datetime.str_to_user(existing.submitted_on)
										: existing.submitted_on,
								])
							)}</div>`
						: ""
				}
				<label class="cp-composer-label">${__("Rating")} <span class="cp-reqd">*</span></label>
				<div class="cp-stars-mount">${starsMarkup()}<span class="cp-rating-value"></span></div>
				<label class="cp-composer-label">${__("What is this about?")}</label>
				<select class="form-control cp-feedback-category">
					${categories
						.map(
							(c) =>
								`<option value="${esc(c)}"${
									existing && existing.category === c ? " selected" : ""
								}>${esc(c)}</option>`
						)
						.join("")}
				</select>
				${
					(options.containers || []).length
						? `<label class="cp-composer-label">${__("Containers this is about")}</label>
							<div class="cp-container-picker">
								${(options.containers || [])
									.map(
										(c) =>
											`<label class="cp-container-option">
												<input type="checkbox" value="${esc(c.value)}"${
													picked.has(c.value) ? " checked" : ""
												}>
												<span>${esc(c.label || c.value)}</span>
											</label>`
									)
									.join("")}
							</div>
							<div class="cp-field-hint">${__("Leave all unticked if this is about the whole shipment.")}</div>`
						: ""
				}
				<label class="cp-composer-label">${__("Comments")}</label>
				<textarea class="form-control cp-feedback-comments" rows="4"
					placeholder="${esc(__("Tell us what went well, or what we should fix"))}">${esc(
						existing ? existing.comments : ""
					)}</textarea>
				<label class="cp-feedback-check">
					<input type="checkbox" class="cp-feedback-recommend"${
						existing && existing.would_recommend ? " checked" : ""
					}>
					<span>${__("I would recommend CGM Worldwide Shipping")}</span>
				</label>
				<div class="cp-composer-actions">
					<button type="button" class="cp-btn cp-btn-primary cp-feedback-send">
						${existing ? __("Update feedback") : __("Submit feedback")}
					</button>
				</div>
				${
					existing && existing.response
						? `<div class="cp-feedback-response">
								<div class="cp-feedback-response-head">${__("CGM replied")}</div>
								<div>${nl2br(existing.response)}</div>
							</div>`
						: ""
				}
			</div>`;

		const $category = node.querySelector(".cp-feedback-category");
		const $comments = node.querySelector(".cp-feedback-comments");
		const $recommend = node.querySelector(".cp-feedback-recommend");
		const $send = node.querySelector(".cp-feedback-send");
		const $rating = $(node).find(".cp-rating");
		const $ratingValue = $(node).find(".cp-rating-value");

		function select(value) {
			stars = value;
			paintStars($rating, stars, "star-click");
			$rating.attr("aria-valuenow", stars);
			$ratingValue.text(stars ? `${stars}/${MAX_STARS}` : "");
		}

		$rating
			.on("mousemove", "svg", function (e) {
				paintStars($rating, starValueAt(this, e.pageX), "star-hover");
			})
			.on("mouseleave", function () {
				paintStars($rating, stars, "star-click");
			})
			.on("click", "svg", function (e) {
				select(starValueAt(this, e.pageX));
			})
			.on("keydown", "svg", function (e) {
				if (e.key === "Enter" || e.key === " ") {
					e.preventDefault();
					// Keyboard picks whole stars; halves need the pointer.
					select(starValueAt(this, null));
				}
			});

		select(stars);

		$send.addEventListener("click", () => {
			if (!stars) {
				frappe.msgprint({
					title: __("Rating"),
					indicator: "orange",
					message: __("Pick a star rating first."),
				});
				return;
			}
			if (typeof options.onSubmit !== "function") {
				return;
			}
			$send.disabled = true;
			options.onSubmit(
				{
					rating: stars,
					category: $category.value,
					comments: ($comments.value || "").trim(),
					would_recommend: $recommend.checked ? 1 : 0,
					containers: JSON.stringify(
						Array.from(
							node.querySelectorAll(".cp-container-picker input:checked"),
							(el) => el.value
						)
					),
				},
				function done() {
					$send.disabled = false;
				}
			);
		});

		return {
			get stars() {
				return stars;
			},
		};
	};

	/** Read-only star row (e.g. an average), same look as the input. */
	cgm.portal.renderStars = function (stars) {
		const filled = Math.round(stars || 0);
		const $row = $(starsMarkup(true));
		paintStars($row, filled, "star-click");
		return $row.prop("outerHTML");
	};
})();
