"""Send the two-factor login code by SMS as well as by email.

Frappe delivers the code one way only: System Settings > Two Factor Method is
Email, SMS or an authenticator app. CGM wants both, and choosing SMS there is
not an option - a user with no mobile number could then not log in at all.

So the method stays Email, and this adds the text beside it. Both carry the
same code: the email and SMS methods derive it from the same secret and
counter, so whichever arrives first works.

Frappe has no hook at the point the code is sent, so the email step is wrapped
at runtime. `ensure_login_code_sms` runs at the start of every request (the
`before_request` hook), which is what guarantees the wrap is in place before a
login is handled in a freshly started worker. It is a one-attribute check after
the first call.

The email path is never put at risk: the text is attempted after the email step
has returned, inside its own try, and only changes the on-screen prompt when it
was actually queued.

Off unless CGM Shipping Settings > Also send the login code by SMS is ticked.
"""

from __future__ import annotations

import frappe

SETTING = "send_login_code_by_sms"
_MARK = "_cgm_login_code_sms"


def login_code_sms_enabled() -> bool:
	try:
		settings = frappe.get_cached_doc("CGM Shipping Settings")
		return bool(settings.meta.has_field(SETTING) and settings.get(SETTING))
	except Exception:
		return False


def mask_number(number: str) -> str:
	return number[:4] + "******" + number[-3:] if len(number) > 7 else number


def send_login_code_sms(user: str, token, otp_secret: str) -> str | None:
	"""Queue the code to the user's mobile. Returns the number used, or None."""
	import pyotp

	from frappe.twofactor import get_rendered_otp_message

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_sms import (
		normalise_mobile,
		sms_gateway_configured,
	)

	if not login_code_sms_enabled() or not sms_gateway_configured():
		return None
	phone = frappe.db.get_value("User", user, ["mobile_no", "phone"], as_dict=True) or {}
	number = normalise_mobile(phone.get("mobile_no") or phone.get("phone"))
	if not number:
		return None

	otp = pyotp.HOTP(otp_secret).at(int(token))
	# Not after commit: the login request is not finished until the code is typed in.
	frappe.enqueue(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_sms.deliver_sms",
		queue="short",
		numbers=[number],
		text=get_rendered_otp_message(otp),
		source="login code",
	)
	return number


def ensure_login_code_sms() -> None:
	"""Wrap Frappe's email step of two-factor login, once per process."""
	import frappe.twofactor as twofactor

	original = twofactor.process_2fa_for_email
	if getattr(original, _MARK, False):
		return

	def process_2fa_for_email(user, token, otp_secret, otp_issuer, method="Email"):
		result = original(user, token, otp_secret, otp_issuer, method=method)
		# "OTP App" comes through here once, to email the QR code. That is setup,
		# not a login code, so nothing is texted for it.
		if method != "Email":
			return result
		try:
			number = send_login_code_sms(user, token, otp_secret)
			if number and isinstance(result, dict) and result.get("token_delivery"):
				result["prompt"] = frappe._(
					"Verification code has been sent to your registered email address and by SMS to {0}."
				).format(mask_number(number))
		except Exception:
			frappe.log_error(title="CGM login code SMS failed", message=frappe.get_traceback())
		return result

	setattr(process_2fa_for_email, _MARK, True)
	twofactor.process_2fa_for_email = process_2fa_for_email
