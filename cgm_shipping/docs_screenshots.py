"""Regenerate the screenshots used by `docs/` from a live site.

Why this exists: the guides under `docs/` are the source of truth for the CGM
Shipping wiki (see `customizations/wiki_docs.py`). Their screenshots went stale
because there was no way to retake them, so most guides shipped without any.

This drives the headless Chromium that Frappe already bundles for PDF generation
(`frappe.utils.pdf_generator`) - no Playwright, Selenium or other new dependency.
Each shot is one `Shot` in SHOTS below, so retaking the whole set after a UI
change is one command.

Four things it does beyond a plain screenshot:

1. **Full-width content.** The desk sidebar takes 220px of a 1600px frame and
   carries nothing a reader needs. It is collapsed via the `sidebar-expanded`
   localStorage key before the page loads, so the record fills the frame.
2. **Anonymised.** Real customer, supplier and staff names are rewritten *in the
   browser* immediately before the capture - the database is never touched.
   Names map to stable fictional aliases, so the same customer reads as the same
   company in every shot.
3. **Arrow callouts.** Annotations anchor to CSS selectors, not pixel
   coordinates, so they stay attached to the right control when the UI moves.
   Each is a numbered badge the guide's prose can refer to.
4. **Blank-frame guard.** A failed navigation still screenshots successfully, as
   a white rectangle. Frames with no content are rejected rather than written.

Usage
-----
    export CGM_DOCS_API_TOKEN="<api_key>:<api_secret>"   # a desk user with read access
    export CGM_DOCS_BASE_URL="http://127.0.0.1:8004"     # where the site actually answers
    bench --site <site> execute cgm_shipping.docs_screenshots.capture_all

    # one guide's shots only
    bench --site <site> execute cgm_shipping.docs_screenshots.capture_all \
        --kwargs '{"only": "crm-intake"}'

    # keep real names (internal-only docs)
    bench --site <site> execute cgm_shipping.docs_screenshots.capture_all \
        --kwargs '{"anonymise": false}'

The token is read from the environment and never stored. Generate one under
User > API Access, and revoke it when the run is done.

Notes
-----
- Chromium's default start timeout is 3s, which is not enough on a cold cache.
  Set it once per site: `bench --site <site> set-config chromium_start_timeout 40`.
- `get_host_url()` returns the site name as the host (`http://cgm:8004`), which
  Chromium cannot resolve - it renders blank rather than failing. Always set
  CGM_DOCS_BASE_URL on a local bench.
"""

from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import frappe

# cgm_shipping/ -> app root, where docs/ lives
DOCS_IMAGES = Path(__file__).resolve().parents[1] / "docs" / "images"

DEFAULT_WIDTH = 1600
DEFAULT_HEIGHT = 1000
# Desk is a SPA: the route resolves long before the list or form has rendered.
DEFAULT_WAIT_MS = 7000
# A rendered desk page is tens of KB as PNG; anything smaller is a blank frame.
BLANK_PNG_BYTES = 20_000

ACCENT = (29, 78, 216)  # blue-700: reads on the desk's greys, and in print
ACCENT_TEXT = (255, 255, 255)
FONT_CANDIDATES = (
	"/System/Library/Fonts/Supplemental/Arial Bold.ttf",
	"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
	"/System/Library/Fonts/Helvetica.ttc",
)

#: Fictional companies real customer names are mapped onto, in order.
ALIASES = (
	"Acme Traders Ltd",
	"Northwind Imports",
	"Meridian Foods Ltd",
	"Bluepeak Commodities",
	"Harbourline Ltd",
	"Sunfield Agri Ltd",
	"Castleford Trading",
	"Greenmark Supplies",
	"Orchid Bay Ltd",
	"Tradewind Partners",
	"Silverbirch Ltd",
	"Cobalt Union Ltd",
)

#: Fictional hauliers and vendors real supplier names are mapped onto.
SUPPLIER_ALIASES = (
	"Rift Haulage Ltd",
	"Summit Transporters",
	"Kestrel Logistics",
	"Ironway Carriers Ltd",
	"Baobab Freight Ltd",
	"Redstone Haulage",
	"Lakeside Movers Ltd",
	"Anvil Transport Co",
)

