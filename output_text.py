"""Display-only medication cleanup. Never applied to stored records or mapping keys."""
import re


def medication_output(text: str) -> str:
    # Exact qualifier only. Keep weight-based units, held/start annotations,
    # order-specific qualifiers, doses and all source data in the editor.
    if not re.search(r'\([ \t]*dosing[ \t]+weight[ \t]*\)', text, flags=re.I):
        return text
    value = re.sub(r'\([ \t]*dosing[ \t]+weight[ \t]*\)', '', text, flags=re.I)
    return '\n'.join(re.sub(r'[ \t]{2,}', ' ', line).rstrip() for line in value.split('\n')).strip()
