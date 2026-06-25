// Copyright (c) 2026, Titansoft Limited and contributors

function initTransporterAllocationPage() {
	const page = document.getElementById("tp-allocation-page");
	if (!page || page.dataset.tpBound === "1") {
		return false;
	}

	const allocationName = page.dataset.allocation;

	function readAssignmentFields(form) {
		return {
			truck_number: form.querySelector(".tp-truck")?.value?.trim() || "",
			driver_name: form.querySelector(".tp-driver")?.value?.trim() || "",
			driver_contact: form.querySelector(".tp-contact")?.value?.trim() || "",
		};
	}

	function setButtonLoading(button, loading, loadingLabel) {
		if (!button) {
			return;
		}
		button.disabled = loading;
		const label = button.querySelector(".tp-btn-label");
		if (label) {
			if (loading) {
				if (!button.dataset.defaultLabel) {
					button.dataset.defaultLabel = label.textContent;
				}
				label.textContent = loadingLabel;
			} else if (button.dataset.defaultLabel) {
				label.textContent = button.dataset.defaultLabel;
			}
		}
	}

	function showDraftSavedUI(form) {
		form.dataset.hasDraft = "1";
		form.querySelector(".tp-draft-banner")?.classList.remove("d-none");
		form.querySelector(".tp-submit-hint")?.classList.add("d-none");
		const submitBtn = form.querySelector(".tp-submit-assignment");
		if (submitBtn) {
			submitBtn.classList.remove("d-none");
			submitBtn.disabled = false;
		}
		const row = form.closest(".tp-container-row");
		const pill = row?.querySelector(".tp-status-pill");
		if (pill) {
			pill.className = "indicator-pill blue tp-status-pill";
			pill.textContent = __("Draft saved");
		}
		form.querySelectorAll(".tp-step").forEach((step, index) => {
			if (index > 0) {
				step.classList.add("tp-step-active");
			}
		});
	}

	function showSaveSuccessPrompt(form, itemName, message) {
		showDraftSavedUI(form);
		frappe.show_alert({
			message: message || __("Draft saved."),
			indicator: "green",
		});
		frappe.msgprint({
			title: __("Draft saved"),
			indicator: "green",
			message: __(
				"Your truck and driver details are saved. Submit when you are ready to confirm the assignment, or keep editing below."
			),
			primary_action: {
				label: __("Submit now"),
				action() {
					frappe.hide_msgprint();
					submitAssignment(form, itemName, true);
				},
			},
		});
	}

	function parseCallError(response) {
		if (response?._server_messages) {
			try {
				const messages = JSON.parse(response._server_messages);
				const parsed = messages
					.map((msg) => {
						try {
							return JSON.parse(msg);
						} catch (e) {
							return { message: msg };
						}
					})
					.map((msg) => msg.message)
					.filter(Boolean);
				if (parsed.length) {
					return parsed.join(" ");
				}
			} catch (e) {
				// fall through
			}
		}
		return response?.message || __("Something went wrong. Please try again.");
	}

	function callAssignmentApi(method, form, itemName, values, options = {}) {
		const activeBtn =
			options.activeBtn ||
			form.querySelector(
				options.isSubmit ? ".tp-submit-assignment" : ".tp-save-draft"
			);
		const otherBtn = form.querySelector(
			options.isSubmit ? ".tp-save-draft" : ".tp-submit-assignment"
		);

		setButtonLoading(activeBtn, true, options.loadingLabel || __("Saving..."));
		setButtonLoading(otherBtn, false);

		return frappe.call({
			method,
			args: {
				allocation_name: allocationName,
				item_name: itemName,
				truck_number: values.truck_number,
				driver_name: values.driver_name,
				driver_contact: values.driver_contact,
			},
			freeze: true,
			freeze_message: options.freezeMessage || __("Please wait..."),
			callback(r) {
				setButtonLoading(activeBtn, false);
				if (r.exc) {
					frappe.msgprint({
						title: __("Could not complete"),
						indicator: "red",
						message: parseCallError(r),
					});
					return;
				}
				options.onSuccess?.(r);
			},
			error(r) {
				setButtonLoading(activeBtn, false);
				frappe.msgprint({
					title: __("Could not complete"),
					indicator: "red",
					message: parseCallError(r),
				});
			},
		});
	}

	function saveAssignment(form, itemName) {
		const values = readAssignmentFields(form);
		if (!values.truck_number && !values.driver_name) {
			frappe.msgprint({
				title: __("Enter details"),
				indicator: "orange",
				message: __("Enter at least a truck number or driver name before saving."),
			});
			return;
		}

		callAssignmentApi(
			"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal.save_truck_assignment",
			form,
			itemName,
			values,
			{
				freezeMessage: __("Saving draft..."),
				isSubmit: false,
				onSuccess(r) {
					const message = r.message?.message || __("Draft saved.");
					showSaveSuccessPrompt(form, itemName, message);
				},
			}
		);
	}

	function runSubmitAssignment(form, itemName, values) {
		callAssignmentApi(
			"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal.submit_truck_assignment_portal",
			form,
			itemName,
			values,
			{
				freezeMessage: __("Submitting assignment..."),
				loadingLabel: __("Submitting..."),
				isSubmit: true,
				onSuccess() {
					frappe.show_alert({
						message: __("Truck assignment submitted."),
						indicator: "green",
					});
					window.location.reload();
				},
			}
		);
	}

	function submitAssignment(form, itemName, skipConfirm) {
		const values = readAssignmentFields(form);
		if (!values.truck_number || !values.driver_name) {
			frappe.msgprint({
				title: __("Missing details"),
				indicator: "orange",
				message: __("Truck number and driver name are required before you can submit."),
			});
			return;
		}

		frappe.hide_msgprint();

		if (skipConfirm) {
			runSubmitAssignment(form, itemName, values);
			return;
		}

		const message =
			__("You are about to confirm this truck and driver assignment. CGM will be notified.") +
			`<p style="margin-top:.75rem;margin-bottom:0;"><b>${frappe.utils.escape_html(
				values.truck_number
			)}</b> · ${frappe.utils.escape_html(values.driver_name)}</p>`;

		// frappe.confirm() is unreliable on website pages — reuse msgprint like the save flow.
		frappe.msgprint({
			title: __("Submit assignment?"),
			indicator: "blue",
			message,
			primary_action: {
				label: __("Yes, submit"),
				action() {
					frappe.hide_msgprint();
					runSubmitAssignment(form, itemName, values);
				},
			},
			secondary_action: {
				label: __("Not yet"),
				action() {
					frappe.hide_msgprint();
				},
			},
		});
	}

	page.addEventListener("submit", (event) => {
		const form = event.target.closest(".tp-assign-form");
		if (form) {
			event.preventDefault();
		}
	});

	page.addEventListener("click", (event) => {
		const saveBtn = event.target.closest(".tp-save-draft");
		if (saveBtn) {
			event.preventDefault();
			const form = saveBtn.closest(".tp-assign-form");
			const row = form?.closest(".tp-container-row");
			if (form && row?.dataset.item) {
				saveAssignment(form, row.dataset.item);
			}
			return;
		}

		const submitBtn = event.target.closest(".tp-submit-assignment");
		if (submitBtn) {
			event.preventDefault();
			const form = submitBtn.closest(".tp-assign-form");
			const row = form?.closest(".tp-container-row");
			if (form && row?.dataset.item) {
				submitAssignment(form, row.dataset.item, false);
			}
		}
	});

	page.querySelectorAll(".tp-interchange-file").forEach((input) => {
		input.addEventListener("change", () => {
			const file = input.files?.[0];
			if (!file) {
				return;
			}
			const row = input.closest(".tp-container-row");
			const itemName = row?.dataset.item;

			const formData = new FormData();
			formData.append("file", file);
			formData.append("is_private", "1");
			formData.append("folder", "Home/Attachments");
			formData.append("doctype", "Container Allocation");
			formData.append("docname", allocationName);

			frappe.dom.freeze(__("Uploading interchange..."));
			fetch("/api/method/upload_file", {
				method: "POST",
				body: formData,
				headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
			})
				.then((response) => response.json())
				.then((data) => {
					if (data.exc) {
						frappe.throw(data._server_messages || __("Upload failed"));
					}
					const fileUrl = data.message?.file_url;
					if (!fileUrl) {
						frappe.throw(__("Upload failed. Please try again."));
					}
					return frappe.call({
						method:
							"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal.upload_interchange",
						args: {
							allocation_name: allocationName,
							item_name: itemName,
							interchange_document: fileUrl,
						},
					});
				})
				.then(() => {
					frappe.show_alert({
						message: __("Interchange receipt uploaded."),
						indicator: "green",
					});
					window.location.reload();
				})
				.catch((error) => {
					frappe.msgprint({
						title: __("Upload failed"),
						indicator: "red",
						message: error.message || __("Could not upload the file. Please try again."),
					});
				})
				.finally(() => frappe.dom.unfreeze());
		});
	});

	page.dataset.tpBound = "1";
	return true;
}

window.initTransporterAllocationPage = initTransporterAllocationPage;

function bootTransporterAllocationPage() {
	if (!document.getElementById("tp-allocation-page")) {
		return;
	}
	if (typeof frappe === "undefined" || typeof frappe.call !== "function") {
		return false;
	}
	return initTransporterAllocationPage();
}

function scheduleTransporterAllocationBoot() {
	if (bootTransporterAllocationPage()) {
		return;
	}
	let attempts = 0;
	const timer = setInterval(() => {
		attempts += 1;
		if (bootTransporterAllocationPage() || attempts > 200) {
			clearInterval(timer);
		}
	}, 50);
}

if (document.readyState === "loading") {
	document.addEventListener("DOMContentLoaded", scheduleTransporterAllocationBoot);
} else {
	scheduleTransporterAllocationBoot();
}

if (typeof frappe !== "undefined" && frappe.ready) {
	frappe.ready(scheduleTransporterAllocationBoot);
}
