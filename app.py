# app.py
import os
from typing import Optional, Iterable

import streamlit as st
import streamlit.components.v1 as components

from common import (
    DEFAULT_DISPLAY_WIDTH,
    load_index_v2,
    save_index_v2,
    audit_paths,
    decode_upload_to_pil,
    ensure_new_fields,
    index_prefers_relative,
    add_image_record,
    save_video_file,
    ensure_media_dirs,
    save_base_image,
    attach_media
)
from editor import landing_page, project_main_ui

st.set_page_config(page_title="WiiGoR Audits", layout="wide")


# =============================================================================
# Helpers
# =============================================================================

def safe_rerun() -> None:
    """
    Trigger a Streamlit rerun, compatible with older versions where
    st.rerun may not exist (fall back to st.experimental_rerun).
    """
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()

def _ensure_session_default(key: str, default) -> None:
    """Small helper to set a default value in session_state if missing."""
    if key not in st.session_state:
        st.session_state[key] = default

def scroll_to_top() -> None:
    """
    Scroll the visible Streamlit page to the very top.

    This explicitly scrolls the inner Streamlit containers
    (section.main / block-container), not just the window.
    """
    components.html(
        """
        <script>
        (function() {
            try {
                const root = window.parent || window;
                const doc = root.document;

                // Try the main scrolling containers used by Streamlit
                const targets = [
                    'section.main',
                    'div[data-testid="stAppViewContainer"]',
                    'div.block-container'
                ];

                let scrolled = false;
                for (const sel of targets) {
                    const el = doc.querySelector(sel);
                    if (el) {
                        if (el.scrollTo) {
                            el.scrollTo({ top: 0, left: 0, behavior: 'auto' });
                        } else {
                            el.scrollTop = 0;
                            el.scrollLeft = 0;
                        }
                        scrolled = true;
                    }
                }

                // Fallback: also try the window itself
                if (!scrolled && root.scrollTo) {
                    root.scrollTo(0, 0);
                }
            } catch (e) {
                // ignore errors
            }
        })();
        </script>
        """,
        height=0,
    )

def _increment_image_counter(idx: dict) -> str:
    """
    Increase the global image counter in index['counters']['images'] and
    return the new number as a zero-padded 3-digit string.
    """
    counters = idx.setdefault("counters", {})
    current = int(counters.get("images", 0))
    current += 1
    counters["images"] = current
    return f"{current:03d}"

def _images_for_audit(index: dict, audit_id: str) -> list[dict]:
    """Return all image records belonging to a specific audit."""
    return [
        r for r in index.get("images", [])
        if r.get("audit_id") == audit_id
    ]

def _find_image_idx_by_nr(images: Iterable[dict], nr: str) -> int:
    """
    Find the index of the image with given 'nr' in the list; if not found,
    fall back to the last image index (or 0 if the list is empty).
    """
    images = list(images)
    for i, r in enumerate(images):
        if r.get("nr") == nr:
            return i
    return max(len(images) - 1, 0)

# =============================================================================
# Session Defaults
# =============================================================================

_ensure_session_default("mode", "landing")
_ensure_session_default("paths", None)
_ensure_session_default("current_idx", 0)
_ensure_session_default("canvas_ver", 0)
_ensure_session_default("upload_key", 0)
_ensure_session_default("stroke_width", 6)
_ensure_session_default("marking_active", True)
_ensure_session_default("display_width", DEFAULT_DISPLAY_WIDTH)
_ensure_session_default("current_audit_id", None)
_ensure_session_default("scroll_to_top", False)

# =============================================================================
# App Flow
# =============================================================================
if st.session_state.get("scroll_to_top"):
    scroll_to_top()
    # Reset the flag so normal reruns don't keep jumping
    st.session_state["scroll_to_top"] = False

if st.session_state.mode == "landing" or st.session_state.paths is None:
    # Top-level: project & audit selection, landing UI
    landing_page()
