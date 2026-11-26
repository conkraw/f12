"""Insert reviewed note content into the original Word templates.

The uploaded DOCX files are preserved as package assets. The builder inserts
medication and Plan paragraphs and removes the two medication-cell placeholders.
Other visible template content and package parts stay unchanged. SmartLink runs,
colors, table styling, sections and page geometry retain their original format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from io import BytesIO
from pathlib import Path
import re
from xml.parsers import expat
from zipfile import BadZipFile, ZipFile


TEMPLATE_FILES = {
    "progress": Path(__file__).resolve().parent / "templates" / "picu_progress_note.docx",
    "attestation": Path(__file__).resolve().parent / "templates" / "attending_attestation.docx",
}
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_GROUPS = ("Drips", "Scheduled", "PRN")
_SYSTEM_ANCHORS = (
    ("Neurologic", "{CKNEUROSMARTLIST:45213}"),
    ("Respiratory", "{CKRESPLIST:45220}"),
    ("Cardiovascular", "{CKCVLIST:45328}"),
    ("FEN / GI", "{ACKFENGI:45365}"),
)
_ALIASES = {"Neurology": "Neurologic", "FEN/GI": "FEN / GI", "Infectious Diseases": "Infectious Disease"}


class NoteWordError(ValueError):
    """A static, patient-free error suitable for the note utility UI."""


@dataclass
class _Node:
    name: str
    start: int
    open_end: int
    end: int = 0
    close_start: int = 0
    children: list["_Node"] = field(default_factory=list)
    text: list[str] = field(default_factory=list)


def _tag_end(source: bytes, start: int) -> int:
    """Find the end of one XML tag while respecting quoted attribute values."""
    quote = None
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if char == quote:
                quote = None
        elif char in (34, 39):
            quote = char
        elif char == 62:
            return index + 1
    raise NoteWordError("The Word template contains incomplete XML.")


def _parse_xml(source: bytes) -> _Node:
    """Read logical XML nodes and their byte ranges without reserializing them."""
    if b"<!DOCTYPE" in source.upper() or b"<!ENTITY" in source.upper():
        raise NoteWordError("The Word template contains unsupported XML declarations.")
    parser = expat.ParserCreate(namespace_separator="}")
    roots = []
    stack = []

    def start(name, attributes):
        position = parser.CurrentByteIndex
        node = _Node(name, position, _tag_end(source, position))
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    def end(name):
        node = stack.pop()
        if source[node.start:node.open_end].rstrip().endswith(b"/>"):
            node.end = node.open_end
            node.close_start = node.open_end
        else:
            node.close_start = parser.CurrentByteIndex
            node.end = _tag_end(source, parser.CurrentByteIndex)

    def text(value):
        if stack:
            stack[-1].text.append(value)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    try:
        parser.Parse(source, True)
    except expat.ExpatError:
        raise NoteWordError("The Word template contains invalid XML.") from None
    if len(roots) != 1:
        raise NoteWordError("The Word template has an invalid document structure.")
    return roots[0]


def _nodes(root: _Node, name: str):
    if root.name == _W + name:
        yield root
    for child in root.children:
        yield from _nodes(child, name)


def _text(root: _Node) -> str:
    return "".join("".join(node.text) for node in _nodes(root, "t"))


def _paragraph(root: _Node, text: str) -> _Node:
    found = [node for node in _nodes(root, "p") if _text(node).strip() == text]
    if len(found) != 1:
        raise NoteWordError("The Word template is missing a unique required note placeholder.")
    return found[0]


def _table(root: _Node, heading: str) -> _Node:
    found = []
    for node in _nodes(root, "tbl"):
        first = next(_nodes(node, "p"), None)
        if first is not None and _text(first).strip() == heading:
            found.append(node)
    if len(found) != 1:
        raise NoteWordError("The Word template is missing a unique required section table.")
    return found[0]


def _body_format(root: _Node, source: bytes) -> tuple[bytes, bytes]:
    """Reuse the template's ordinary body paragraph and run formatting."""
    paragraphs = [node for node in _nodes(root, "p") if _text(node).startswith("The patient is a ")]
    if len(paragraphs) != 1:
        raise NoteWordError("The Word template is missing its assessment paragraph.")
    reference = paragraphs[0]
    paragraph_properties = b""
    run_properties = b""
    for child in reference.children:
        if child.name == _W + "pPr":
            # The additions must be allowed to flow across pages. Copy the
            # original body format without its section or pagination controls.
            paragraph_properties = b"".join(
                source[item.start:item.end] for item in child.children
                if item.name not in {_W + name for name in ("keepNext", "keepLines", "pageBreakBefore", "sectPr")}
            )
        elif child.name == _W + "r" and not run_properties:
            run_properties = b"".join(
                source[item.start:item.end] for item in child.children if item.name == _W + "rPr"
            )
    return paragraph_properties, run_properties


