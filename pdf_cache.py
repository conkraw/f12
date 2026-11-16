"""Bounded, session-private reuse of rendered patient PDFs.

No disk writes, shared Streamlit cache, background tasks, or archive changes.
The app owns one instance per signed-in session and closes it on reset/logout.
The download worker captures that instance, not Streamlit session state.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from threading import RLock

from lab_windows import display_clock
from models import validate_sheet


@dataclass(frozen=True)
class PreparedPdf:
    signature: str
    data: bytes
    page_count: int
    target_pages: int
    font_size: float
    tight_spacing: bool
    balanced_columns: bool

    @property
    def report(self) -> dict:
        return {'page_count': self.page_count, 'font_size': self.font_size,
                'fits_one_page': self.page_count == 1, 'target_pages': self.target_pages,
                'target_met': self.page_count <= self.target_pages,
                'tight_spacing': self.tight_spacing, 'balanced_columns': self.balanced_columns}


class SessionPdfCache:
    """Keep at most one body per room/page-target, with LRU memory bounds.

    Hash the complete clinical record and current display output before every
    reuse. A different patient, clinical edit, changed time-filtered display,
    or renderer version cannot match an old PDF. Metadata is stamped later.
    The lock prevents concurrent clicks from rendering the same body twice.
    """
    def __init__(self, *, max_entries: int = 128, max_bytes: int = 32 * 1024 * 1024):
        if type(max_entries) is not int or type(max_bytes) is not int or min(max_entries, max_bytes) < 1:
            raise ValueError('PDF cache limits must be positive integers.')
        self._entries: OrderedDict[tuple[str, int], PreparedPdf] = OrderedDict()
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._bytes = 0
        self._builds = 0
        self._hits = 0
        self._closed = False
        self._lock = RLock()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def stats(self) -> dict:
        """Only counts, never patient data or cache fingerprints."""
        with self._lock:
            return {'entries': len(self._entries), 'bytes': self._bytes,
                    'builds': self._builds, 'hits': self._hits, 'closed': self._closed}

    def _drop(self, slot: tuple[str, int]) -> None:
        old = self._entries.pop(slot, None)
        if old is not None:
            self._bytes -= len(old.data)

    def invalidate_room(self, room: str) -> None:
        with self._lock:
            for slot in list(self._entries):
                if slot[0] == room:
                    self._drop(slot)

    def close(self) -> None:
        """Discard retained bytes and make captured old worker instances unusable."""
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._closed = True

    def prepare(self, sheet: dict, printed_at: datetime | None = None, *,
                target_pages: int = 1) -> PreparedPdf:
        from exports import handoff_pdf_body, pdf_content_signature
        snapshot = deepcopy(sheet)
        validate_sheet(snapshot)
        if type(target_pages) is not int or target_pages not in (1, 2):
            raise ValueError('Choose a one-page or two-page print target.')
        with self._lock, display_clock(printed_at) as instant:
            if self._closed:
                raise ValueError('This print session was cleared. Prepare a new download.')
            signature = pdf_content_signature(snapshot, instant, target_pages=target_pages)
            slot = (snapshot['room'], target_pages)
            existing = self._entries.get(slot)
            if existing is not None and existing.signature == signature:
                self._entries.move_to_end(slot)
                self._hits += 1
                return existing
            # Remove an obsolete variant before building. Never fall back to it
            # when the new render fails, even when the room/id remains the same.
            self._drop(slot)
            data, report = handoff_pdf_body(snapshot, instant, target_pages=target_pages)
            if not isinstance(data, bytes) or not data.startswith(b'%PDF-'):
                raise ValueError('The patient PDF could not be prepared.')
            result = PreparedPdf(signature, data, report['page_count'], target_pages,
                                 report['font_size'], report['tight_spacing'], report['balanced_columns'])
            self._builds += 1
            if len(data) <= self._max_bytes:
                while self._entries and (len(self._entries) >= self._max_entries or
                                         self._bytes + len(data) > self._max_bytes):
                    self._drop(next(iter(self._entries)))
                self._entries[slot] = result
                self._bytes += len(data)
            return result


def cached_handoffs_pdf(sheets: list[dict], cache: SessionPdfCache,
                        printed_at: datetime | None = None, *, target_pages: int = 1,
                        save_statuses: dict | None = None) -> bytes:
    """Assemble current cached clinical pages with fresh, truthful metadata.

    Only newly changed/missing patient bodies invoke ReportLab's clinical
    renderer. Existing pages are copied as PDF content, not rasterized or
    reflowed. Every patient still starts on a new page. The caller retains
    authentication, cancellation, and shared-record checks before/after this.
    """
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from exports import draw_pdf_metadata
    from print_time import eastern_print_time
    from save_status import handoff_save_caption

    if not sheets or len(sheets) > 100:
        raise ValueError('Select between 1 and 100 handoffs to print.')
    snapshot = deepcopy(sheets)
    for sheet in snapshot:
        validate_sheet(sheet)
    if len({s['room'] for s in snapshot}) != len(snapshot):
        raise ValueError('A room cannot be included twice in one print packet.')
    statuses = deepcopy(save_statuses or {})
    for sheet in snapshot:
        handoff_save_caption(sheet, statuses.get(sheet['room']))
    with display_clock(printed_at) as instant:
        prepared = [cache.prepare(sheet, instant, target_pages=target_pages) for sheet in snapshot]
        stamp = eastern_print_time(instant)
        metadata_bytes = BytesIO()
        c = canvas.Canvas(metadata_bytes, pagesize=(792, 612), pageCompression=1)
        c.setAuthor('')
        for position, (sheet, body) in enumerate(zip(snapshot, prepared), 1):
            for page in range(1, body.page_count + 1):
                draw_pdf_metadata(c, sheet, 792, 612, position, len(snapshot), stamp,
                                  page, statuses.get(sheet['room']))
                c.showPage()
        c.save()
        metadata = PdfReader(BytesIO(metadata_bytes.getvalue()))
        output = BytesIO()
        writer = PdfWriter()
        try:
            index = 0
            for body in prepared:
                reader = PdfReader(BytesIO(body.data))
                if len(reader.pages) != body.page_count:
                    raise ValueError('The patient PDF page count could not be verified.')
                for source_page in reader.pages:
                    page = writer.add_page(source_page)
                    page.merge_page(metadata.pages[index])
                    # Merging expands PDF streams. Recompress without changing
                    # layout so reuse does not inflate the download payload.
                    page.compress_content_streams()
                    index += 1
            if cache.closed:
                raise ValueError('This print session was cleared. Prepare a new download.')
            writer.add_metadata({'/Title': 'PICU handoffs', '/Author': ''})
            writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
            writer.write(output)
            return output.getvalue()
        finally:
            writer.close()
