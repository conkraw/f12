"""Display-only medication cleanup. Never applied to stored records or mapping keys."""
import re


_NAME_CONTEXT = re.compile(
    r"^(?:(?P<hide>(?:and|or|alternative\s+order)\s*:|"
    r"\[START\s+ON\s+[^\s\]\r\n][^\]\r\n]*\])|"
    r"(?P<keep>\[(?:held\s+by\s+provider|discontinued)\]|"
    r"followed\s+by(?:\s*:|\b)))\s*", re.I)


def medication_name_output(name: str) -> str:
    """Hide only requested leading labels, without changing the source name.

    Known status and Followed by wrappers remain visible while allowing a
    following connector or START ON label to be hidden. An unknown wrapper
    ends that prefix chain. Do not use this presentation value for matching,
    schedule checks, rate selection, or stored records.
    """
    original = name.strip()
    remainder, kept, changed = original, [], False
    while remainder:
        match = _NAME_CONTEXT.match(remainder)
        if match is None:
            break
        if match.group("keep"):
            kept.append(match.group("keep"))
        else:
            changed = True
        remainder = remainder[match.end():].lstrip()
    # A label-only source must never turn into a blank medication entry.
    if not changed or not remainder:
        return original
    return " ".join(kept + [remainder])


def medication_output(text: str) -> str:
    # Exact qualifier only. Keep weight-based units, held/start annotations,
    # order-specific qualifiers, doses and all source data in the editor.
    if not re.search(r'\([ \t]*dosing[ \t]+weight[ \t]*\)', text, flags=re.I):
        return text
    value = re.sub(r'\([ \t]*dosing[ \t]+weight[ \t]*\)', '', text, flags=re.I)
    return '\n'.join(re.sub(r'[ \t]{2,}', ' ', line).rstrip() for line in value.split('\n')).strip()
