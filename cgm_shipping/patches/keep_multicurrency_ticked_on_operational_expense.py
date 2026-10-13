"""Re-tick Multicurrency on Operational Expense requests where it was unticked.

Why: the box could be unticked by the requester, which forced every line on the
request back to the company currency. It is now read-only and always on for
Operational Expense. `default_multicurrency_on_operational_expense` ticked it on
the requests that existed when it ran; this catches any unticked since, including
submitted ones that can no longer be saved.

What: the same update that patch makes, run once more. Nothing recalculates: a
request that was unticked has every line in the company currency at rate 1, and
ticking the box leaves those lines exactly as they are.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

from cgm_shipping.patches.default_multicurrency_on_operational_expense import execute as tick_all


def execute():
	tick_all()
