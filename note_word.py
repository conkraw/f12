"""Insert reviewed note content into the original Word templates.

The uploaded DOCX files are preserved as package assets. The builder inserts
medication and Plan paragraphs and clears medication-cell placeholders.
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

from note_fengi import FENGI_TEMPLATE_FILES
from note_neuro import NEURO_TEMPLATE_FILES
from note_respiratory import RESP_TEMPLATE_FILES
from note_cardiovascular import CV_TEMPLATE_FILES


TEMPLATE_FILES = {
    "progress": Path(__file__).resolve().parent / "templates" / "picu_progress_note.docx",
    "attestation": Path(__file__).resolve().parent / "templates" / "attending_attestation.docx",
}
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_FENGI_HEADING = "FLUIDS ELECTROLYTES NUTRITION/GASTROINTESTINAL"
_NEURO_HEADING = "NEUROLOGY"
_RESPIRATORY_HEADING = "RESPIRATORY"
_CARDIOVASCULAR_HEADING = "CARDIOVASCULAR"
_TABLE_HEADING_TEXT = re.compile(r"[A-Z][A-Z0-9 /(),&-]*")
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
    attributes: dict[str, str] = field(default_factory=dict)
    namespaces: dict[str | None, str] = field(default_factory=dict)


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
    namespaces = {}

    def namespace(prefix, uri):
        namespaces[prefix] = uri

    def start(name, attributes):
        position = parser.CurrentByteIndex
        node = _Node(name, position, _tag_end(source, position), attributes=dict(attributes))
        if stack:
            stack[-1].children.append(node)
        else:
            node.namespaces = dict(namespaces)
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
    parser.StartNamespaceDeclHandler = namespace
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


def _walk(root: _Node):
    yield root
    for child in root.children:
        yield from _walk(child)


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


def _medication_rows(table: _Node) -> tuple[_Node, _Node]:
    rows = [node for node in table.children if node.name == _W + "tr"]
    headings = [index for index, row in enumerate(rows) if _text(row).strip() == "MEDICATIONS"]
    if len(headings) != 1 or headings[0] + 1 >= len(rows):
        raise NoteWordError("The Word template is missing a unique required medication cell.")
    return rows[headings[0]], rows[headings[0] + 1]


def _medication_placeholder(table: _Node) -> _Node:
    """Find the medication row without selecting a urine-output placeholder."""
    return _paragraph(_medication_rows(table)[1], "***")


def _fingerprint(node: _Node):
    return (node.name, tuple(sorted(node.attributes.items())), tuple(node.text),
            tuple(_fingerprint(child) for child in node.children))


def _default_styles(source: bytes):
    root = _parse_xml(source)
    defaults = tuple(_fingerprint(node) for node in _nodes(root, "docDefaults"))
    styles = sorted((node.attributes.get(_W + "styleId", ""), _fingerprint(node))
                    for node in _nodes(root, "style")
                    if node.attributes.get(_W + "default") in {"1", "true", "on"})
    return defaults, tuple(styles)


def _load_section_source(variant: str, progress: ZipFile, *, template_files: dict,
                         heading: str, description: str) -> bytes:
    """Load a vetted source table without adding or rewriting Word resources.

    The supplied tables use direct formatting and matching default styles,
    fonts and theme. Their Epic links are literal text, with no relationship
    targets. Reject a future incompatible asset instead of silently losing its
    formatting, links or embedded resources during an XML-only transplant.
    """
    if not isinstance(variant, str) or variant not in template_files:
        raise NoteWordError(f"The selected {description} Word template is invalid.")
    try:
        with ZipFile(BytesIO(template_files[variant].read_bytes())) as original:
            source = original.read("word/document.xml")
            root = _parse_xml(source)
            table = _table(root, heading)
            progress_root = _parse_xml(progress.read("word/document.xml"))
            if not root.namespaces.items() <= progress_root.namespaces.items():
                raise NoteWordError(f"The {description} Word template has incompatible XML namespaces.")
            for node in _walk(table):
                if (any(key.startswith(_R) for key in node.attributes)
                        or node.name in {_W + name for name in ("pStyle", "rStyle", "tblStyle", "numPr", "sectPr")}):
                    raise NoteWordError(f"The {description} Word template requires unsupported Word resources.")
            if (_default_styles(original.read("word/styles.xml")) != _default_styles(progress.read("word/styles.xml"))
                    or any(original.read(part) != progress.read(part)
                           for part in ("word/fontTable.xml", "word/theme/theme1.xml"))):
                raise NoteWordError(f"The {description} Word template has incompatible formatting resources.")
            return source
    except (OSError, BadZipFile, KeyError):
        raise NoteWordError(f"The {description} Word template is missing or invalid. Restore the packaged templates folder.") from None


def _load_fengi_source(variant: str, progress: ZipFile) -> bytes:
    return _load_section_source(variant, progress, template_files=FENGI_TEMPLATE_FILES,
                                heading=_FENGI_HEADING, description="age-specific FEN/GI")


def _load_neuro_source(variant: str, progress: ZipFile) -> bytes:
    return _load_section_source(variant, progress, template_files=NEURO_TEMPLATE_FILES,
                                heading=_NEURO_HEADING, description="neurologic")


def _load_respiratory_source(variant: str, progress: ZipFile) -> bytes:
    return _load_section_source(variant, progress, template_files=RESP_TEMPLATE_FILES,
                                heading=_RESPIRATORY_HEADING, description="respiratory")


def _add_pacemaker_rows(source: bytes, pacemaker_source: bytes) -> bytes:
    """Copy the two supplied pacemaker rows into the compatible ECLS table."""
    table = _table(_parse_xml(source), _CARDIOVASCULAR_HEADING)
    pacemaker_table = _table(_parse_xml(pacemaker_source), _CARDIOVASCULAR_HEADING)
    grid = next((node for node in table.children if node.name == _W + "tblGrid"), None)
    pacemaker_grid = next((node for node in pacemaker_table.children if node.name == _W + "tblGrid"), None)
    if grid is None or pacemaker_grid is None or _fingerprint(grid) != _fingerprint(pacemaker_grid):
        raise NoteWordError("The cardiovascular pacemaker rows have an incompatible table grid.")
    rows = [node for node in table.children if node.name == _W + "tr"]
    if any(_text(node).strip() == "PACEMAKER" for node in rows):
        raise NoteWordError("The cardiovascular Word template already contains pacemaker rows.")
    pacemaker_rows = [node for node in pacemaker_table.children if node.name == _W + "tr"]
    headings = [index for index, node in enumerate(pacemaker_rows) if _text(node).strip() == "PACEMAKER"]
    if (len(headings) != 1 or headings[0] + 1 >= len(pacemaker_rows)
            or _text(pacemaker_rows[headings[0] + 1]).strip() != "{ACKCVPACEMAKER:45347}"):
        raise NoteWordError("The cardiovascular Word template is missing unique required pacemaker rows.")
    first, last = pacemaker_rows[headings[0]], pacemaker_rows[headings[0] + 1]
    content = pacemaker_source[first.start:last.end]
    medication_heading, _ = _medication_rows(table)
    return _apply_edits(source, [(medication_heading.start, medication_heading.start, content)])


def _load_cardiovascular_source(variant: str, progress: ZipFile, *, include_pacemaker: bool = False) -> bytes:
    source = _load_section_source(variant, progress, template_files=CV_TEMPLATE_FILES,
                                  heading=_CARDIOVASCULAR_HEADING, description="cardiovascular")
    if variant == "art_cvl_ecls" and include_pacemaker is True:
        pacemaker_source = _load_section_source("art_cvl_pacemaker", progress, template_files=CV_TEMPLATE_FILES,
                                                heading=_CARDIOVASCULAR_HEADING, description="cardiovascular")
        source = _add_pacemaker_rows(source, pacemaker_source)
    return source


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


def _new_paragraph(text: str, formatting: tuple[bytes, bytes], *, heading: bool = False,
                   keep_next: bool | None = None) -> bytes:
    paragraph_properties, run_properties = formatting
    keep_next = heading if keep_next is None else keep_next
    pagination = b'<w:keepNext w:val="1"/>' if keep_next else b'<w:keepNext w:val="0"/>'
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


def _keep_with_next_edits(paragraph: _Node, source: bytes) -> list[tuple[int, int, bytes]]:
    """Change only one paragraph's nonvisual keep-with-next property."""
    properties = next((node for node in paragraph.children if node.name == _W + "pPr"), None)
    keep_next = b"<w:keepNext/>"
    if properties is None:
        return [(paragraph.open_end, paragraph.open_end, b"<w:pPr>" + keep_next + b"</w:pPr>")]
    existing = [node for node in properties.children if node.name == _W + "keepNext"]
    if existing:
        return [(node.start, node.end, keep_next) for node in existing]
    if properties.end == properties.open_end:
        content = source[properties.start:properties.open_end - 2] + b">" + keep_next + b"</w:pPr>"
        return [(properties.start, properties.end, content)]
    return [(properties.open_end, properties.open_end, keep_next)]


