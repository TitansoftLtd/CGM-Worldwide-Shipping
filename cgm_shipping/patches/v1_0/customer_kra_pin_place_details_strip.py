"""Move KRA PIN field to Customer main details strip for sites created before insert_after changed."""

from cgm_shipping.patches.v1_0.customer_kra_pin_field import execute as ensure_kra_pin_field


def execute():
	ensure_kra_pin_field()