def _safe_text(text: str) -> str:
    if not isinstance(text, str):
        raise NoteWordError("A generated note line has an invalid text value.")
    if any(not (char in "\t\n\r" or 32 <= ord(char) <= 0xD7FF or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF) for char in text):
        raise NoteWordError("A generated note line contains an unsupported character.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _new_run(text: str, run_properties: bytes, *, heading: bool = False) -> bytes:
    # Assessment paragraphs in the supplied files use ordinary body text.
    # Bold only new labels. Do not alter any existing template runs.
    if heading:
        if run_properties:
            run_properties = run_properties.replace(b"</w:rPr>", b"<w:b/><w:bCs/></w:rPr>")
        else:
            run_properties = b"<w:rPr><w:b/><w:bCs/></w:rPr>"
    text_xml = []
    for part in re.split(r"(\n|\t)", _safe_text(text)):
        if part == "\n":
            text_xml.append("<w:br/>")
        elif part == "\t":
            text_xml.append("<w:tab/>")
        elif part:
            text_xml.append('<w:t xml:space="preserve">' + escape(part, quote=False) + "</w:t>")
    return b"<w:r>" + run_properties + "".join(text_xml).encode("utf-8") + b"</w:r>"


def _new_paragraph(text: str, formatting: tuple[bytes, bytes], *, heading: bool = False) -> bytes:
    paragraph_properties, run_properties = formatting
    pagination = b'<w:keepNext w:val="1"/>' if heading else b'<w:keepNext w:val="0"/>'
    return (b"<w:p><w:pPr>" + pagination + b'<w:keepLines w:val="0"/>' + paragraph_properties
            + b"</w:pPr>" + _new_run(text, run_properties, heading=heading) + b"</w:p>")


def _empty_plan_placeholders(root: _Node, plan: _Node) -> list[_Node]:
    body = next(_nodes(root, "body"), None)
    if body is None or plan not in body.children:
        return []
    placeholders = []
    for node in body.children[body.children.index(plan) + 1:]:
        # A paragraph with a bookmark, run, field, break or section setting
        # is not an empty placeholder, even if it has no visible text.
        if (node.name != _W + "p"
                or any(child.name != _W + "pPr" for child in node.children)
                or any(_nodes(node, "sectPr"))
                or any(_nodes(node, "pageBreakBefore"))):
            break
        placeholders.append(node)
    return placeholders


def _plan_edits(root: _Node, source: bytes, plan: _Node, tokens: list[str], formatting: tuple[bytes, bytes]) -> list[tuple[int, int, bytes]]:
    """Reuse empty Plan paragraphs so they do not spill onto a blank page."""
    edits = []
    placeholders = _empty_plan_placeholders(root, plan)
    for index, node in enumerate(placeholders):
        content = b""
        if index < len(tokens):
            run = _new_run(tokens[index], formatting[1])
            if node.end == node.open_end:
                content = source[node.start:node.open_end - 2] + b">" + run + b"</w:p>"
            else:
                content = source[node.start:node.close_start] + run + source[node.close_start:node.end]
        # Any unused trailing Plan placeholder is genuinely empty. Remove it
        # only when selected plan tokens are being inserted.
        edits.append((node.start, node.end, content))
    remaining = tokens[len(placeholders):]
    if remaining:
        offset = placeholders[-1].end if placeholders else plan.end
        content = b"".join(_new_paragraph(token, formatting) for token in remaining)
        edits.append((offset, offset, content))
    return edits


def _sections(result: dict) -> dict:
    payload = result.get("medications") or {}
    raw = payload.get("sections") or {}
    if not isinstance(raw, dict):
        raise NoteWordError("The generated medication sections are invalid.")
    sections = {}
    for original, groups in raw.items():
        if not isinstance(original, str) or not isinstance(groups, dict):
            raise NoteWordError("A generated medication section is invalid.")
        name = _ALIASES.get(original, original)
        target = sections.setdefault(name, {group: [] for group in _GROUPS})
        for group in _GROUPS:
            values = groups.get(group) or []
            if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) for value in values):
                raise NoteWordError("A generated medication group is invalid.")
            target[group].extend(value for value in values if value.strip())
    return sections


def _medication_paragraphs(groups: dict, formatting: tuple[bytes, bytes]) -> bytes:
    if not any(groups.get(group) for group in _GROUPS):
        return b""
    pieces = []
    for group in _GROUPS:
        values = groups.get(group) or []
        if not values:
            continue
        pieces.append(_new_paragraph(group + ":", formatting, heading=True))
        pieces.extend(_new_paragraph(value, formatting) for value in values)
    return b"".join(pieces)