def _plan_heading_edits(plan: _Node, source: bytes) -> list[tuple[int, int, bytes]]:
    """Keep the existing Plan heading with its first generated plan item."""
    return _keep_with_next_edits(_paragraph(plan, "PLAN"), source)


def _table_heading_edits(table: _Node, source: bytes) -> list[tuple[int, int, bytes]]:
    """Keep plain section labels with the next row without changing appearance."""
    rows = [node for node in table.children if node.name == _W + "tr"]
    edits = []
    for row in rows[:-1]:
        cells = [node for node in row.children if node.name == _W + "tc"]
        if len(cells) != 1:
            continue
        paragraphs = [node for node in _nodes(cells[0], "p") if _text(node).strip()]
        if len(paragraphs) != 1 or not _TABLE_HEADING_TEXT.fullmatch(_text(paragraphs[0]).strip()):
            continue
        edits.extend(_keep_with_next_edits(paragraphs[0], source))
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


def _medication_paragraphs(groups: dict, formatting: tuple[bytes, bytes], *, table_cell: bool = False) -> bytes:
    if not any(groups.get(group) for group in _GROUPS):
        return b""
    pieces = []
    for group in _GROUPS:
        values = groups.get(group) or []
        if not values:
            continue
        if table_cell:
            # An inline label cannot be stranded when its table row splits.
            # Keep only the generated label bold, and avoid paragraph keep
            # chains that can push an oversized medication row to a new page.
            first = _new_paragraph(group + ": ", formatting, heading=True, keep_next=False)
            first = first[:-len(b"</w:p>")] + _new_run(values[0], formatting[1]) + b"</w:p>"
            pieces.append(first)
            pieces.extend(_new_paragraph(value, formatting) for value in values[1:])
        else:
            pieces.append(_new_paragraph(group + ":", formatting, heading=True))
            pieces.extend(_new_paragraph(value, formatting) for value in values)
    return b"".join(pieces)


