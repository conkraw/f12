"""Button-driven note review. Generated patient text stays in this session."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from threading import Event
import time

from note_settings import normalize_note_settings


PREFIX = "utility_note_"
DRAFT_KEY = PREFIX + "draft"
EDITOR_KEY = PREFIX + "editor"
SELECTION_KEY = PREFIX + "selected"
ADDITIONAL_KEY = PREFIX + "additional"
STYLE_KEY = PREFIX + "style"
INVASIVE_KEY = PREFIX + "invasive_phrase"
ROOM_KEY = PREFIX + "room"
TYPE_KEY = PREFIX + "type"
REVOKE_KEY = PREFIX + "revocation"
MAX_NOTE_LENGTH = 200_000
NOTE_TYPES = {"progress": "Progress note", "attestation": "Attending attestation"}
WORD_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEFAULT_INVASIVE_PHRASE = "ACKZACUTEHYPOXEMICRESPIRATORYFAILUREINVASIVE"


def clear_note_draft(state, *, all_values: bool = False) -> None:
    event = state.pop(REVOKE_KEY, None)
    if event is not None:
        event.set()
    keys = tuple(state) if all_values else (
        DRAFT_KEY, EDITOR_KEY, SELECTION_KEY, ADDITIONAL_KEY, PREFIX + "pending_choices",
    )
    for key in keys:
        if key.startswith(PREFIX):
            state.pop(key, None)


def source_signature(sheet: dict) -> str:
    clinical = {key: value for key, value in sheet.items()
                if key not in ("created_at", "updated_at")}
    payload = json.dumps(clinical, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def note_sources(vault: dict, drafts: dict) -> dict:
    """Collect current patients without rendering handoffs or calculating doses."""
    from batching import room_order
    rooms = dict(vault.get("rooms", {}))
    rooms.update(drafts)
    ready = {}
    for room in sorted(rooms, key=room_order):
        sheet = rooms[room]
        if not isinstance(sheet, dict):
            continue
        fields = sheet.get("fields", {})
        filled = any(str(value).strip() for value in fields.values())
        filled = filled or bool(sheet.get("medications"))
        filled = filled or any(sheet.get(key) for key in (
            "ventilation", "noninvasive", "devices", "neuro_devices", "ecls",
            "code_status", "dosing_weight", "nutrition", "diet", "feeds",
        ))
        if filled:
            ready[room] = sheet
    return ready


def create_note_draft(state, sheet: dict, *, authorize, settings: dict,
                      selected_ids=None, generator=None, clinical_settings=None,
                      note_type: str = "progress", word_renderer=None) -> bool:
    """Recheck access at the action boundary, including stale browser events."""
    if not authorize():
        clear_note_draft(state)
        return False
    options = normalize_note_settings(settings)
    if note_type not in NOTE_TYPES:
        raise ValueError("Choose a progress note or attending attestation.")
    if generator is None:
        from note_generator import generate_note
        generator = generate_note
    result = generator(deepcopy(sheet), phrase_style=options["phrase_style"],
                       phrase_overrides=options["phrase_overrides"],
                       selected_ids=selected_ids, settings=deepcopy(clinical_settings or {}),
                       note_type=note_type)
    text = result.get("text")
    if not isinstance(text, str) or len(text) > MAX_NOTE_LENGTH:
        raise ValueError("The generated note is too long. Shorten the handoff and try again.")
    if word_renderer is None:
        from note_word import render_note_docx
        word_renderer = render_note_docx
    word_bytes = word_renderer(result, note_type=note_type)
    if not isinstance(word_bytes, bytes) or not word_bytes.startswith(b"PK"):
        raise ValueError("The Word document could not be prepared. Generate the note again.")
    if not authorize():
        clear_note_draft(state)
        return False
    clear_note_draft(state)
    state[REVOKE_KEY] = Event()
    state[DRAFT_KEY] = {
        "room": sheet["room"], "sheet_id": sheet["id"],
        "source_signature": source_signature(sheet),
        "options": deepcopy(options), "result": result,
        "note_type": note_type, "word_bytes": word_bytes,
    }
    state[EDITOR_KEY] = text
    state[SELECTION_KEY] = [item["id"] for item in result["suggestions"]
                            if item.get("selected")]
    state[ADDITIONAL_KEY] = []
    return True


def draft_matches(draft: dict | None, sheet: dict) -> bool:
    return bool(draft and draft.get("room") == sheet.get("room")
                and draft.get("sheet_id") == sheet.get("id")
                and draft.get("source_signature") == source_signature(sheet))


def note_download(content: str | bytes, *, revoked: Event, expires_at: float, check_current=None):
    """A worker-safe download with captured access, expiry, and census guards."""
    if not isinstance(content, (str, bytes)):
        raise ValueError("The note download is unavailable. Generate the note again.")
    payload = content.encode("utf-8") if isinstance(content, str) else content

    def download():
        def check():
            if revoked.is_set() or time.monotonic() >= expires_at:
                raise ValueError("The note download expired. Unlock Utilities and generate a new note.")
        check()
        if check_current is not None:
            check_current()
        check()
        return payload

    return download


def render_note_utility(st, *, authorize, get_sources, stored_settings,
                        save_settings, make_download, current_room=None,
                        clinical_settings=None) -> None:
    """Render review controls. Only the two explicit buttons call the generator."""
    if not authorize():
        clear_note_draft(st.session_state, all_values=True)
        return
    ss = st.session_state
    pending = ss.pop(PREFIX + "pending_choices", None)
    if pending is not None:
        ss[SELECTION_KEY] = pending
        ss[ADDITIONAL_KEY] = []
    sources = get_sources()
    st.subheader("Generate a Word document")
    st.caption("Choose a handoff and a template, then click Generate note. The Word download keeps your original template formatting.")
    if not sources:
        clear_note_draft(ss)
        st.info("Create a handoff first, then return to Utilities.")
        return
    choices = list(sources)
    if ss.get(ROOM_KEY) not in choices:
        ss[ROOM_KEY] = current_room if current_room in sources else choices[0]
    room = st.selectbox("Patient handoff", choices, key=ROOM_KEY,
                        on_change=clear_note_draft, args=(ss,))
    if ss.get(TYPE_KEY) not in NOTE_TYPES:
        ss[TYPE_KEY] = "progress"
    note_type = st.radio("Document type", list(NOTE_TYPES), key=TYPE_KEY,
                         format_func=lambda value: NOTE_TYPES[value], horizontal=True,
                         on_change=clear_note_draft, args=(ss,))
    sheet = sources[room]
    draft = ss.get(DRAFT_KEY)
    if draft and (not draft_matches(draft, sheet)
                  or draft.get("note_type") != note_type or not draft.get("word_bytes")):
        clear_note_draft(ss)
        st.info("The selected handoff or document type changed. Click Generate note to prepare the current Word document.")
    options = normalize_note_settings(stored_settings)
    ss.setdefault(STYLE_KEY, options["phrase_style"])
    ss.setdefault(INVASIVE_KEY, options["phrase_overrides"].get("acute_hypoxemic_invasive", DEFAULT_INVASIVE_PHRASE))
    with st.expander("Epic phrase settings", expanded=False):
        st.radio("Plan reference format", ("at", "dot"), key=STYLE_KEY,
                 format_func=lambda value: "Template references (@NAME@)" if value == "at" else "Dot phrases (.NAME)")
        st.text_input("Invasive respiratory failure phrase name", key=INVASIVE_KEY,
                      max_chars=122,
                      help="Uses the exact phrase name you provided. Change this only if the name in Epic changes.")
        st.caption("Invasive and noninvasive respiratory plans use your supplied ACKZ names. Confirm that the chosen references expand in your Epic setup.")
        if st.button("Save phrase settings", key=PREFIX + "save_settings"):
            if authorize():
                try:
                    new_options = _widget_options(ss, options)
                    save_settings(new_options)
                    options = new_options
                    st.success("Phrase settings saved.")
                except ValueError as exc:
                    st.error(str(exc))
                except Exception:
                    st.error("The phrase settings could not be saved. Your note is still available.")
    if st.button("Generate note", type="primary", key=PREFIX + "generate"):
        try:
            current = get_sources().get(room)
            if current is None or source_signature(current) != source_signature(sheet):
                clear_note_draft(ss)
                st.error("The handoff changed. Select it again and generate a new note.")
                return
            create_note_draft(ss, current, authorize=authorize,
                              settings=_widget_options(ss, options),
                              clinical_settings=clinical_settings, note_type=note_type)
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("The note could not be generated. Your handoff has not been changed.")
    draft = ss.get(DRAFT_KEY)
    if not draft or not draft_matches(draft, sheet) or draft.get("note_type") != note_type:
        return
    result = draft["result"]
    if note_type == "attestation":
        st.caption("Your attending attestation keeps its examination SmartLists and selected plans. Medication lists stay in the resident's note.")
    else:
        st.caption("Medication review lists follow the main systems in your progress note. Review and edit the downloaded document in Word.")
    for warning in result.get("warnings", []):
        st.warning(warning)
    from note_generator import get_phrase_catalog
    suggested = {item["id"]: item for item in result["suggestions"]}
    catalog = {item["id"]: item for item in get_phrase_catalog()}
    if suggested:
        st.multiselect("Include these suggested plans", list(suggested),
                       key=SELECTION_KEY,
                       format_func=lambda key: suggested[key]["label"])
        with st.expander("Why these plans were suggested", expanded=False):
            for item in suggested.values():
                st.text(item["label"] + ": " + " | ".join(item.get("reasons", [])))
                st.caption(item.get("phrase") or "Enter the exact phrase name in Epic phrase settings.")
    additional = [key for key in catalog if key not in suggested]
    st.multiselect("Add another plan", additional, key=ADDITIONAL_KEY,
                   format_func=lambda key: catalog[key]["label"])
    if st.button("Update note with selected plans", key=PREFIX + "update"):
        try:
            selected = list(dict.fromkeys(ss.get(SELECTION_KEY, []) + ss.get(ADDITIONAL_KEY, [])))
            current = get_sources().get(room)
            if current is None or not draft_matches(draft, current):
                clear_note_draft(ss)
                st.error("The handoff changed. Generate a new note before updating the plan.")
                return
            # Widget keys above have already rendered. A separate callback-free
            # draft refresh defers new selection keys until the next script run.
            temporary = {}
            if create_note_draft(temporary, current, authorize=authorize,
                                 settings=_widget_options(ss, options), selected_ids=selected,
                                 clinical_settings=clinical_settings, note_type=note_type):
                old_event = ss.get(REVOKE_KEY)
                if old_event is not None:
                    old_event.set()
                ss[DRAFT_KEY] = temporary[DRAFT_KEY]
                ss[REVOKE_KEY] = temporary[REVOKE_KEY]
                ss[EDITOR_KEY] = temporary[EDITOR_KEY]
                # Keep the already rendered choice widgets stable on this run.
                ss[PREFIX + "pending_choices"] = temporary[SELECTION_KEY]
                draft = ss[DRAFT_KEY]
                result = draft["result"]
                st.success("Note updated from the current handoff and selected plans.")
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("The note could not be updated. The existing draft is still available.")
    if not authorize():
        clear_note_draft(ss, all_values=True)
        return
    file_prefix = "attending_attestation_" if note_type == "attestation" else "picu_progress_note_"
    st.download_button("Download Word document (.docx)", make_download(draft["word_bytes"], draft),
                       file_name=file_prefix + room + ".docx", mime=WORD_MIME,
                       key=PREFIX + "word_download", type="primary", on_click="ignore")
    st.caption("Preview text is shown below. Open the Word download to see your formatting and make edits.")
    st.text_area("Generated note preview", height=540, key=EDITOR_KEY,
                 max_chars=MAX_NOTE_LENGTH, disabled=True)
    text = result["text"]
    with st.expander("Plain text", expanded=False):
        st.code(text, language=None)
        st.download_button("Download plain text (.txt)", make_download(text, draft),
                           file_name=file_prefix + room + ".txt", mime="text/plain",
                           key=PREFIX + "download", on_click="ignore")
    st.caption("Generate note or Update note prepares a fresh Word document from the selected handoff and plans.")


def _widget_options(state, base: dict) -> dict:
    overrides = dict(base.get("phrase_overrides", {}))
    overrides["acute_hypoxemic_invasive"] = state.get(INVASIVE_KEY, "")
    return normalize_note_settings({"phrase_style": state.get(STYLE_KEY, "at"),
                                    "phrase_overrides": overrides})