#: Carriers left un-anonymised - public companies, and naming them helps the reader.
PUBLIC_CARRIERS = frozenset(
	{
		"MAERSK",
		"MSC",
		"PIL",
		"COSCO",
		"CMA CGM",
		"HAPAG-LLOYD",
		"ONE",
		"EVERGREEN",
		"KPA",
		"KRA",
	}
)


@dataclass
class Annotation:
	"""An arrow callout anchored to a CSS selector."""

	selector: str
	label: str
	#: which side of the target the label sits on
	side: str = "right"


@dataclass
class Shot:
	stem: str
	route: str
	guide: str
	annotations: list[Annotation] = field(default_factory=list)


SHOTS: list[Shot] = [
	# --- CRM & intake -------------------------------------------------------
	Shot("opportunity-list", "opportunity", "crm-intake"),
	Shot(
		"opportunity-form",
		"opportunity/{opportunity}",
		"crm-intake",
		[
			Annotation(".indicator-pill, .form-status-indicator", "Intake stage", "below"),
			Annotation("[data-fieldname='custom_shipment_type']", "Picks the task plan", "right"),
		],
	),
	# --- Commercial ---------------------------------------------------------
	Shot("quotation-list", "quotation", "commercial"),
	Shot(
		"quotation-form",
		"quotation/{quotation}",
		"commercial",
		[
			Annotation("[data-fieldname='custom_import_cost_component']", "Import valuation", "right"),
		],
	),
	# --- Operations ---------------------------------------------------------
	Shot("project-list", "project", "operations"),
	Shot("container-tracker-list", "container-tracker", "operations"),
	Shot(
		"task-form",
		"task/{task}",
		"operations",
		[
			Annotation("[data-fieldname='department']", "Who owns the task", "right"),
			Annotation("[data-fieldname='custom_task_documents']", "Completion gate", "above"),
		],
	),
	# --- Declaration & customs ---------------------------------------------
	Shot("customs-entry-list", "customs-entry", "declaration-customs"),
	Shot("customs-entry-form", "customs-entry/{customs_entry}", "declaration-customs"),
	# --- Transport & containers --------------------------------------------
	Shot("container-allocation-list", "container-allocation", "transport-containers"),
	Shot(
		"container-allocation-form",
		"container-allocation/{container_allocation}",
		"transport-containers",
		[
			Annotation("[data-fieldname='transporter']", "Who hauls it", "right"),
			Annotation("[data-fieldname='containers']", "Containers on the job", "above"),
		],
	),
	# --- Deposits & charges -------------------------------------------------
	Shot("bill-of-lading-form", "bill-of-lading/{bill_of_lading}", "deposits-and-charges"),
	# --- Finance ------------------------------------------------------------
	Shot("sales-invoice-list", "sales-invoice", "finance"),
	Shot(
		"sales-invoice-form",
		"sales-invoice/{sales_invoice}",
		"finance",
		[Annotation("[data-fieldname='project']", "Ties cost to the shipment", "right")],
	),
	# --- Funding ------------------------------------------------------------
	Shot(
		"funding-request-form",
		"funding-request/{funding_request}",
		"funding",
		[Annotation("[data-fieldname='material_requests']", "One row per request", "above")],
	),
	Shot("material-request-list", "material-request", "funding"),
	# --- Shipment modes & types --------------------------------------------
	Shot("shipment-type-list", "shipment-type", "shipment-types"),
	Shot(
		"task-template-form",
		"cgm-task-template/{cgm_task_template}",
		"shipment-modes",
		[Annotation("[data-fieldname='tasks']", "The ordered plan", "above")],
	),
	# --- Settings -----------------------------------------------------------
	Shot("cgm-shipping-settings", "cgm-shipping-settings", "customizations"),
	# --- Patches ------------------------------------------------------------
	Shot("patch-log-list", "patch-log", "patches"),
]


# --------------------------------------------------------------------------
# sample records
# --------------------------------------------------------------------------