def _medication_edits(anchor: _Node, content: bytes) -> list[tuple[int, int, bytes]]:
    if content:
        return [(anchor.start, anchor.end, content)]
    # Retain the original styled paragraph in an empty Word cell. Text can be
    # split over several runs, so clear each text range inside this placeholder.
    return [(node.open_end, node.close_start, b"") for node in _nodes(anchor, "t")
            if node.close_start > node.open_end]


def _apply_edits(source: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    pieces = []
    previous = 0
    for start, end, content in sorted(edits, key=lambda value: (value[0], value[1])):
        if start < previous:
            raise NoteWordError("The Word template has overlapping insertion locations.")
        pieces.extend((source[previous:start], content))
        previous = end
    pieces.append(source[previous:])
    return b"".join(pieces)


def _cleared_paragraph(source: bytes, paragraph: _Node) -> bytes:
    edits = [(start - paragraph.start, end - paragraph.start, value)
             for start, end, value in _medication_edits(paragraph, b"")]
    return _apply_edits(source[paragraph.start:paragraph.end], edits)


def _section_content(source: bytes, groups: dict, formatting: tuple[bytes, bytes], *,
                     heading: str, description: str) -> bytes:
    root = _parse_xml(source)
    table = _table(root, heading)
    anchor = _medication_placeholder(table)
    content = _medication_paragraphs(groups, formatting, table_cell=True)
    source_edits = _medication_edits(anchor, content) + _table_heading_edits(table, source)
    edits = [(start - table.start, end - table.start, value)
             for start, end, value in source_edits]
    table_content = _apply_edits(source[table.start:table.end], edits)
    # Copy the supplied empty separator too. It prevents adjacent source tables
    # from merging when Word opens the resulting document.
    body = next(_nodes(root, "body"), None)
    if body is None or table not in body.children:
        raise NoteWordError(f"The {description} Word template has an invalid table location.")
    following = body.children[body.children.index(table) + 1:]
    if (following and following[0].name == _W + "p"
            and all(child.name == _W + "pPr" for child in following[0].children)
            and not any(_nodes(following[0], "sectPr"))):
        separator = source[following[0].start:following[0].end]
    else:
        separator = _new_paragraph("", formatting)
    return table_content + separator


def _fengi_content(source: bytes, groups: dict, formatting: tuple[bytes, bytes]) -> bytes:
    return _section_content(source, groups, formatting, heading=_FENGI_HEADING,
                            description="age-specific FEN/GI")


def _neuro_content(source: bytes, groups: dict, formatting: tuple[bytes, bytes]) -> bytes:
    return _section_content(source, groups, formatting, heading=_NEURO_HEADING,
                            description="neurologic")


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


def _insert_content(source: bytes, result: dict, note_type: str, fengi_source: bytes | None = None,
                    neuro_source: bytes | None = None, respiratory_source: bytes | None = None,
                    cardiovascular_source: bytes | None = None) -> bytes:
    root = _parse_xml(source)
    formatting = _body_format(root, source)
    edits = []
    if note_type == "progress":
        sections = _sections(result)
        for section, token in _SYSTEM_ANCHORS:
            anchor = _paragraph(root, token)
            if section == "Neurologic" and neuro_source is not None:
                # The original anchor separates the Objective heading table
                # from this section. Preserve its now-empty paragraph so Word
                # cannot merge those two independently formatted tables.
                content = _cleared_paragraph(source, anchor)
                content += _neuro_content(neuro_source, sections.get(section, {}), formatting)
                edits.append((anchor.start, anchor.end, content))
                continue
            if section == "Respiratory" and respiratory_source is not None:
                content = _section_content(respiratory_source, sections.get(section, {}), formatting,
                                           heading=_RESPIRATORY_HEADING, description="respiratory")
                edits.append((anchor.start, anchor.end, content))
                continue
            if section == "Cardiovascular" and cardiovascular_source is not None:
                content = _section_content(cardiovascular_source, sections.get(section, {}), formatting,
                                           heading=_CARDIOVASCULAR_HEADING, description="cardiovascular")
                edits.append((anchor.start, anchor.end, content))
                continue
            if section == "FEN / GI" and fengi_source is not None:
                content = _fengi_content(fengi_source, sections.get(section, {}), formatting)
                edits.append((anchor.start, anchor.end, content))
                continue
            content = _medication_paragraphs(sections.get(section, {}), formatting)
            if content:
                edits.append((anchor.end, anchor.end, content))
        for section, title in (("Hematology", "HEMATOLOGY"), ("Infectious Disease", "INFECTIOUS DISEASES")):
            table = _table(root, title)
            anchor = _medication_placeholder(table)
            content = _medication_paragraphs(sections.get(section, {}), formatting, table_cell=True)
            edits.extend(_medication_edits(anchor, content))
            edits.extend(_table_heading_edits(table, source))
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
        if note_type == "progress" and any(value is not None for value in (neuro_source, respiratory_source, cardiovascular_source)):
            edits.extend(_plan_heading_edits(plan, source))
        edits.extend(_plan_edits(root, source, plan, tokens, formatting))
    if not edits:
        return source
    return _apply_edits(source, edits)


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
            fengi_source = None
            neuro_source = None
            respiratory_source = None
            cardiovascular_source = None
            if note_type == "progress" and result.get("fengi_variant") is not None:
                fengi_source = _load_fengi_source(result["fengi_variant"], original)
            if note_type == "progress" and result.get("neuro_variant") is not None:
                neuro_source = _load_neuro_source(result["neuro_variant"], original)
            if note_type == "progress" and result.get("respiratory_variant") is not None:
                respiratory_source = _load_respiratory_source(result["respiratory_variant"], original)
            if note_type == "progress" and result.get("cardiovascular_variant") is not None:
                cardiovascular_source = _load_cardiovascular_source(
                    result["cardiovascular_variant"], original,
                    include_pacemaker=result.get("cardiovascular_include_pacemaker", False))
            modified = _insert_content(source, result, note_type, fengi_source, neuro_source,
                                       respiratory_source, cardiovascular_source)
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
