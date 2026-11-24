"""Real Streamlit import, patient preview and save for HC and estimated IBW."""
from copy import deepcopy
from html import unescape
from io import BytesIO
import re

from pypdf import PdfReader

from exports import handoff_pdf
from test_prn_preview_native import native_app, import_source


def block(letter, body):
    marker = letter * 24
    return marker + '\n' + body + '\n' + marker + '\n'


def normalized_preview(at):
    html = next(item.proto.srcdoc for item in at.get('iframe')
                if 'Synthetic growth example' in item.proto.srcdoc)
    return ' '.join(unescape(re.sub(r'<[^>]*>', '', html)).split())


def test_native_hc_then_obese_patient_replacement_and_save(native_app):
    at = native_app
    infant = (block('a', 'Diagnoses:\nSynthetic growth example\nAge: 183 days\nSex: male')
              + block('i', 'NUTRITION:\nWeight: 8 kg\nDosing Weight: 8 kg\n'
                      'Length: 68 cm\nHead Circumference: 43.52 cm (11/24/26 0600)\n'
                      'HC Age: 183 days'))
    import_source(at, infant)
    saved = deepcopy(at.session_state['vault']['rooms']['P4102'])
    assert saved['anthropometrics']['hc_age'] == '183 days'
    assert '[56th %tile]' in normalized_preview(at)
    assert 'Estimated IBW' not in normalized_preview(at)
    pages = PdfReader(BytesIO(handoff_pdf(saved))).pages
    assert len(pages) == 1
    assert '[56th %tile]' in ' '.join(pages[0].extract_text().split())

    at.session_state['handoff_tab'] = 'Labs / Vitals'
    at.run()
    assert not at.exception and not at.error
    assert at.text_input(key='anthro_' + saved['id'] + '_hc_age').value == '183 days'

    adolescent = (block('a', 'Diagnoses:\nSynthetic growth example\nAge: 15 years\nSex: male')
                  + block('i', 'NUTRITION:\nWeight: 95 kg\nDosing Weight: 70 kg\n'
                          'Height: 160 cm\nBMI: 37.11\nBMI Age: 15 years 0 months'))
    import_source(at, adolescent)
    sheet = deepcopy(at.session_state['vault']['rooms']['P4102'])
    assert sheet['id'] != saved['id']
    assert 'hc_age' not in sheet['anthropometrics']
    assert sheet['nutrition']['weight'] == '95 kg'
    assert sheet['dosing_weight'] == '70 kg'
    at.session_state['handoff_tab'] = 'Handoff'
    at.run()
    assert not at.exception and not at.error
    preview = normalized_preview(at)
    assert 'Estimated IBW: 50.8 kg (BMI 50th %tile)' in preview
    assert 'Head circumference:' not in preview
    assert 'Severe obesity' in preview
    next(button for button in at.button if button.label == 'Save handoff').click().run()
    assert not at.exception and not at.error
    assert at.session_state['vault']['rooms']['P4102']['dosing_weight'] == '70 kg'
    pages = PdfReader(BytesIO(handoff_pdf(sheet))).pages
    assert len(pages) == 1
    assert 'Estimated IBW: 50.8 kg (BMI 50th %tile)' in ' '.join(pages[0].extract_text().split())
