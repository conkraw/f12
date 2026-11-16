"""Reproducible synthetic CPU benchmark for dated-score rendering and Print all.

Examples:
    python3 validation/profile_scores_682.py --variant dated --labs --print-all
    python3 validation/profile_scores_682.py --app-root /path/to/6.80 --variant legacy

No patient paste, live archive, network operation or Streamlit server is used.
Timings are local CPU measurements, not predictions of live application latency.
"""
from pathlib import Path
import argparse
import cProfile
import io
import json
import platform
import pstats
import statistics
import sys
import time
from copy import deepcopy
from datetime import datetime
from importlib.metadata import version


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--variant', choices=('legacy', 'dated'), default='dated')
    parser.add_argument('--labs', action='store_true', help='Include 40 synthetic laboratory rows.')
    parser.add_argument('--print-all', action='store_true', help='Also benchmark a warmed 18-room PDF packet.')
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--output', type=Path)
    return parser.parse_args()


def benchmark(function, loops, repetitions):
    function()
    raw = []
    for _ in range(repetitions):
        start = time.perf_counter()
        for _ in range(loops):
            function()
        raw.append((time.perf_counter() - start) / loops * 1000)
    return {'median_ms': round(statistics.median(raw), 6),
            'min_ms': round(min(raw), 6), 'raw_ms_per_operation': raw,
            'loops_per_repetition': loops, 'repetitions': repetitions}


def main():
    args = arguments()
    if args.repetitions < 1:
        raise ValueError('Use at least one repetition.')
    sys.path.insert(0, str(args.app_root.resolve()))
    from models import new_sheet, new_vault, validate_sheet, validate_vault, automatic_vitals, DEFAULT_ROOMS
    from exports import handoff_html, handoff_pdf, pdf_content_signature
    from batching import available_handoffs
    from labs import parse_labs
    from lab_windows import display_clock, EASTERN
    from security import generate_key, seal_vault
    from pdf_cache import SessionPdfCache, cached_handoffs_pdf
    from pypdf import PdfReader
    import _strptime

    instant = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)
    sheet = new_sheet('P4102')
    sheet['sbs_vent_mode'] = 'PC'
    sheet['fields']['Diagnoses'] = 'SYNTHETIC BENCHMARK'
    sheet['sbs_observations'] = {'readings': [
        {'value': '-1', 'recorded_at': '11/16/2026 09:00', 'include': True}], 'notes': []}
    for source, label, score in [('y', 'CAPD', '6'), ('l', 'WAT-1', '2')]:
        value = score + (' (11/16/26)' if args.variant == 'dated' else '')
        sheet['neuro_vitals'][source] = [
            {'label': label, 'value': value, 'section': 'Neurologic', 'include': True}]
    if args.labs:
        components = ['NA', 'K', 'CL', 'CO2', 'BUN', 'CREATININE', 'GLUCOSE', 'CA', 'MG', 'PHOS']
        source = 'Component\tValue\tDate\n' + '\n'.join(
            f'{component}\t{index + 1}\t11/{16 - day:02d}/2026'
            for day in range(4) for index, component in enumerate(components))
        parsed = parse_labs(source)
        if parsed.error:
            raise ValueError(parsed.error)
        sheet['labs'] = parsed.data
    validate_sheet(sheet)
    vault = new_vault()
    for room in DEFAULT_ROOMS[:18]:
        one = deepcopy(sheet)
        one['room'] = room
        one['id'] = new_sheet(room)['id']
        vault['rooms'][room] = one
    validate_vault(vault)
    key = generate_key()
    with display_clock(instant):
        functions = {
            'validate_sheet': (lambda: validate_sheet(sheet), 100),
            'automatic_vitals': (lambda: automatic_vitals(sheet), 100),
            'validate_census': (lambda: validate_vault(vault), 5),
            'available_census': (lambda: available_handoffs(vault, {}), 5),
            'pdf_signature_one': (lambda: pdf_content_signature(sheet, instant), 20),
            'html_one': (lambda: handoff_html(sheet, instant), 10),
            'pdf_one': (lambda: handoff_pdf(sheet, instant), 3),
            'encrypt_census': (lambda: seal_vault(vault, key), 5),
        }
        measurements = {name: benchmark(function, loops, args.repetitions)
                        for name, (function, loops) in functions.items()}
        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(30):
            handoff_html(sheet, instant)
        profiler.disable()
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats('cumulative').print_stats(20)
        call_counts = []
        for (filename, _, name), (_, count, self_time, total, _) in stats.stats.items():
            if (filename.endswith('_strptime.py') and name in ('compile', 'pattern', '_strptime')) or (
                    filename.endswith(('labs.py', 'score_dates.py')) and name == 'date_parts'):
                call_counts.append({'module': Path(filename).name, 'function': name,
                                    'calls': count, 'cumulative_seconds': total,
                                    'self_seconds': self_time})
        print_all = None
        if args.print_all:
            sheets = list(vault['rooms'].values())
            unchanged = deepcopy(sheets)
            cache = SessionPdfCache()
            begin = time.perf_counter()
            for current in sheets:
                cache.prepare(current, instant)
            prepare_ms = (time.perf_counter() - begin) * 1000
            before = cache.stats
            packet = [b'']

            def make_packet():
                packet[0] = cached_handoffs_pdf(sheets, cache, instant)
                return packet[0]

            measured = benchmark(make_packet, 1, args.repetitions)
            after = cache.stats
            pages = len(PdfReader(io.BytesIO(packet[0])).pages)
            if before['builds'] != len(sheets) or after['builds'] != before['builds']:
                raise AssertionError('A warmed packet rebuilt a clinical PDF body.')
            if sheets != unchanged or pages != len(sheets):
                raise AssertionError('Synthetic packet integrity failed.')
            print_all = {'rooms': len(sheets), 'pages': pages,
                         'initial_prepare_ms': prepare_ms,
                         'initial_body_builds': before['builds'],
                         'final_body_builds': after['builds'],
                         'additional_body_builds': after['builds'] - before['builds'],
                         'cache_hits_during_warm_and_measured_packets': after['hits'] - before['hits'],
                         'warm_packet': measured}
            cache.close()
    result = {'app_directory': args.app_root.name, 'variant': args.variant,
              'lab_rows': len(sheet['labs']['rows']), 'census_rooms': len(vault['rooms']),
              'environment': {'python': platform.python_version(),
                              'reportlab': version('reportlab'), 'pypdf': version('pypdf')},
              'measurements': measurements, 'print_all': print_all,
              'profile': {'html_renders': 30, 'strptime_cache_capacity': _strptime._CACHE_MAX_SIZE,
                          'selected_calls': call_counts, 'top_cumulative': stream.getvalue()},
              'limitations': 'Synthetic local CPU benchmark. No live Streamlit server, network save, production data or concurrent-user load.'}
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
        print(str(args.output))
    else:
        print(text)


if __name__ == '__main__':
    main()