def _sample_records() -> dict[str, str]:
	"""One representative record per doctype the routes interpolate."""

	def pick(doctype: str, filters: dict | None = None) -> str:
		rows = frappe.get_all(doctype, filters=filters or {}, pluck="name", order_by="modified desc", limit=1)
		return rows[0] if rows else ""

	return {
		"opportunity": pick("Opportunity"),
		"quotation": pick("Quotation"),
		"sales_invoice": pick("Sales Invoice"),
		"funding_request": pick("Funding Request"),
		"container_allocation": pick("Container Allocation"),
		"customs_entry": pick("Customs Entry"),
		"bill_of_lading": pick("Bill of Lading"),
		"cgm_task_template": pick("CGM Task Template"),
		"task": pick("Task", {"project": ["is", "set"]}),
		"project": pick("Project"),
	}


def build_alias_map() -> dict[str, str]:
	"""Real name -> fictional alias, stable across runs.

	Covers customers, the staff whose names appear in assignment chips and
	owner columns, and their email addresses. Sorted so a given customer keeps
	the same alias between runs and the docs stay internally consistent.
	"""
	mapping: dict[str, str] = {}

	customers = sorted(frappe.get_all("Customer", pluck="name"))
	for i, name in enumerate(customers):
		mapping[name] = ALIASES[i % len(ALIASES)]

	# Suppliers are real trading relationships too - transporters especially.
	# Global carriers are left alone: they are public, and a guide that says
	# "MAERSK" is more useful than one that says "Carrier 3".
	suppliers = sorted(frappe.get_all("Supplier", pluck="name"))
	for i, name in enumerate(s for s in suppliers if s.upper() not in PUBLIC_CARRIERS):
		mapping[name] = SUPPLIER_ALIASES[i % len(SUPPLIER_ALIASES)]

	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User"},
		fields=["name", "full_name", "first_name"],
	)
	for i, u in enumerate(sorted(users, key=lambda r: r.name)):
		alias_name = f"Demo User {i + 1}"
		if u.full_name and u.full_name not in ("Administrator", "Guest"):
			mapping[u.full_name] = alias_name
		if u.first_name and len(u.first_name) > 3:
			mapping[u.first_name] = alias_name.split()[-1]
		if "@" in (u.name or ""):
			mapping[u.name] = f"user{i + 1}@example.com"

	# Longest first, so "Acme Traders Ltd" is not half-replaced by "Acme".
	return dict(sorted(mapping.items(), key=lambda kv: -len(kv[0])))


# --------------------------------------------------------------------------
# browser-side helpers
# --------------------------------------------------------------------------

_COLLAPSE_SIDEBAR_JS = """
try { localStorage.setItem('sidebar-expanded', 'false'); } catch (e) {}
"""

# Frappe persists list filters per user, so whoever the token belongs to can have a
# saved filter that hides every row - the capture then shows an empty-state panel
# instead of the list. Clear through the framework's own filter area so the list
# refreshes properly rather than fighting the saved user settings.
_CLEAR_FILTERS_JS = """
(function () {
  try {
    if (window.cur_list && cur_list.filter_area) { cur_list.filter_area.clear(); return 1; }
  } catch (e) {}
  return 0;
})()
"""

_ANONYMISE_JS = """
(function (pairs) {
  var n = 0;
  function swap(s) {
    for (var i = 0; i < pairs.length; i++) {
      if (s.indexOf(pairs[i][0]) > -1) { s = s.split(pairs[i][0]).join(pairs[i][1]); n++; }
    }
    return s;
  }
  var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  var texts = [];
  while (w.nextNode()) texts.push(w.currentNode);
  texts.forEach(function (t) { var v = swap(t.nodeValue); if (v !== t.nodeValue) t.nodeValue = v; });
  document.querySelectorAll('input, textarea').forEach(function (e) {
    if (e.value) { var v = swap(e.value); if (v !== e.value) e.value = v; }
    if (e.placeholder) e.placeholder = swap(e.placeholder);
  });
  document.querySelectorAll('[title], [aria-label], [data-original-title]').forEach(function (e) {
    ['title', 'aria-label', 'data-original-title'].forEach(function (a) {
      var v = e.getAttribute(a); if (v) e.setAttribute(a, swap(v));
    });
  });
  return n;
})(%s)
"""

