"""Seed CGM Shipping documentation into a Frappe Wiki space from docs/ (idempotent)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe

WIKI_SPACE_ROUTE = "cgm-shipping"
WIKI_SPACE_NAME = "CGM Shipping"
WIKI_CONFIG_FILENAME = ".wiki.json"
LANDING_BASENAMES = ("readme.md", "index.md", "readme.mdx", "index.mdx")


def execute() -> None:
	if not frappe.db.exists("DocType", "Wiki Space"):
		return

	from wiki.wiki.git_sync import _sync_to_live

	docs_dir = Path(__file__).resolve().parents[2] / "docs"
	config_path = docs_dir / WIKI_CONFIG_FILENAME
	if not config_path.is_file():
		frappe.log_error(
			title="CGM Frappe Wiki",
			message=f"Wiki config not found: {config_path}",
		)
		return

	config = json.loads(config_path.read_text(encoding="utf-8"))
	sidebar = config.get("sidebar")
	if not sidebar:
		frappe.log_error(
			title="CGM Frappe Wiki",
			message=f"No sidebar in {config_path}",
		)
		return

	space = _get_or_create_space()
	nodes = _build_nodes_from_local_config(docs_dir, sidebar)
	_import_local_images(space, docs_dir, nodes)
	_sync_to_live(space, nodes, None, None)
	_ensure_space_published(space.name)
	frappe.db.commit()


def _get_or_create_space() -> frappe.Document:
	existing = frappe.db.get_value("Wiki Space", {"route": WIKI_SPACE_ROUTE}, "name")
	if existing:
		return frappe.get_doc("Wiki Space", existing)

	space = frappe.new_doc("Wiki Space")
	space.space_name = WIKI_SPACE_NAME
	space.route = WIKI_SPACE_ROUTE
	space.is_published = 1
	space.show_in_switcher = 1
	space.allow_contributions = 0
	space.insert(ignore_permissions=True)
	return space


def _ensure_space_published(space_name: str) -> None:
	frappe.db.set_value(
		"Wiki Space",
		space_name,
		{"is_published": 1, "show_in_switcher": 1},
		update_modified=False,
	)


def _import_local_images(space: frappe.Document, docs_dir: Path, nodes: list[dict[str, Any]]) -> None:
	"""Turn repo-relative image links in the docs into Frappe Files the wiki can serve.

	Frappe Wiki ships this for GitHub-backed spaces, but its importer fetches blobs
	by SHA from the GitHub API. This space syncs from the local `docs/` folder, so
	the same job is done here from disk: read the image, store it as a public File
	attached to the space, and rewrite the link in place before the content is
	hashed into a blob - otherwise `![](images/foo.png)` reaches the wiki as a
	relative path that resolves to nothing.

	Idempotent per (space, file contents): the File is named `cgmimg-<sha>.<ext>`,
	so an unchanged screenshot reuses the File already stored and the page content
	does not churn on every migrate.
	"""
	import hashlib
	import posixpath

	from wiki.wiki.git_sync import IMAGE_EXTENSIONS, MD_IMAGE_PATTERN, _is_repo_relative

	def import_one(path: Path) -> str | None:
		data = path.read_bytes()
		sha = hashlib.sha256(data).hexdigest()[:16]
		stem = f"cgmimg-{sha}"
		existing = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Wiki Space",
				"attached_to_name": space.name,
				"file_name": ["like", f"{stem}.%"],
			},
			fields=["file_url"],
			limit=1,
		)
		if existing:
			return existing[0].file_url
		return frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{stem}{path.suffix.lower()}",
				"attached_to_doctype": "Wiki Space",
				"attached_to_name": space.name,
				"is_private": 0,
				"content": data,
			}
		).insert(ignore_permissions=True).file_url

	for node in nodes:
		content = node.get("content")
		source_path = node.get("source_path")
		if not content or not source_path or node.get("is_group"):
			continue
		base_dir = posixpath.dirname(source_path)

		def repl(match, base_dir=base_dir):
			src = match.group(2).strip("<>").strip()
			if not _is_repo_relative(src) or not src.lower().endswith(IMAGE_EXTENSIONS):
				return match.group(0)
			resolved = posixpath.normpath(posixpath.join(base_dir, src))
			if resolved.startswith(".."):
				return match.group(0)
			image_path = docs_dir / resolved
			if not image_path.is_file():
				frappe.log_error(
					title="CGM Frappe Wiki",
					message=f"Image not found for {source_path}: {resolved}",
				)
				return match.group(0)
			url = import_one(image_path)
			return f"{match.group(1)}{url}{match.group(3) or ''}{match.group(4)}" if url else match.group(0)

		node["content"] = MD_IMAGE_PATTERN.sub(repl, content)


def _build_nodes_from_local_config(docs_dir: Path, sidebar: list[Any]) -> list[dict[str, Any]]:
	from wiki.wiki.git_sync import (
		_extract_title,
		_front_matter_slug,
		_front_matter_title,
		_humanize,
		_published_flag,
		strip_front_matter,
	)

	nodes: list[dict[str, Any]] = []
	landing_taken = [False]
	order = [0]

	def next_seg() -> str:
		seg = f"{order[0]:06d}"
		order[0] += 1
		return seg

	def read_markdown(rel_path: str) -> tuple[str, dict[str, Any]] | None:
		file_path = docs_dir / rel_path
		if not file_path.is_file():
			return None
		raw = file_path.read_text(encoding="utf-8")
		return strip_front_matter(raw)

	def add_leaf(path: str | None, parent_dir: str, label: str | None = None) -> None:
		if not path:
			return
		parsed = read_markdown(path)
		if not parsed:
			return
		body, meta = parsed
		base = path.split("/")[-1].rsplit(".", 1)[0]
		is_landing = (
			not landing_taken[0]
			and parent_dir == ""
			and path.split("/")[-1].lower() in LANDING_BASENAMES
		)
		if is_landing:
			landing_taken[0] = True
		nodes.append(
			{
				"is_group": 0,
				"dir": parent_dir,
				"parent_dir": parent_dir,
				"source_path": path,
				"landing_path": None,
				"landing": is_landing,
				"title": label or _front_matter_title(meta) or _extract_title(body) or _humanize(base),
				"slug": _front_matter_slug(meta) or base,
				"content": body,
				"is_published": _published_flag(meta),
				"order": None,
				"seg": next_seg(),
			}
		)

	def add_group(label: str, parent_dir: str) -> str:
		dir_key = f"{parent_dir}/{label}" if parent_dir else label
		nodes.append(
			{
				"is_group": 1,
				"dir": dir_key,
				"parent_dir": parent_dir,
				"source_path": f"{WIKI_CONFIG_FILENAME}#{dir_key}",
				"landing_path": None,
				"title": label,
				"slug": label,
				"content": "",
				"is_published": 1,
				"order": None,
				"seg": next_seg(),
			}
		)
		return dir_key

	def walk(entries: list[Any], parent_dir: str) -> None:
		if not isinstance(entries, list):
			return
		for entry in entries:
			if isinstance(entry, str):
				add_leaf(entry, parent_dir)
			elif isinstance(entry, dict):
				if isinstance(entry.get("items"), list):
					child_dir = add_group(entry["label"], parent_dir) if entry.get("label") else parent_dir
					walk(entry["items"], child_dir)
				elif entry.get("page") or entry.get("path"):
					add_leaf(entry.get("page") or entry.get("path"), parent_dir, label=entry.get("label"))
				elif len(entry) == 1:
					((key, value),) = entry.items()
					if isinstance(value, list):
						walk(value, add_group(key, parent_dir))
					elif isinstance(value, str):
						add_leaf(value, parent_dir, label=key)

	walk(sidebar, "")
	return nodes