def _plan_tokens(result: dict) -> list[str]:
    supplied = result.get("selected_plan_tokens")
    if supplied is None:
        style = result.get("phrase_style", "at")
        if style not in ("at", "dot"):
            raise NoteWordError("The generated note phrase format is invalid.")
        supplied = []
        for row in result.get("suggestions") or []:
            if row.get("selected") and row.get("phrase"):
                phrase = row["phrase"]
                supplied.append("@" + phrase + "@" if style == "at" else "." + phrase)
    if not isinstance(supplied, (list, tuple)):
        raise NoteWordError("The selected note plan phrases are invalid.")
    tokens = []
    for token in supplied:
        if not isinstance(token, str) or not re.fullmatch(r"(?:@[A-Z][A-Z0-9_]{0,119}@|\.[A-Z][A-Z0-9_]{0,119})", token):
            raise NoteWordError("A selected plan item is not a valid Epic phrase token.")
        if token not in tokens:
            tokens.append(token)
    return tokens


def _insert_content(source: bytes, result: dict, note_type: str) -> bytes:
    root = _parse_xml(source)
    formatting = _body_format(root, source)
    edits = []
    if note_type == "progress":
        sections = _sections(result)
        for section, token in _SYSTEM_ANCHORS:
            anchor = _paragraph(root, token)
            content = _medication_paragraphs(sections.get(section, {}), formatting)
            if content:
                edits.append((anchor.end, anchor.end, content))
        for section, title in (("Hematology", "HEMATOLOGY"), ("Infectious Disease", "INFECTIOUS DISEASES")):
            table = _table(root, title)
            anchor = _paragraph(table, "***")
            content = _medication_paragraphs(sections.get(section, {}), formatting)
            if content:
                # Replace only this medication placeholder with the flat groups,
                # keeping the table cell and its properties in their exact place.
                edits.append((anchor.start, anchor.end, content))
            else:
                # An empty Word cell still needs its paragraph. Clear only the
                # placeholder text, including when Word split it across runs.
                for node in _nodes(anchor, "t"):
                    if node.close_start > node.open_end:
                        edits.append((node.open_end, node.close_start, b""))
        standard = {name for name, _ in _SYSTEM_ANCHORS} | {"Hematology", "Infectious Disease"}
        extra = []
        for section, groups in sections.items():
            if section not in standard and any(groups.values()):
                extra.append(_new_paragraph(section, formatting, heading=True))
                extra.append(_medication_paragraphs(groups, formatting))
        if extra:
            content = _new_paragraph("ADDITIONAL MEDICATIONS", formatting, heading=True) + b"".join(extra)
            offset = _table(root, "ASSESSMENT").start
            edits.append((offset, offset, content))
    # Attestation intentionally never reads the medication payload. The source
    # attestation statement and every exam SmartList remain exactly as supplied.
    plan = _table(root, "PLAN")
    tokens = _plan_tokens(result)
    if tokens:
        edits.extend(_plan_edits(root, source, plan, tokens, formatting))
    if not edits:
        return source
    pieces = []
    previous = 0
    for start, end, content in sorted(edits, key=lambda value: (value[0], value[1])):
        if start < previous:
            raise NoteWordError("The Word template has overlapping insertion locations.")
        pieces.extend((source[previous:start], content))
        previous = end
    pieces.append(source[previous:])
    return b"".join(pieces)


def render_note_docx(result: dict, *, note_type: str = "progress") -> bytes:
    """Return a Word draft using the original progress or attestation template.

    The structured medication lists and selected Plan tokens are inserted into
    the original template. Plain-text preview edits are not used to reconstruct
    formatting or alter existing template wording.
    """
    if note_type not in TEMPLATE_FILES:
        raise NoteWordError("Choose a progress note or attending attestation.")
    if not isinstance(result, dict):
        raise NoteWordError("Generate a note before downloading its Word document.")
    try:
        template = TEMPLATE_FILES[note_type].read_bytes()
    except OSError:
        raise NoteWordError("The Word note template is missing or unavailable. Restore the packaged templates folder.") from None
    try:
        with ZipFile(BytesIO(template)) as original:
            source = original.read("word/document.xml")
            modified = _insert_content(source, result, note_type)
            if modified == source:
                return template
            output = BytesIO()
            with ZipFile(output, "w") as updated:
                updated.comment = original.comment
                for info in original.infolist():
                    payload = modified if info.filename == "word/document.xml" else original.read(info.filename)
                    updated.writestr(info, payload)
            return output.getvalue()
    except (BadZipFile, KeyError):
        raise NoteWordError("The packaged Word note template is invalid or incomplete.") from None