# Every field, control and grid on the page, so a callout can be parked in the
# margin rather than on top of one. Scoring on pixel darkness alone is not
# enough: the empty right-hand half of a text input reads as blank, so a label
# lands on the control and looks like it is covering data.
_OBSTACLES_JS = """
JSON.stringify((function () {
  var out = [];
  document.querySelectorAll(
    '[data-fieldname], .frappe-control, .form-grid, .form-section, .page-head, .comment-box'
  ).forEach(function (e) {
    var r = e.getBoundingClientRect();
    if (r.width > 8 && r.height > 8 && r.bottom > 0 && r.top < window.innerHeight) {
      out.push({x: r.x, y: r.y, w: r.width, h: r.height});
    }
  });
  return out;
})())
"""

_RECTS_JS = """
JSON.stringify((function (sels) {
  return sels.map(function (s) {
    var e = null;
    try { e = document.querySelector(s); } catch (err) { return null; }
    if (!e) return null;
    var r = e.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    return {x: r.x, y: r.y, w: r.width, h: r.height};
  });
})(%s))
"""


def _value(result: dict):
	return (result or {}).get("result", {}).get("value")


# --------------------------------------------------------------------------
# annotation drawing
# --------------------------------------------------------------------------


def _font(size: int):
	from PIL import ImageFont

	for path in FONT_CANDIDATES:
		try:
			return ImageFont.truetype(path, size)
		except Exception:
			continue
	return ImageFont.load_default()


def _ink_ratio(image, box: tuple[float, float, float, float]) -> float:
	"""Fraction of the region that carries content rather than background.

	Desk backgrounds are white or near-white and text and borders are dark, so
	counting dark pixels is a good enough proxy for "something is written here".
	Used to park a callout in empty space instead of on top of a field.
	"""
	x0, y0, x1, y1 = (int(v) for v in box)
	x0, y0 = max(0, x0), max(0, y0)
	x1, y1 = min(image.width, x1), min(image.height, y1)
	if x1 <= x0 or y1 <= y0:
		return 1.0
	crop = image.crop((x0, y0, x1, y1)).convert("L")
	hist = crop.histogram()
	return sum(hist[:205]) / float(crop.width * crop.height)


def _overlaps(a, b, pad: int = 6) -> bool:
	return not (a[2] + pad < b[0] or a[0] > b[2] + pad or a[3] + pad < b[1] or a[1] > b[3] + pad)


def _place_label(image, target, box_w, box_h, preferred, taken, obstacles=()):
	"""Choose where a callout sits: the emptiest spot that clears the target.

	Candidates radiate from the target on all four sides at increasing distance.
	Each is scored on how much content it would cover, with a nudge towards the
	caller's preferred side, and anything overlapping the target or a label
	already placed is discarded outright.
	"""
	x0, y0, x1, y1 = target
	W, H = image.size
	cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
	best = None

	for gap in (46, 76, 112, 150, 200, 260):
		for side in ("right", "left", "above", "below"):
			if side == "right":
				ax, ay = x1, cy
				bx, by = ax + gap, ay - box_h / 2
			elif side == "left":
				ax, ay = x0, cy
				bx, by = ax - gap - box_w, ay - box_h / 2
			elif side == "above":
				ax, ay = cx, y0
				bx, by = ax - box_w / 2, ay - gap - box_h
			else:
				ax, ay = cx, y1
				bx, by = ax - box_w / 2, ay + gap

			bx = max(8, min(bx, W - box_w - 8))
			by = max(8, min(by, H - box_h - 8))
			box = (bx, by, bx + box_w, by + box_h)

			if _overlaps(box, target) or any(_overlaps(box, t) for t in taken):
				continue
			if any(_overlaps(box, o, pad=0) for o in obstacles):
				continue

			# Score the label footprint plus a little margin around it.
			score = _ink_ratio(image, (bx - 4, by - 4, bx + box_w + 4, by + box_h + 4))
			if side != preferred:
				score += 0.02
			score += gap / 12000.0  # all else equal, stay near the target
			if best is None or score < best[0]:
				best = (score, box, (ax, ay))

	if best is None and obstacles:
		# Dense form with no clear margin: drop the obstacle rule and fall back to
		# the emptiest-looking spot, which at least avoids covering text.
		return _place_label(image, target, box_w, box_h, preferred, taken, ())
	if best is None:
		bx = max(8, min(x1 + 46, W - box_w - 8))
		by = max(8, min(cy - box_h / 2, H - box_h - 8))
		return (bx, by, bx + box_w, by + box_h), (x1, cy)
	return best[1], best[2]


