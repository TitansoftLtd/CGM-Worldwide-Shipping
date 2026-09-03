frappe.ready(function () {
	const web_form = frappe.web_form;
	if (!web_form) return;

	// Rendered server-side by cgm_job_application.py.
	const COUNTIES = JSON.parse(`{{ cgm_county_options }}`);
	const JOB_OPENING = JSON.parse(`{{ cgm_job_opening }}`);

	const country_field = web_form.fields_dict["country"];
	const county_field = web_form.fields_dict["custom_territory"];

	function filter_counties() {
		if (!county_field) return;

		const country = country_field ? country_field.get_value() : null;
		const options = COUNTIES.filter((c) => country && c.country === country).map((c) => ({
			value: c.value,
			label: c.label,
		}));
		county_field.set_data(options);

		const current = county_field.get_value();
		if (current && !options.some((o) => o.value === current)) {
			county_field.set_value("");
		}
	}

	if (county_field && country_field) {
		web_form.on("country", filter_counties);
		filter_counties();
	}

	const head = document.querySelector(".web-form-head");
	if (head && !head.querySelector(".cgm-web-form-logo")) {
		const logo = document.createElement("img");
		logo.className = "cgm-web-form-logo";
		logo.src = "/assets/cgm_shipping/images/CGM%20Logo.png";
		logo.alt = "CGM Worldwide Shipping Company Limited";
		head.prepend(logo);
	}

	// Locked to a vacancy, the control renders its raw value - the Job Opening's id.
	// set_disp_area re-reads this.value each repaint, so writing the DOM once loses
	// the race with set_default_values; the renderer is replaced instead. Chosen from
	// the dropdown, the Autocomplete shows the title on its own. A stale or closed
	// vacancy left in the URL must not prefill it.
	const job_field = web_form.fields_dict["job_title"];
	if (job_field) {
		if (JOB_OPENING && JOB_OPENING.job_title) {
			job_field.set_disp_area = function (value) {
				const current = this.value || value;
				const match = (this._data || []).find((d) => d.value === current);
				const label = (match && match.label) || JOB_OPENING.job_title || current;
				if (this.disp_area) $(this.disp_area).text(label);
			};
			job_field.set_disp_area(job_field.value);
		} else if (frappe.utils.get_query_params().job_title) {
			job_field.set_value("");
		}
	}
});
