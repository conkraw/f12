"""Shared checks for the intentionally new per-section recovery contract."""
from models import validate_sheet
FIELDS = {'b': ['medications'], 'cd': ['ventilation', 'noninvasive'],
 'e': ['vitals'], 'f': ['cultures'], 'g': ['labs'],
 'i': ['nutrition', 'dosing_weight'], 'n': ['admission_date'], 'o': ['viral_panel'],
 'p': ['blood_gas'], 'q': ['cbc'], 'r': ['recurring_orders'], 's': ['intake_output']}
def assert_retained(out, before, section):
 assert out.errors and out.sheet is not None
 validate_sheet(out.sheet)
 assert section in out.sheet['import_warnings'] and section in out.skipped
 for key in FIELDS.get(section, []):
  assert out.sheet[key] == before[key]
 if section in 'klm':
  assert out.sheet['neuro_vitals'][section] == before['neuro_vitals'][section]