def _draw_annotations(image, rects: list[dict | None], annotations: list[Annotation], obstacles=()):
	"""Draw a numbered badge and an arrow onto `image` for each located target."""
	import math

	from PIL import ImageDraw

	draw = ImageDraw.Draw(image)
	label_font = _font(19)
	badge_font = _font(17)
	drawn = 0
	taken: list[tuple[float, float, float, float]] = []

	for idx, (rect, ann) in enumerate(zip(rects, annotations, strict=False), start=1):
		if not rect:
			continue

		target = (
			rect["x"] - 3,
			rect["y"] - 3,
			rect["x"] + rect["w"] + 3,
			rect["y"] + rect["h"] + 3,
		)
		# Outline the target so the arrow has something to point at.
		draw.rounded_rectangle(list(target), radius=6, outline=ACCENT, width=3)

		text = ann.label
		box_w = int(draw.textlength(text, font=label_font)) + 52
		box_h = 36
		box, (ax, ay) = _place_label(image, target, box_w, box_h, ann.side, taken, obstacles)
		taken.append(box)
		taken.append(target)
		bx, by = box[0], box[1]

		# Arrow from the label's nearest edge to the target anchor.
		cx, cy = bx + box_w / 2, by + box_h / 2
		sx = bx + box_w if cx < ax else (bx if cx > ax else cx)
		sy = max(by, min(cy, by + box_h))
		draw.line([(sx, sy), (ax, ay)], fill=ACCENT, width=3)

		angle = math.atan2(ay - sy, ax - sx)
		head = 11
		draw.polygon(
			[
				(ax, ay),
				(ax - head * math.cos(angle - 0.5), ay - head * math.sin(angle - 0.5)),
				(ax - head * math.cos(angle + 0.5), ay - head * math.sin(angle + 0.5)),
			],
			fill=ACCENT,
		)

		# Label pill with a numbered badge.
		draw.rounded_rectangle([bx, by, bx + box_w, by + box_h], radius=18, fill=ACCENT)
		draw.ellipse([bx + 6, by + 6, bx + 30, by + 30], fill=ACCENT_TEXT)
		draw.text((bx + 18, by + box_h / 2), str(idx), font=badge_font, fill=ACCENT, anchor="mm")
		draw.text((bx + 40, by + box_h / 2), text, font=label_font, fill=ACCENT_TEXT, anchor="lm")
		drawn += 1

	return drawn


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------


def _is_blank(png_bytes: bytes, image) -> bool:
	if len(png_bytes) > BLANK_PNG_BYTES:
		return False
	return len(image.convert("RGB").getcolors(maxcolors=64) or []) <= 2


def _base_url() -> str:
	override = os.environ.get("CGM_DOCS_BASE_URL")
	if override:
		return override.rstrip("/")

	from frappe.utils.pdf import get_host_url

	return get_host_url().rstrip("/")


