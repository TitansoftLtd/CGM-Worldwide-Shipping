"""Table columns in the wiki editor app size to their content.

Rules pinned here:

* Only the wiki app's HTML page is changed; every other response is left alone.
* The style is added once, however many times the hook runs.
* A failure never breaks the page being served.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import wiki_docs


def _response(html, mimetype="text/html"):
	response = MagicMock()
	response.mimetype = mimetype
	state = {"html": html}
	response.get_data.side_effect = lambda as_text=False: state["html"]
	response.set_data.side_effect = lambda value: state.__setitem__("html", value)
	response.html = lambda: state["html"]
	return response


def _request(path):
	return frappe._dict(path=path)


PAGE = "<html><head><title>Wiki</title></head><body></body></html>"


class TestWikiAppTableStyle(unittest.TestCase):
	def test_style_is_added_to_the_wiki_app_page(self):
		response = _response(PAGE)
		wiki_docs.add_table_style_to_wiki_app(response=response, request=_request("/wiki-app/spaces/x/page/y"))
		self.assertIn("table-layout: auto !important", response.html())
		self.assertTrue(response.html().index("<style") < response.html().index("</head>"))

	def test_added_once(self):
		response = _response(PAGE)
		for _ in range(3):
			wiki_docs.add_table_style_to_wiki_app(response=response, request=_request("/wiki-app"))
		self.assertEqual(response.html().count(wiki_docs.WIKI_APP_STYLE_MARK), 1)

	def test_other_pages_are_left_alone(self):
		for path in ("/desk/project", "/api/method/ping", "/cgm-shipping/processes/operations", "/"):
			response = _response(PAGE)
			wiki_docs.add_table_style_to_wiki_app(response=response, request=_request(path))
			response.set_data.assert_not_called()

	def test_non_html_responses_are_left_alone(self):
		response = _response('{"a": 1}', mimetype="application/json")
		wiki_docs.add_table_style_to_wiki_app(response=response, request=_request("/wiki-app/api"))
		response.set_data.assert_not_called()

	def test_a_failure_does_not_break_the_page(self):
		response = _response(PAGE)
		response.get_data.side_effect = RuntimeError("stream")
		with patch.object(frappe, "log_error"):
			wiki_docs.add_table_style_to_wiki_app(response=response, request=_request("/wiki-app"))
