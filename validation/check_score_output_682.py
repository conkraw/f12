"""Compare 6.81 and 6.82 score output using identical synthetic records.

Run with the two application directories. The check uses fresh child processes
so modules from the versions cannot mix. Generated IDs and save metadata are
fixed, and source dates and values are left unchanged.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys


def worker(root):
    sys.path.insert(0, str(root))
    from datetime import datetime
    from exports import handoff_html, handoff_text
    from importing import import_replacement
    from models import automatic_vitals, new_vault, validate_sheet
    from lab_windows import EASTERN, display_clock

    def block(letter, body):
        return letter * 24 + '\n' + body + '\n' + letter * 24

    def fix_generated_metadata(data, prefix='root'):
        if isinstance(data, dict):
            for key, value in data.items():
                if key == 'id' and isinstance(value, str) and len(value) == 32:
                    data[key] = hashlib.sha256((prefix + '/id').encode()).hexdigest()[:32]
                elif key in ('created_at', 'updated_at'):
                    data[key] = '2026-11-16T17:00:00+00:00'
                else:
                    fix_generated_metadata(value, prefix + '/' + key)
        elif isinstance(data, list):
            for index, value in enumerate(data):
                fix_generated_metadata(value, prefix + '/' + str(index))

    cases = [
        ('invasive_observed', 'Pressure Control - Intermittent Mandatory Ventilation', 'Endotracheal tube',
         'SBS Last 24 Hours:\nSBS -2 (11/15/26 0730 : Example Recorder, RN)\nSBS -1 (11/16/26 0900 : Example Recorder, RN)'),
        ('invasive_target', 'Pressure Support - Continuous Positive Airway Pressure', 'Endotracheal tube',
         'Target Arousal Level:\nSBS Last 24 Hours: Target Arousal Level (SBS): SBS 0 (11/15/26 0900 : Example Recorder, DO)'),
        ('nasal_cannula', '', 'Nasal cannula',
         'Target Arousal Level:\nSBS Last 24 Hours: Target Arousal Level (SBS): SBS 0 (11/15/26 0900 : Example Recorder, DO)'),
    ]
    results = {}
    instant = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)
    with display_clock(instant):
        for name, mode, delivery, sbs in cases:
            source = '\n'.join([
                block('a', 'Diagnoses:\n1. SYNTHETIC OUTPUT PARITY'),
                block('c', 'Invasive Ventilation:\nMode: ' + mode),
                block('d', 'Non-invasive Ventilation:\nO2 Delivery Method: ' + delivery),
                block('k', sbs),
                block('y', 'CAPD: 9 (11/15/26 0800 : Example Recorder, RN)\nCAPD: 6 (11/16/26 0800 : Example Recorder, RN)'),
                block('l', 'WAT Score:\nWAT-1: 4 (11/16/26 0600 : Example Recorder, RN)\nWAT-1: 2 (11/16/26 0640 : Example Recorder, RN)'),
            ])
            imported = import_replacement('P4102', source, new_vault()['settings'])
            if imported.errors:
                raise AssertionError(imported.errors)
            sheet = imported.sheet
            fix_generated_metadata(sheet)
            validate_sheet(sheet)
            text = handoff_text(sheet, instant)
            html = handoff_html(sheet, instant)
            if 'Example Recorder' in text or 'Example Recorder' in html:
                raise AssertionError('A synthetic attribution appeared in output.')
            results[name] = {
                'neuro': automatic_vitals(sheet)['Neurologic'],
                'sheet_sha256': hashlib.sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest(),
                'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'html_sha256': hashlib.sha256(html.encode()).hexdigest(),
            }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path, nargs='?')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.before), sort_keys=True))
        return
    if not args.after:
        parser.error('Supply both application directories.')
    results = []
    for directory in (args.before, args.after):
        raw = subprocess.check_output([sys.executable, str(Path(__file__).resolve()), str(directory), '--worker'], text=True)
        results.append(json.loads(raw))
    if results[0] != results[1]:
        raise AssertionError('The normalized synthetic score output differs.')
    report = {'before': args.before.name, 'after': args.after.name,
              'equal': True, 'cases': results[0],
              'checked': ['normalized stored sheet', 'text output', 'HTML output'],
              'metadata_fixed': ['generated identifiers', 'creation timestamp', 'save timestamp']}
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
        print(str(args.output))
    else:
        print(text)


if __name__ == '__main__':
    main()
