"""Add invoice thank-you line to Main Letter Head footer. Idempotent."""

from __future__ import annotations

import frappe

THANK_YOU = "Thank you for your business."

FOOTER_HTML = """<div style="width: 100%; border-bottom: 0px solid #000;">
    <div style="text-align: center;">
        <p style="margin: 0 0 6px; color: #171717; font-size: 13px; font-weight: 700;">Thank you for your business.</p>
        <h3 style="margin: 0;"><strong>CGM Worldwide Shipping Limited</strong></h3>
        <p style="margin: 0;">7th floor, The Oval, Ring Road Parklands.</p>
        <!--<p style="margin: 0;">P.O Box 56248 - 00200 Nairobi | Tel: +254 715 708 808</p>-->
        <p style="margin: 0;">
            Website: <a href="https://cgmshipping.com/">www.cgmshipping.com</a> |  
            Email: <a href="mailto:info@cgmshipping.com">info@cgmshipping.com</a>
        </p>
    </div>
</div>"""


def execute() -> None:
	if not frappe.db.exists("Letter Head", "Main"):
		return

	current = frappe.db.get_value("Letter Head", "Main", "footer") or ""
	if THANK_YOU in current and "CGM Worldwide Shipping Limited" in current:
		return

	frappe.db.set_value("Letter Head", "Main", "footer", FOOTER_HTML, update_modified=True)
	frappe.clear_cache(doctype="Letter Head")
