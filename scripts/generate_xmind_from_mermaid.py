#!/usr/bin/env python3
"""Generate XMind workbooks from Mermaid mindmap markdown files."""

from __future__ import annotations

import json
import re
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*(.*?)```", re.DOTALL)
ROOT_RE = re.compile(r'^root\(\((.*)\)\)$')
ROOT_QUOTED_RE = re.compile(r'^root\(\("(.*)"\)\)$')
QUOTED_RE = re.compile(r'^"(.*)"$')


@dataclass
class Node:
    title: str
    children: list["Node"] = field(default_factory=list)


def extract_mermaid_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = MERMAID_BLOCK_RE.search(text)
    if not match:
        raise ValueError(f"No Mermaid block found in {path}")
    body = match.group(1).strip("\n")
    lines = [line.rstrip() for line in body.splitlines() if line.strip()]
    if not lines or lines[0].strip() != "mindmap":
        raise ValueError(f"Unsupported Mermaid mindmap format in {path}")
    return lines[1:]


def clean_label(raw: str) -> str:
    raw = raw.strip()
    for pattern in (ROOT_QUOTED_RE, ROOT_RE):
        root_match = pattern.match(raw)
        if root_match:
            return root_match.group(1)
    quoted_match = QUOTED_RE.match(raw)
    if quoted_match:
        return quoted_match.group(1)
    return raw


def parse_mermaid_tree(path: Path) -> Node:
    lines = extract_mermaid_lines(path)
    root_line = lines[0]
    root_title = clean_label(root_line.strip())
    if root_title == root_line.strip():
        raise ValueError(f"Root node not found in {path}")

    root = Node(root_title)
    root_indent = len(root_line) - len(root_line.lstrip(" "))
    stack: list[tuple[int, Node]] = [(0, root)]

    for line in lines[1:]:
        indent = len(line) - len(line.lstrip(" "))
        depth = (indent - root_indent) // 2 + 1
        title = clean_label(line.strip())
        node = Node(title)

        while stack and stack[-1][0] >= depth:
            stack.pop()
        if not stack:
            raise ValueError(f"Broken indentation tree in {path}: {line}")
        stack[-1][1].children.append(node)
        stack.append((depth, node))

    return root


def stable_id(*parts: str) -> str:
    seed = "::".join(parts)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def topic_dict(
    node: Node,
    *,
    source_key: str,
    lineage: list[str],
    structure_root: bool = False,
) -> dict:
    topic = {
        "id": stable_id(source_key, *lineage),
        "class": "topic",
        "title": node.title,
    }
    if structure_root:
        topic["structureClass"] = "org.xmind.ui.logic.right"
    if node.children:
        topic["children"] = {
            "attached": [
                topic_dict(
                    child,
                    source_key=source_key,
                    lineage=[*lineage, str(index), child.title],
                )
                for index, child in enumerate(node.children, start=1)
            ]
        }
    return topic


def workbook_dict(root: Node, *, source_key: str) -> tuple[list[dict], dict]:
    sheet_id = stable_id(source_key, "sheet")
    root_topic = topic_dict(
        root,
        source_key=source_key,
        lineage=["root", root.title],
        structure_root=True,
    )
    workbook = [
        {
            "id": sheet_id,
            "class": "sheet",
            "title": root.title,
            "rootTopic": root_topic,
        }
    ]
    metadata = {
        "creator": {"name": "Codex", "version": "1.0"},
        "modifier": {"name": "Codex", "version": "1.0"},
        "title": root.title,
        "activeSheetId": sheet_id,
    }
    return workbook, metadata


def write_xmind(src: Path) -> Path:
    root = parse_mermaid_tree(src)
    workbook, metadata = workbook_dict(root, source_key=src.stem)
    manifest = {
        "file-entries": {
            "content.json": {},
            "metadata.json": {},
        }
    }
    target = src.with_suffix(".xmind")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "content.json",
            json.dumps(workbook, ensure_ascii=False, indent=2),
        )
        zf.writestr(
            "metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2),
        )
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    return target


def main() -> int:
    base = Path("mindmaps")
    files = sorted(p for p in base.glob("*.md") if p.is_file())
    if not files:
        print("No markdown mindmaps found.", file=sys.stderr)
        return 1

    generated = []
    for path in files:
        target = write_xmind(path)
        generated.append(target)

    print("\n".join(str(path) for path in generated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