else:
    paths = st.session_state.paths
    idx = load_index_v2(paths["index"])

    # -------------------------------------------------------------------------
    # SIDEBAR: Bilder hinzufügen (Upload oder Kamera)
    # -------------------------------------------------------------------------
    st.sidebar.header("Bilder & Videos hinzufügen")

    current_audit_id: Optional[str] = st.session_state.get("current_audit_id")

    if current_audit_id:
        # Auswahl: Upload vs. Kamera (Foto) vs. Kamera (Video)
        source_mode = st.sidebar.radio(
            "Quelle wählen",
            ["Upload (Dateien)", "Kamera (Foto aufnehmen)", "Kamera (Video aufnehmen)"],
            index=0,
            key="img_source_mode",
        )

        # ==============================================================
        # Variante 1: Dateien hochladen (Bilder + Videos)
        # ==============================================================
        if source_mode.startswith("Upload"):
            up_files = st.sidebar.file_uploader(
                "Dateien (JPG, PNG, HEIC, MP4, MOV, AVI, MKV)",
                type=["jpg", "jpeg", "png", "heic", "mp4", "mov", "avi", "mkv"],
                accept_multiple_files=True,
                key=f"main_upload_{st.session_state.get('upload_key', 0)}",
                help="Mehrere Dateien sind möglich.",
            )

            video_exts = {".mp4", ".mov", ".avi", ".mkv"}
            selected_video_target_nr = None
            video_candidates_present = False

            if up_files:
                for _f in up_files:
                    fn = getattr(_f, "name", "") or ""
                    if os.path.splitext(fn.lower())[1] in video_exts:
                        video_candidates_present = True
                        break

            if video_candidates_present:
                imgs_this_audit = [r for r in idx.get("images", []) if r.get("audit_id") == current_audit_id]
                nr_options = [r.get("nr") for r in imgs_this_audit]
                if nr_options:
                    selected_video_target_nr = st.sidebar.selectbox(
                        "📌 Videos zuordnen zu Fehlerbild (optional)",
                        options=["— keine Auswahl —"] + nr_options,
                        index=0,
                        help="Wenn gewählt: die hochgeladenen Videos werden direkt diesem Fehlerbild zugeordnet.",
                        key="sidebar_video_target_nr",
                    )
                    if selected_video_target_nr == "— keine Auswahl —":
                        selected_video_target_nr = None
                else:
                    st.sidebar.info("Keine Fehlerbilder vorhanden – Videos können später im Referenz-Tab zugeordnet werden.")

            import_btn_disabled = not up_files
            if st.sidebar.button(
                "📥 Dateien importieren",
                use_container_width=True,
                disabled=import_btn_disabled,
            ):
                if not up_files:
                    st.sidebar.warning("Keine Dateien ausgewählt.")
                else:
                    try:
                        idx2 = load_index_v2(paths["index"])
                        a_paths = audit_paths(paths, current_audit_id)
                        prefer_rel = index_prefers_relative(idx2)
                        imported_images = 0
                        imported_videos = 0
                        last_nr: Optional[str] = None

                        for f in up_files:
                            file_name = getattr(f, "name", "upload")
                            file_ext = os.path.splitext(file_name.lower())[1]
                            is_video = file_ext in [".mp4", ".mov", ".avi", ".mkv"]
                            
                            if is_video:
                                record_nr_for_video = selected_video_target_nr
                                saved_path = save_video_file(
                                    f.read(),
                                    file_name,
                                    idx2,
                                    current_audit_id,
                                    paths,
                                    prefer_rel,
                                    record_nr_for_video
                                )
                                if saved_path:
                                    imported_videos += 1
                                    if record_nr_for_video is None:
                                        # store absolute paths to process later
                                        st.session_state.setdefault("video_attach_candidates", [])
                                        # normalize to absolute (for safety)
                                        abs_saved = saved_path if os.path.isabs(saved_path) else os.path.normpath(saved_path)
                                        st.session_state["video_attach_candidates"].append(abs_saved)
                            else:
                                pil = decode_upload_to_pil(
                                    f.read(),
                                    file_name,
                                )
                                # 2) Laufende Bildnummer bestimmen
                                nr = _increment_image_counter(idx2)

                                # Save base image with IMMUTABLE UUID-based filename
                                # This filename will NEVER change (not affected by reindex)
                                # Use unified deduplicated store
                                ensure_media_dirs()
                                base_ref = attach_media(pil_image=pil, media_type="image")  # returns "base_images/....jpg"
                                if not base_ref:
                                    raise RuntimeError("attach_media() konnte das Kamerabild nicht speichern.")

                                rec = add_image_record(idx2, base_ref, nr)

                                rec["audit_id"] = current_audit_id
                                ensure_new_fields(rec)

                                imported_images += 1
                                last_nr = nr

                        save_index_v2(paths["index"], idx2)

                        # Upload-Key erhöhen, damit der Uploader neu initialisiert wird
                        st.session_state.upload_key = (
                            st.session_state.get("upload_key", 0) + 1
                        )

                        # Editor auf das neueste importierte Fehlerbild setzen
                        if imported_images > 0 and last_nr is not None:
                            images_for_audit = _images_for_audit(
                                idx2,
                                current_audit_id,
                            )
                            idx_in_audit = _find_image_idx_by_nr(
                                images_for_audit,
                                last_nr,
                            )
                            st.session_state.current_idx = idx_in_audit
                            st.session_state["main_tab"] = "🛠️ Editor"
                            st.session_state.canvas_ver = (
                                st.session_state.get("canvas_ver", 0) + 1
                            )

                        st.sidebar.success(
                            f"{imported_images} Bild(er) und {imported_videos} Video(s) importiert."
                        )
                        if (imported_videos > 0) and (not selected_video_target_nr):
                            st.session_state["main_tab"] = "🎬 Referenz"
                            st.session_state["show_video_attach_dialog"] = True
                        safe_rerun()
                    except Exception as ex:
                        st.sidebar.error(f"Upload fehlgeschlagen: {ex}")

        # ==============================================================
        # Variante 2: Foto mit Kamera aufnehmen
        # ==============================================================
        elif source_mode == "Kamera (Foto aufnehmen)":
            st.sidebar.caption(
                "Kamera verwenden, um direkt ein Fehlerbild aufzunehmen."
            )
            # Dynamischer Key, damit das Widget nach dem Speichern sauber
            # zurückgesetzt wird (neues Foto, keine „Geisterwerte").
            cam_key = f"main_camera_input_{st.session_state.get('upload_key', 0)}"

            camera_photo = st.sidebar.camera_input(
                "Foto aufnehmen",
                key=cam_key,
            )
            save_disabled = camera_photo is None
            if st.sidebar.button(
                "✅ Foto speichern",
                use_container_width=True,
                key="btn_save_camera_main",
                disabled=save_disabled,
            ):
                if camera_photo is None:
                    st.sidebar.warning("Bitte zuerst ein Foto aufnehmen.")
                else:
                    try:
                        idx2 = load_index_v2(paths["index"])
                        ensure_media_dirs()

                        # Ein einzelnes Foto aus der Kamera in PIL dekodieren
                        pil = decode_upload_to_pil(
                            camera_photo.getvalue(),
                            "camera.jpg",
                        )

                        # Neue laufende Fehlerbild-Nummer
                        nr = _increment_image_counter(idx2)
                        # Save base image with IMMUTABLE UUID-based filename
                        ensure_media_dirs()
                        base_filename, raw_abs = save_base_image(pil, ".jpg")
                        
                        # Store reference with subdirectory path
                        raw_store = f"base_images/{base_filename}"
                        rec = add_image_record(idx2, raw_store, nr)
                        rec["audit_id"] = current_audit_id
                        ensure_new_fields(rec)

                        # Index speichern
                        save_index_v2(paths["index"], idx2)

                        # Fehlerbilder dieses Audits suchen und Index im Editor bestimmen
                        images_for_audit = _images_for_audit(idx2, current_audit_id)
                        idx_in_audit = _find_image_idx_by_nr(images_for_audit, nr)

                        # Editor auf dieses Fehlerbild setzen
                        st.session_state.current_idx = idx_in_audit
                        st.session_state["main_tab"] = "🛠️ Editor"

                        # upload_key erhöhen -> Kamera-Widget wird zurückgesetzt
                        st.session_state.upload_key = (
                            st.session_state.get("upload_key", 0) + 1
                        )
                        st.sidebar.success("Foto aufgenommen & gespeichert.")
                        safe_rerun()
                    except Exception as ex:
                        st.sidebar.error(f"Foto konnte nicht gespeichert werden: {ex}")

        # ==============================================================
        # Variante 3: Video mit Kamera aufnehmen
        # ==============================================================
        elif source_mode == "Kamera (Video aufnehmen)":
            st.sidebar.caption(
                "🎬 Video direkt mit der Kamera aufnehmen."
            )

            # Verfügbare Fehlerbilder für die Video-Zuordnung
            idx_for_video = load_index_v2(paths["index"])
            imgs_this_audit = [
                r for r in idx_for_video.get("images", [])
                if r.get("audit_id") == current_audit_id
            ]
            nr_options = [r.get("nr") for r in imgs_this_audit]
            video_target_nr = None

            if nr_options:
                video_target_nr = st.sidebar.selectbox(
                    "📌 Video zuordnen zu Fehlerbild",
                    options=["— später zuordnen —"] + nr_options,
                    index=0,
                    help="Wähle ein Fehlerbild, dem das Video zugeordnet werden soll.",
                    key="camera_video_target_nr",
                )
                if video_target_nr == "— später zuordnen —":
                    video_target_nr = None
            else:
                st.sidebar.info(
                    "Noch keine Fehlerbilder vorhanden. Video kann später zugeordnet werden."
                )
            st.sidebar.markdown("---")
            # Single file uploader: auf Mobilgeräten öffnet sich hier in der
            # Regel die Kamera-App für Video-Aufnahmen.
            camera_video = st.sidebar.file_uploader(
                "🎥 Video aufnehmen / auswählen",
                type=["mp4", "mov", "avi", "mkv", "webm"],
                accept_multiple_files=False,
                key=f"camera_video_input_{st.session_state.get('upload_key', 0)}",
                help=(
                    "Auf Mobilgeräten öffnet sich die Kamera. "
                    "Am PC kannst du eine vorhandene Videodatei auswählen."
                ),
            )
            # Video-Vorschau & Speichern
            if camera_video is not None:
                st.sidebar.video(camera_video)

                if st.sidebar.button(
                    "✅ Video speichern",
                    use_container_width=True,
                    key="btn_save_camera_video",
                    type="primary",
                ):
                    try:
                        idx2 = load_index_v2(paths["index"])
                        ensure_media_dirs()

                        video_bytes = camera_video.read()
                        video_ref = attach_media(
                            uploaded_bytes=video_bytes,
                            uploaded_filename=camera_video.name,
                            media_type="video",
                        )  # returns "base_videos/....ext"

                        if not video_ref:
                            st.sidebar.error("Video konnte nicht gespeichert werden (attach_media fehlgeschlagen).")
                            safe_rerun()

                        # Optional: direkt einem Fehlerbild zuordnen
                        if video_target_nr:
                            for rec in idx2.get("images", []):
                                if rec.get("audit_id") == current_audit_id and rec.get("nr") == video_target_nr:
                                    rec.setdefault("videos", [])
                                    if video_ref not in rec["videos"]:
                                        rec["videos"].append(video_ref)
                                    break
                            st.sidebar.success(f"✅ Video gespeichert und Fehlerbild {video_target_nr} zugeordnet.")
                        else:
                            # Falls du – wie bisher – späteres Zuordnen nutzt:
                            st.session_state.setdefault("video_attach_candidates", [])
                            st.session_state["video_attach_candidates"].append(video_ref)
                            st.sidebar.success("✅ Video gespeichert. Kann im Tab '🎬 Referenz' zugeordnet werden.")
                            st.session_state["main_tab"] = "🎬 Referenz"

                        save_index_v2(paths["index"], idx2)

                        # reset uploader
                        st.session_state.upload_key = st.session_state.get("upload_key", 0) + 1
                        safe_rerun()

                    except Exception as ex:
                        st.sidebar.error(f"Fehler beim Speichern: {ex}")

            st.sidebar.markdown("---")

    st.sidebar.header("")
    if st.session_state.get("current_audit_id"):
        pass
    
    # -------------------------------------------------------------------------
    # Sidebar: zurück zu Projekten
    # -------------------------------------------------------------------------
    if st.sidebar.button("↩ Zurück zu Projekten", use_container_width=True):
        st.session_state.mode = "landing"
        st.session_state.paths = None
        st.session_state["scroll_to_top"] = True
        safe_rerun()

    # -------------------------------------------------------------------------
    # MAIN: Projekt-UI
    # -------------------------------------------------------------------------
    project_main_ui()