def capture_all(
	only: str | None = None,
	width: int = DEFAULT_WIDTH,
	height: int = DEFAULT_HEIGHT,
	wait: int = DEFAULT_WAIT_MS,
	anonymise: bool = True,
) -> None:
	"""Capture every shot in SHOTS (or just one guide's) into docs/images."""
	from frappe.utils.pdf_generator.cdp_connection import CDPSocketClient
	from frappe.utils.pdf_generator.chrome_pdf_generator import ChromePDFGenerator
	from frappe.utils.pdf_generator.page import Page
	from PIL import Image

	token = os.environ.get("CGM_DOCS_API_TOKEN")
	if not token:
		frappe.throw(
			"Set CGM_DOCS_API_TOKEN=<api_key>:<api_secret> before running. See the module docstring."
		)

	DOCS_IMAGES.mkdir(parents=True, exist_ok=True)
	records = _sample_records()
	base = _base_url()
	headers = {"Authorization": f"token {token}"}
	pairs = list(build_alias_map().items()) if anonymise else []

	wanted = [s for s in SHOTS if not only or s.guide == only]
	if not wanted:
		frappe.throw(f"No shots match guide {only!r}. Known: {sorted({s.guide for s in SHOTS})}")

	generator = ChromePDFGenerator()
	browser_id = frappe.utils.random_string(10)
	generator.add_browser(browser_id)
	done, skipped = [], []

	try:
		if not generator._devtools_url:
			generator._set_devtools_url()

		for shot in wanted:
			try:
				resolved = shot.route.format(**records)
			except KeyError as exc:
				skipped.append((shot.stem, f"no sample record for {exc}"))
				continue
			if "{" in resolved or resolved.rsplit("/", 1)[-1] == "":
				skipped.append((shot.stem, "no sample record on this site"))
				continue

			url = f"{base}/desk/{resolved}"
			session = page = context = None
			try:
				session = CDPSocketClient(generator._devtools_url)
				session.connect()
				context, error = session.send("Target.createBrowserContext", {"disposeOnDetach": True})
				if error:
					raise RuntimeError(f"browser context: {error}")

				page = Page(session, context["browserContextId"], "screenshot")
				page.is_print_designer = False
				page.set_media_emulation("screen")
				page.set_device_metrics(width, height)
				page.send("Network.enable")
				page.send("Network.setExtraHTTPHeaders", {"headers": headers})

				# Collapse the sidebar before the desk boots, so the record gets
				# the full frame rather than 220px of navigation.
				page.navigate(f"{base}/desk")
				time.sleep(2)
				page.evaluate(_COLLAPSE_SIDEBAR_JS)

				page.navigate(url)
				time.sleep(wait / 1000)

				# List routes only: drop any saved filter that would hide the rows.
				if "/" not in resolved:
					if _value(page.evaluate(_CLEAR_FILTERS_JS)):
						time.sleep(3)

				if pairs:
					swapped = _value(page.evaluate(_ANONYMISE_JS % json.dumps(pairs)))
				else:
					swapped = 0

				rects = []
				obstacles = []
				if shot.annotations:
					raw_obs = _value(page.evaluate(_OBSTACLES_JS))
					for o in json.loads(raw_obs) if raw_obs else []:
						obstacles.append((o["x"], o["y"], o["x"] + o["w"], o["y"] + o["h"]))
					raw = _value(
						page.evaluate(_RECTS_JS % json.dumps([a.selector for a in shot.annotations]))
					)
					rects = json.loads(raw) if raw else []

				png = page.capture_screenshot(image_format="png")
			finally:
				# Dispose the context explicitly. disposeOnDetach only fires when the
				# session detaches cleanly, and a run of 20 shots otherwise leaves
				# 20 Chromium contexts alive until the process exits.
				if page is not None:
					try:
						page.close()
					except Exception:
						pass
				if session is not None:
					if context:
						try:
							session.send(
								"Target.disposeBrowserContext",
								{"browserContextId": context["browserContextId"]},
							)
						except Exception:
							pass
					try:
						session.disconnect()
					except Exception:
						pass

			image = Image.open(io.BytesIO(png)).convert("RGB")
			if _is_blank(png, image):
				skipped.append((shot.stem, f"blank frame from {url}"))
				print(f"  BLANK     {shot.stem:<30} {url}")
				continue

			arrows = _draw_annotations(image, rects, shot.annotations, obstacles) if shot.annotations else 0
			buf = io.BytesIO()
			image.save(buf, "PNG", optimize=True)
			out = DOCS_IMAGES / f"{shot.stem}.png"
			out.write_bytes(buf.getvalue())

			done.append(shot.stem)
			missing = len(shot.annotations) - arrows
			note = f"{arrows} arrow(s)" if arrows else ""
			if missing:
				note += f", {missing} selector(s) not found"
			print(
				f"  captured  {shot.stem:<30} {shot.guide:<22} "
				f"{len(buf.getvalue()) // 1024:>4} KB  {swapped} swaps  {note}"
			)
		# one bad route must not lose the rest of the run
	except Exception as exc:
		skipped.append(("<run>", f"{type(exc).__name__}: {exc}"))
		raise
	finally:
		generator.remove_browser(browser_id)

	print(f"\n{len(done)} captured, {len(skipped)} skipped -> {DOCS_IMAGES}")
	for stem, why in skipped:
		print(f"  skipped {stem}: {why}")
