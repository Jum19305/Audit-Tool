# editor.py
import os
import math
from datetime import date, datetime
import numpy as np
import streamlit as st
from PIL import Image, ImageDraw
from streamlit_drawable_canvas import st_canvas
from typing import List, Optional

from common import (
    PROJECTS_ROOT, PRIORITY_OPTIONS, BI_CATEGORIES, QZ_OPTIONS, FEHLERART_OPTIONS, 
    project_paths_v2, load_index_v2, save_index_v2, create_audit, audit_paths, 
    init_project_v2, decode_upload_to_pil, ensure_new_fields, attach_context_images, 
    detach_context_image, save_annotated_as_edited, sanitize_filename, ensure_dirs_exist,
    attach_additional_images, detach_additional_image, clone_image_to_audit, get_videos_for_record,
    save_video_file, index_prefers_relative, link_existing_video_to_record,
    reindex_audit_images, resolve_media_path, is_overlay_ref, delete_global_media,
    get_display_name_for_record, composite_base_with_overlay,
    save_canvas_overlay, save_base_image, fehlerbild_sort_key,
    OVERLAY_KONTEXT, OVERLAY_ZUSATZ_FEHLER, OVERLAY_NACHARBEIT, OVERLAY_ZUSATZ_NACHARBEIT,
    VEHICLE_AREA_OPTIONS, VEHICLE_AREA_LABELS, SYSTEM_DOMAIN_OPTIONS, SYSTEM_DOMAIN_LABELS,
    SORTING_MODE_OPTIONS, SORT_ORDER_BI,
)
from export import build_pdf_with_modes, select_images

from inhaltsangabe_visualization import (
    render_inhaltsangabe_tab,
    get_all_areas,
    get_all_systems,
    render_area_badges,
    render_system_badges,
    render_badge_legend,
    has_nacharbeit_info,
    render_nacharbeit_info_icon,
)
from media_store import(
    to_abs_path, to_rel_path, downscale_to_width, is_media_shared,
)


#------------------------------------------------------------------------------
# Helper for rerun
#------------------------------------------------------------------------------
def safe_rerun() -> None:
    """Trigger a Streamlit rerun; fall back to experimental_rerun on older versions."""
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()

# -----------------------------------------------------------------------------
# UI Styling – Roding Grün & schwarze Titel
# -----------------------------------------------------------------------------
RODING_GREEN_HEX = "#00ccb8"

PRIMARY_CSS = f"""
<style>
:root {{
    --primary-color: {RODING_GREEN_HEX};
}}
/* Primärbuttons */
div.stButton > button:first-child {{
    background-color: {RODING_GREEN_HEX} !important;
    color: #ffffff !important;
    border: 0;
}}
div[data-testid="stSidebar"] div.stButton > button:first-child {{
    background-color: {RODING_GREEN_HEX} !important;
    color: #ffffff !important;
    border: 0;
}}
/* Checkboxen, Radio, Slider Akzent */
input[type="checkbox"], input[type="radio"] {{
    accent-color: {RODING_GREEN_HEX} !important;
}}
[data-baseweb="slider"] div:nth-child(2) > div {{
    background-color: {RODING_GREEN_HEX} !important;
}}
/* Select / Multiselect Caret */
div[data-baseweb="select"] svg {{
    color: {RODING_GREEN_HEX};
}}
/* Einheitliche, große, fette, schwarze Frame-Titel */
.frame-title {{
    font-weight: 800;
    color: #000000;
    font-size: 1.35rem;
    margin-top: 0.25rem;
    margin-bottom: 0.5rem;
}}
/* Dünnere Trennlinie */
hr {{
    border: none;
    height: 1px;
    background: #e2e2e2;
}}
</style>
"""
# -----------------------------------------------------------------------------
# Canvas Tool Configuration
# -----------------------------------------------------------------------------
DRAWING_MODES = {
    "Freihand": "freedraw",
    "Linie": "line",
    "Rechteck": "rect",
    "Kreis": "circle",
    "Pfeil": "arrow"
}

PREDEFINED_COLORS = {
    "Roding Grün": "#00ccb8",
    "Rot": "#FF0000",
    "Gelb": "#FFFF00",
    "Blau": "#0000FF",
    "Orange": "#FFA500",
    "Magenta": "#FF00FF",
    "Cyan": "#00FFFF",
    "Schwarz": "#000000",
    "Weiß": "#FFFFFF"
}

# -----------------------------------------------------------------------------
# Session State Initialization for Canvas Tools
# -----------------------------------------------------------------------------
def init_canvas_session_state():
    """Initialize session state for canvas tools if not exists"""
    if "canvas_stroke_color" not in st.session_state:
        st.session_state.canvas_stroke_color = RODING_GREEN_HEX
    if "canvas_fill_color" not in st.session_state:
        st.session_state.canvas_fill_color = "rgba(0,204,184,0.3)"
    if "canvas_drawing_mode" not in st.session_state:
        st.session_state.canvas_drawing_mode = "freedraw"

# -----------------------------------------------------------------------------
# Canvas Tools Widget
# -----------------------------------------------------------------------------
def render_canvas_tools(key_prefix: str = "main"):
    """Render a toolbar for canvas drawing tools"""
    init_canvas_session_state()
    
    st.markdown("#### 🎨 Zeichenwerkzeuge")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Drawing mode selection
        mode_label = st.selectbox(
            "Werkzeug",
            options=list(DRAWING_MODES.keys()),
            index=list(DRAWING_MODES.values()).index(st.session_state.canvas_drawing_mode) 
                if st.session_state.canvas_drawing_mode in DRAWING_MODES.values() else 0,
            key=f"{key_prefix}_drawing_mode_select"
        )
        st.session_state.canvas_drawing_mode = DRAWING_MODES[mode_label]
        
        # Stroke width
        st.session_state.stroke_width = st.slider(
            "Strichstärke",
            min_value=1,
            max_value=20,
            value=st.session_state.stroke_width,
            key=f"{key_prefix}_stroke_width"
        )
    
    with col2:
        # Color selection
        color_name = st.selectbox(
            "Strichfarbe",
            options=list(PREDEFINED_COLORS.keys()),
            index=list(PREDEFINED_COLORS.values()).index(st.session_state.canvas_stroke_color)
                if st.session_state.canvas_stroke_color in PREDEFINED_COLORS.values() else 0,
            key=f"{key_prefix}_stroke_color_select"
        )
        st.session_state.canvas_stroke_color = PREDEFINED_COLORS[color_name]
        
        # Custom color picker
        custom_color = st.color_picker(
            "Benutzerdefinierte Farbe",
            value=st.session_state.canvas_stroke_color,
            key=f"{key_prefix}_custom_color"
        )
        if custom_color != st.session_state.canvas_stroke_color:
            st.session_state.canvas_stroke_color = custom_color
        
        # Update fill color with transparency
        rgb = custom_color.lstrip('#')
        r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
        st.session_state.canvas_fill_color = f"rgba({r},{g},{b},0.3)"
    
    st.caption(
        "💡 **Tipp:** Wähle ein Werkzeug und zeichne direkt auf dem Bild. "
        "Freihand für flexible Markierungen, geometrische Formen für präzise Hervorhebungen."
    )
def draw_arrow_on_canvas(canvas_result, background_image, stroke_color, stroke_width):
    """
    Convert line drawings to arrows by adding arrowheads.
    This post-processes the canvas output when arrow mode is active.
    
    LAYERED ARCHITECTURE: Creates a transparent overlay with arrows only,
    NOT a baked composite with the background.
    """
    if canvas_result is None or canvas_result.json_data is None:
        return None
    
    json_data = canvas_result.json_data
    if not json_data or "objects" not in json_data:
        return None
    
    # LAYERED: Create a TRANSPARENT overlay
    result_img = Image.new("RGBA", background_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(result_img)
    
    # Process each object
    for obj in json_data["objects"]:
        if obj.get("type") == "line":
            # Extract line coordinates with proper scaling
            # Get the transformation values
            left = obj.get("left", 0)
            top = obj.get("top", 0)
            scale_x = obj.get("scaleX", 1)
            scale_y = obj.get("scaleY", 1)
            
            # Calculate actual coordinates
            x1 = left + obj.get("x1", 0) * scale_x
            y1 = top + obj.get("y1", 0) * scale_y
            x2 = left + obj.get("x2", 0) * scale_x
            y2 = top + obj.get("y2", 0) * scale_y
            
            # Parse color - need RGBA with full opacity for the stroke
            stroke = obj.get("stroke", stroke_color)
            if stroke.startswith("#"):
                color = tuple(int(stroke[i:i+2], 16) for i in (1, 3, 5)) + (255,)  # Add alpha
            else:
                color = (0, 204, 184, 255)  # Default Roding Green with alpha
            
            width = int(obj.get("strokeWidth", stroke_width))
            
            # Calculate arrow properties
            dx = x2 - x1
            dy = y2 - y1
            length = math.sqrt(dx**2 + dy**2)
            
            # Skip if line is too short
            if length < 1:
                continue
            
            # Normalize direction
            dx_norm = dx / length
            dy_norm = dy / length
            
            # Arrow dimensions (scale with line width)
            arrow_length = max(width * 2.5, 15)
            arrow_width = max(width * 1.5, 8)
            
            # Calculate arrowhead base point (slightly before the end point)
            base_x = x2 - arrow_length * dx_norm
            base_y = y2 - arrow_length * dy_norm

            # Draw the main line 
            draw.line([(x1, y1), (base_x, base_y)], fill=color, width=width)
            
            # Calculate perpendicular vector for arrow wings
            perp_x = -dy_norm
            perp_y = dx_norm
            
            # Arrowhead wing points
            left_x = base_x + arrow_width * perp_x
            left_y = base_y + arrow_width * perp_y
            right_x = base_x - arrow_width * perp_x
            right_y = base_y - arrow_width * perp_y
            
            # Draw arrowhead as filled triangle (smooth edges)
            draw.polygon(
                [(x2, y2), (left_x, left_y), (right_x, right_y)],
                fill=color,
                outline=color
            )
    
    return result_img

# -----------------------------------------------------------------------------
# Canvas Renderer
# -----------------------------------------------------------------------------
def render_enhanced_canvas(
    background_image: Image.Image,
    canvas_key: str,
    form_key: str,
    on_save_callback=None,
    on_clear_callback=None,
    tool_key_prefix: str = "main"
):
    """
    Render an enhanced canvas with tools and form buttons
    
    Args:
        background_image: PIL Image to use as background
        canvas_key: Unique key for the canvas component
        form_key: Unique key for the form
        on_save_callback: Function to call when save button is pressed
        on_clear_callback: Function to call when clear button is pressed
        tool_key_prefix: Prefix for tool widget keys
    """
    init_canvas_session_state()
    render_canvas_tools(key_prefix=tool_key_prefix)
    
    st.markdown("---")

    current_mode = st.session_state.canvas_drawing_mode
    canvas_mode = "line" if current_mode == "arrow" else current_mode

    if current_mode == "arrow":
        st.info("🎯 Pfeil-Modus: Ziehe eine Linie - sie wird automatisch mit Pfeilspitze gespeichert")
    
    with st.form(key=form_key):
        canvas = st_canvas(
            fill_color=st.session_state.canvas_fill_color,
            stroke_width=st.session_state.stroke_width,
            stroke_color=st.session_state.canvas_stroke_color,
            background_image=background_image,
            update_streamlit=True,
            height=background_image.height,
            width=background_image.width,
            drawing_mode=canvas_mode if st.session_state.marking_active else None,
            key=canvas_key,
        )
        
        cA, cB = st.columns(2)
        save_btn = cA.form_submit_button("💾 Markierung speichern")
        clear_btn = cB.form_submit_button("🧹 Markierung entfernen")
    
    if save_btn and canvas is not None and canvas.image_data is not None:
        arr = np.asarray(canvas.image_data).astype("uint8")
        if arr.std() > 0 and arr[..., 3].max() > 0:
            # If arrow mode, post-process to add arrowheads
            if current_mode == "arrow":
                try:
                    arrow_img = draw_arrow_on_canvas(
                        canvas, 
                        background_image,
                        st.session_state.canvas_stroke_color,
                        st.session_state.stroke_width
                    )
                    if arrow_img is not None:
                        # LAYERED: arrow_img is already a transparent overlay
                        if on_save_callback:
                            on_save_callback(arrow_img)
                    else:
                        # Fallback to regular save
                        overlay = Image.fromarray(arr, "RGBA")
                        if on_save_callback:
                            on_save_callback(overlay)
                except Exception:
                    # Fallback to regular save on error
                    overlay = Image.fromarray(arr, "RGBA")
                    if on_save_callback:
                        on_save_callback(overlay)
            else:
                # Regular mode
                overlay = Image.fromarray(arr, "RGBA")
                if on_save_callback:
                    on_save_callback(overlay)

    if clear_btn:
        if on_clear_callback:
            on_clear_callback()
    
    return canvas

# -----------------------------------------------------------------------------
# Thumbnail-Helfer 
# -----------------------------------------------------------------------------
def _thumb_for_image(path_abs: str, max_h: int = 120):
    """
    Öffnet ein Bild, skaliert es auf eine feste Höhe (max_h) bei proportionaler Breite,
    und liefert ein PIL-Image für st.image().
    """
    try:
        with Image.open(path_abs) as im:
            im = im.convert("RGB")
            w, h = im.size
            if h <= 0:
                return im
            scale = max_h / float(h)
            new_w = int(round(w * scale))
            im = im.resize((new_w, max_h), Image.LANCZOS)
            return im
    except Exception:
        return None

def _banner_thumbnails(paths_abs: list, key_prefix: str, per_row: int = 6, thumb_h: int = 120):
    """
    Zeigt einen horizontalen Thumbnail-Banner (mehrere Reihen). Alle Thumbs haben gleiche Höhe.
    Gibt den ausgewählten Index (int) oder None zurück.
    """
    if not paths_abs:
        st.info("Keine Zusatzbilder vorhanden.")
        return None

    selected = st.session_state.get(f"{key_prefix}_sel", None)
    rows = [paths_abs[i:i + per_row] for i in range(0, len(paths_abs), per_row)]
    row_idx_base = 0
    for row in rows:
        cols = st.columns(len(row))
        for j, p_abs in enumerate(row):
            with cols[j]:
                thumb = _thumb_for_image(p_abs, max_h=thumb_h)
                if thumb is not None:
                    st.image(thumb, use_column_width=False)
                lbl = os.path.basename(p_abs)
                if st.button(f"Auswählen: {lbl}", key=f"{key_prefix}_pick_{row_idx_base + j}"):
                    st.session_state[f"{key_prefix}_sel"] = row_idx_base + j
                    selected = row_idx_base + j
        row_idx_base += len(row)

    return selected
# -------------------------------------------------------------------------
# RAW-Bild Auswahl für interne Audits (Hauptbild ersetzen/entfernen)
# -------------------------------------------------------------------------
def _list_audit_raw_files(a_paths: dict) -> list:
    """List all image files in the RAW folder of current audit."""
    raw_dir = a_paths.get("raw")
    ensure_dirs_exist(raw_dir)
    files = []
    if raw_dir and os.path.isdir(raw_dir):
        for fn in sorted(os.listdir(raw_dir)):
            ext = os.path.splitext(fn.lower())[1]
            if ext in (".jpg", ".jpeg", ".png", ".heic"):
                files.append(os.path.join(raw_dir, fn))
    return files

def _raw_picker_for_main_image(rec: dict, paths: dict, a_paths: dict, idx: dict) -> None:
    """
    Für interne Audits: RAW-Bild aus dem Audit-Ordner auswählen oder
    die Verknüpfung zum Fehlerbild lösen.

    LAYERED ARCHITECTURE:

    - 'RAW verwenden':
        * rec['base_image'] wird auf die gewählte globale RAW-Datei gesetzt
            (Referenz in base_images/*).
        * rec['raw'] wird aus Kompatibilitätsgründen ebenfalls auf diese
            Referenz gesetzt (legacy-Feld).
        * vorhandenes Overlay (rec['overlay'] / rec['edited']) wird gelöscht,
            damit die Markierung zum neuen Bild passt.
    - 'Verknüpfung entfernen':
        * rec['base_image'], rec['raw'] sowie Overlay-Felder werden geleert.
        * Basisdatei im globalen Store bleibt erhalten.
    """
    raw_files = _list_audit_raw_files(a_paths)
    if not raw_files:
        st.info("Im RAW-Ordner dieses Audits sind aktuell keine Bilder vorhanden.")
        return

    labels = [os.path.basename(p) for p in raw_files]

    # Aktuell verknüpftes RAW (falls vorhanden) als Default-Auswahl
    current_raw_ref = rec.get("base_image") or rec.get("raw")
    current_raw_abs = to_abs_path(current_raw_ref, {"root": paths["root"]}) if current_raw_ref else None
    try:
        default_index = raw_files.index(current_raw_abs) if current_raw_abs in raw_files else 0
    except ValueError:
        default_index = 0

    sel = st.selectbox(
        "RAW-Datei im Audit-Ordner",
        options=list(range(len(raw_files))),
        format_func=lambda i: labels[i],
        index=default_index,
        key=f"raw_picker_{st.session_state.current_idx}",
    )
    col1, col2 = st.columns(2)

    # --- RAW-Bild zuweisen ---
    if col1.button(
        "🔁 Dieses RAW als Fehlerbild verwenden",
        use_container_width=True,
        key=f"btn_assign_raw_{st.session_state.current_idx}",
    ):
        chosen_abs = raw_files[sel]

        # Globale Referenz für das Basisbild bestimmen (base_images/<filename>)
        filename = os.path.basename(chosen_abs)
        base_ref = f"base_images/{filename}"

        # Altes Overlay löschen, falls es ein Canvas-Overlay ist
        old_overlay_ref = rec.get("overlay") or rec.get("edited")
        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
            delete_global_media(old_overlay_ref)

        # LAYERED: neues Basisbild setzen, legacy-Felder ebenfalls aktualisieren
        rec["base_image"] = base_ref
        rec["raw"] = base_ref 
        rec["overlay"] = None
        rec["edited"] = None

        save_index_v2(paths["index"], idx)
        st.success("RAW-Bild wurde mit dem Fehlerbild verknüpft.")
        st.session_state.canvas_ver += 1
        safe_rerun()

    # --- Verknüpfung lösen (ohne Basisdatei zu löschen) ----------------
    if col2.button(
        "🔌 Bild-Verknüpfung entfernen (Dateien bleiben im RAW-Ordner)",
        use_container_width=True,
        key=f"btn_detach_raw_{st.session_state.current_idx}",
    ):
        # Overlay-Datei ggf. löschen (nur, wenn es wirklich ein Overlay ist)
        old_overlay_ref = rec.get("overlay") or rec.get("edited")
        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
            delete_global_media(old_overlay_ref)

        # Verknüpfung entfernen – Basisdatei bleibt im globalen Store
        rec["base_image"] = None
        rec["raw"] = None
        rec["overlay"] = None
        rec["edited"] = None
        save_index_v2(paths["index"], idx)
        st.success("Fehlerbild wurde von seinem Bild getrennt. Du kannst später wieder ein RAW-Bild zuweisen.")
        st.session_state.canvas_ver += 1
        safe_rerun()

# -----------------------------------------------------------------------------
# Projektliste
# -----------------------------------------------------------------------------
def list_existing_projects_v2():
    os.makedirs(PROJECTS_ROOT, exist_ok=True)
    projects = []
    for name in sorted(os.listdir(PROJECTS_ROOT)):
        p = os.path.join(PROJECTS_ROOT, name)
        idx_path = os.path.join(p, "index.json")
        if os.path.isdir(p) and os.path.exists(idx_path):
            try:
                data = load_index_v2(idx_path)
                projects.append({
                    "project_id": name,
                    "path": p,
                    "index": idx_path,
                    "vehicle": data.get("project", {}).get("vehicle", ""),
                    "audits_n": len(data.get("audits", [])),
                    "images_n": len(data.get("images", [])),
                })
            except Exception:
                pass
    return projects

# -----------------------------------------------------------------------------
# Landing-Page
# -----------------------------------------------------------------------------
def landing_page():
    from common import resolve_wiigor_logo, ASSETS_DIR, BASE_DIR
    from PIL import Image

    st.markdown(PRIMARY_CSS, unsafe_allow_html=True)

    # Branding ohne "Audits"
    st.title("WiiGoR")
    st.caption("When is it Good or Right")

    logo_path = resolve_wiigor_logo()
    if logo_path:
        try:
            img = Image.open(logo_path)
            col_l, col_c, col_r = st.columns([1, 2, 1])
            with col_c:
                st.image(img, use_column_width=True, caption=None)

        except Exception as ex:
            # Falls Datei kein gültiges Bild ist oder sonst etwas schiefgeht
            st.error(f"Logo konnte nicht geladen werden: {ex}")
    else:
        st.info("Logo nicht gefunden. Siehe Debug-Box für Details.")


    # -------------Projekte laden-----------------------
    try:
        projects = list_existing_projects_v2()
    except Exception as ex:
        st.error(f"Fehler beim Laden der Projekte: {ex}")
        projects = []

    project_ids = [p["project_id"] for p in projects]

    if "landing_selected_project_id" not in st.session_state and project_ids:
        st.session_state["landing_selected_project_id"] = project_ids[0]

    st.subheader("Bestehende Projekte")

    # ------------Audit wählen-------------------------
    with st.expander("🔁 Audit wählen (für gewähltes Projekt)", expanded=True):
        if not projects:
            st.info("Bitte oben ein Projekt anlegen.")
        else:
            proj_pid_choice = st.selectbox(
                "Projekt (für Audit‑Wahl)",
                project_ids,
                index=(project_ids.index(st.session_state["landing_selected_project_id"])
                    if st.session_state.get("landing_selected_project_id") in project_ids else 0),
                key="landing_proj_for_audit_pid"
            )
            paths_sel = project_paths_v2(proj_pid_choice)
            idx_sel = load_index_v2(paths_sel["index"])
            audits = idx_sel.get("audits", []) or []
            if not audits:
                st.info("Dieses Projekt enthält noch keine Audits. Lege unten ein Audit an.")
            else:
                show_all = st.checkbox("Alle Audits anzeigen (ohne Filter)", value=True,
                                        key=f"lp_show_all__{proj_pid_choice}")
                items = audits
                if not show_all:
                    by_scope = {}
                    for a in audits:
                        scope = a.get("scope", "Internes Audit") or "Internes Audit"
                        year = (a.get("date", "") or "")[0:4] or "Unbekannt"
                        by_scope.setdefault(scope, {}).setdefault(year, []).append(a)
                    scopes = [s for s in ["Internes Audit", "Kundenaudit"] if s in by_scope] + \
                            [s for s in sorted(by_scope.keys()) if s not in ("Internes Audit", "Kundenaudit")]
                    scope_sel = st.selectbox("Scope", scopes, index=0, key=f"lp_scope_sel__{proj_pid_choice}")
                    years = sorted(by_scope[scope_sel].keys(), reverse=True)
                    year_sel = st.selectbox("Jahr", years, index=0, key=f"lp_year_sel__{proj_pid_choice}")
                    items = sorted(by_scope[scope_sel][year_sel], key=lambda k: k.get("date", ""), reverse=True)
                else:
                    items = sorted(items, key=lambda k: (k.get("date", ""), k.get("type", "")), reverse=True)

                labels_a = [f"{a.get('date','')} · {a.get('type','')} · {a.get('auditor','')}" for a in items]
                if labels_a:
                    choice = st.radio(
                        "Audit",
                        labels_a,
                        index=0,
                        key=f"lp_audit_radio__{proj_pid_choice}__{show_all}"
                    )
                    pick_a = items[labels_a.index(choice)]
                    if st.button(
                        "➡ Mit Audit öffnen",
                        type="primary",
                        use_container_width=True,
                        key=f"open_with_audit__{proj_pid_choice}",
                    ):
                        st.session_state.paths = paths_sel
                        st.session_state.mode = "project"
                        st.session_state.current_idx = 0
                        st.session_state.canvas_ver = 0
                        st.session_state.current_audit_id = pick_a["audit_id"]
                        st.session_state["main_tab"] = "🛠️ Editor"
                        st.session_state["last_audit_id"] = pick_a["audit_id"]
                        st.session_state["scroll_to_top"] = True
                        st.success(f"Audit gesetzt: {pick_a['audit_id']}")
                        safe_rerun()
                else:
                    st.caption("Keine Audits in dieser Auswahl.")

    # ---------------------Audit anlegen-------------------------
    with st.expander("➕ Audit anlegen (für bestehendes Projekt)", expanded=False):
        if not projects:
            st.info("Lege zuerst ein Projekt an.")
        else:
            proj_pid = st.selectbox(
                "Projekt wählen",
                project_ids,
                index=(project_ids.index(st.session_state["landing_selected_project_id"])
                    if st.session_state.get("landing_selected_project_id") in project_ids else 0),
                key="landing_new_audit_project_id"
            )
            d = st.date_input("Datum", value=date.today(), key=f"landing_new_audit_date__{proj_pid}", format="DD/MM/YYYY")
            t = st.text_input("Audit‑Typ (frei)", key=f"landing_new_audit_type__{proj_pid}")
            aud = st.text_input("Auditor (frei)", key=f"landing_new_audit_auditor__{proj_pid}")
            scope = st.radio("Art des Audits", ["Internes Audit","Kundenaudit"], index=0,
                            horizontal=True, key=f"landing_new_audit_scope__{proj_pid}")
            notes = st.text_area("Notizen", height=60, key=f"landing_new_audit_notes__{proj_pid}")
            if st.button("➕ Audit erstellen", type="primary", key=f"btn_new_audit__{proj_pid}"):
                try:
                    paths_sel = project_paths_v2(proj_pid)
                    idx_sel = load_index_v2(paths_sel["index"])
                    a = create_audit(idx_sel, paths_sel, d, t or "Audit", aud or "", scope, notes)
                    save_index_v2(paths_sel["index"], idx_sel)

                    st.session_state.paths = paths_sel
                    st.session_state.mode = "project"
                    st.session_state.current_audit_id = a["audit_id"]
                    st.session_state["landing_selected_project_id"] = proj_pid
                    st.session_state["main_tab"] = "🛠️ Editor"
                    st.session_state["last_audit_id"] = a["audit_id"]
                    st.session_state["scroll_to_top"] = True
                    st.success(f"Audit '{a['audit_id']}' angelegt.")
                    safe_rerun()
                except Exception as ex:
                    st.error(f"Audit konnte nicht angelegt werden: {ex}")
    st.markdown("---")

    # --------------------Neues Projekt anlegen---------------------------------
    st.subheader("Neues Projekt")

    project_id = st.text_input("Projekt-ID (frei, z. B. 'VIN_WBS123...')")
    vehicle = st.text_input("Bezeichnung Fahrzeug/Artikel")

    if st.button("🚀 Projekt anlegen", type="primary"):
        if not project_id or not vehicle:
            st.error("Bitte **Projekt-ID** und **Fahrzeug/Artikel** angeben.")
        else:
            try:
                # Neues Projekt anlegen (common.init_project_v2 gibt Pfade zurück)
                paths = init_project_v2(project_id, vehicle)

                st.session_state.paths = paths
                st.session_state.mode = "project"
                st.session_state.current_idx = 0
                st.session_state.canvas_ver = 0
                st.session_state.current_audit_id = None
                st.session_state["landing_selected_project_id"] = project_id
                st.session_state["scroll_to_top"] = True
                st.success(f"Projekt '{project_id}' wurde angelegt.")
                safe_rerun()
            except Exception as ex:
                st.error(f"Projekt konnte nicht angelegt werden: {ex}")
    st.markdown("---")

    # ---------------Bestehendes Projekt: Bezeichnung ändern-----------------------
    st.subheader("Projekt-Bezeichnung bearbeiten")

    if not projects:
        st.info("Es sind noch keine Projekte vorhanden. Lege zuerst ein Projekt an.")
    else:
        proj_edit_id = st.selectbox(
            "Projekt auswählen",
            [p["project_id"] for p in projects],
            index=(
                [p["project_id"] for p in projects].index(st.session_state.get("landing_selected_project_id"))
                if st.session_state.get("landing_selected_project_id") in [p["project_id"] for p in projects]
                else 0
            ),
            key="edit_project_select",
        )

        edit_paths = project_paths_v2(proj_edit_id)
        edit_idx = load_index_v2(edit_paths["index"])
        edit_proj = edit_idx.get("project", {}) or {}

        st.text_input(
            "Projekt-ID (nicht änderbar)",
            value=edit_proj.get("project_id", proj_edit_id),
            disabled=True,
            key="edit_project_id_display",
        )

        new_vehicle = st.text_input(
            "Bezeichnung Fahrzeug/Artikel",
            value=edit_proj.get("vehicle", ""),
            key="edit_project_vehicle",
        )

        if st.button("💾 Bezeichnung speichern", key="save_project_edit"):
            try:
                edit_proj["vehicle"] = new_vehicle
                edit_idx["project"] = edit_proj
                save_index_v2(edit_paths["index"], edit_idx)
                st.session_state["landing_selected_project_id"] = proj_edit_id
                st.success("Projekt-Bezeichnung wurde aktualisiert.")
                safe_rerun()
            except Exception as ex:
                st.error(f"Fehler beim Aktualisieren der Projekt-Bezeichnung: {ex}")

    st.markdown("---")
    st.subheader("RQM‑Nacharbeiten – Übersicht über alle Projekte")
    st.caption("Öffne ein Projekt (und wähle ein Audit), um die detaillierte Nacharbeitsliste zu sehen.")

# -----------------------------------------------------------------------------
# Haupt-UI
# -----------------------------------------------------------------------------
def project_main_ui():
    """Main project UI with enhanced canvas tools"""
    st.markdown(PRIMARY_CSS, unsafe_allow_html=True)

    paths = st.session_state.paths
    idx = load_index_v2(paths["index"])

    # Project header
    project_info = idx.get("project", {}) or {}
    project_name = project_info.get("vehicle", "")
    project_desc = project_info.get("project_id", os.path.basename(paths["root"]))

    st.markdown(f"### {project_name}")
    if project_desc:
        st.caption(project_desc)
    st.caption("When is it Good or Right")

    # Audit info
    audits = idx.get("audits", [])
    active_audit = st.session_state.get("current_audit_id")
    # --- BEGIN INSERT: attach dialog overlay for pending sidebar videos ---
    pending = st.session_state.get("video_attach_candidates") or []
    show_dialog = bool(st.session_state.get("show_video_attach_dialog")) and bool(pending)

    # Check if there are Fehlerbilder available for the active audit
    images_for_dialog = [r for r in idx.get("images", []) if r.get("audit_id") == active_audit] if active_audit else []
    nr_options_for_dialog = [r.get("nr") for r in images_for_dialog]

    # If no Fehlerbilder exist, don't show blocking dialog - just show info message
    if show_dialog and not nr_options_for_dialog:
        st.info(
            "📹 **Videos wurden hochgeladen**, können aber noch keinem Fehlerbild zugeordnet werden, "
            "da noch keine Fehlerbilder vorhanden sind. Bitte zuerst ein Fehlerbild erstellen, "
            "dann können die Videos im Tab '🎬 Referenz' zugeordnet werden."
        )
        # Clear the dialog flag so it doesn't keep showing as blocking
        st.session_state["show_video_attach_dialog"] = False
        # Keep video_attach_candidates so user can assign them later in Referenz tab
        show_dialog = False

    if show_dialog:
        # Use expander instead of blocking overlay for better UX
        with st.expander("🎬 Videos zuordnen", expanded=True):
            st.markdown("Die folgenden Videos wurden hochgeladen. Bitte wähle ein Fehlerbild zur Zuordnung.")
            
            with st.form("video_attach_form"):
                # Fehlerbilder in aktivem Audit
                chosen_nr = st.selectbox("Fehlerbild (Nr) wählen", nr_options_for_dialog, key="attach_pick_nr")

                # list of pending videos (just show basenames)
                nice_labels = [os.path.basename(p) for p in pending]
                sel_videos = st.multiselect(
                    "Zuordnen (Videos)",
                    options=list(range(len(pending))),
                    format_func=lambda i: nice_labels[i],
                    default=list(range(len(pending))),
                    key="attach_pick_videos"
                )

                rename_flag = st.checkbox(
                    "Dateien ins Standard-Schema umbenennen (audit__nr__datei.ext)",
                    value=True
                )

                c1, c2 = st.columns(2)
                submit = c1.form_submit_button("✅ Zuordnen & Speichern", use_container_width=True)
                cancel = c2.form_submit_button("Später zuordnen", use_container_width=True)

            if cancel:
                st.session_state["show_video_attach_dialog"] = False
                # Keep video_attach_candidates for later assignment in Referenz tab
                st.info("Du kannst die Videos später im Tab '🎬 Referenz' zuordnen.")
                safe_rerun()

            if submit:
                if not chosen_nr:
                    st.error("Bitte ein Fehlerbild (Nr) auswählen.")
                elif not sel_videos:
                    st.error("Bitte mindestens ein Video auswählen.")
                else:
                    idx2 = load_index_v2(paths["index"])
                    prefer_rel = index_prefers_relative(idx2)
                    linked = 0
                    for i in sel_videos:
                        vabs = pending[i]
                        out = link_existing_video_to_record(
                            video_abs_path=vabs,
                            index=idx2,
                            audit_id=active_audit,
                            project_paths=paths,
                            prefer_relative=prefer_rel,
                            record_nr=chosen_nr,
                            rename_to_canonical=rename_flag,
                        )
                        if out:
                            linked += 1
                    save_index_v2(paths["index"], idx2)
                    st.success(f"{linked} Video(s) zu Fehlerbild {chosen_nr} verknüpft.")
                    st.session_state["video_attach_candidates"] = []
                    st.session_state["show_video_attach_dialog"] = False
                    st.session_state["main_tab"] = "🎬 Referenz"
                    safe_rerun()
    # --- END INSERT ---

    if not active_audit:
        internal = next((a for a in audits if a.get("scope") == "Internes Audit"), None)
        if internal:
            st.session_state.current_audit_id = internal["audit_id"]
            active_audit = internal["audit_id"]
        elif audits:
            active_audit = audits[0]["audit_id"]
            st.session_state.current_audit_id = audits[0]["audit_id"]

    prev_audit = st.session_state.get("last_audit_id")
    if active_audit and prev_audit != active_audit:
        st.session_state["main_tab"] = "🛠️ Editor"
    st.session_state["last_audit_id"] = active_audit
    
    audit_info = next((a for a in audits if a["audit_id"] == active_audit), None)
    audit_name = (audit_info.get("type", "") if audit_info else "") or ""
    audit_scope = (audit_info.get("scope", "") if audit_info else "") or ""

    if audit_name:
        st.markdown(f"**Aktives Audit:** {audit_name} ({audit_scope}) ")

    TAB_EDITOR = "🛠️ Editor"
    TAB_TOC = "📋 Inhaltsangabe"
    TAB_OVERVIEW = "📈 Übersicht"
    TAB_RELEASE = "✅ Release"
    TAB_REFERENCE = "🎬 Referenz"  

    if "main_tab" not in st.session_state:
        st.session_state["main_tab"] = TAB_EDITOR

    col_tab1, col_tab2, col_tab3, col_tab4, col_tab5 = st.columns(5)

    def _tab_button(label: str, tab_const: str, col):
        is_active = (st.session_state["main_tab"] == tab_const)
        btn_label = f"**{label}**" if is_active else label
        if col.button(btn_label, use_container_width=True):
            if st.session_state["main_tab"] != tab_const:
                st.session_state["main_tab"] = tab_const
                st.session_state["scroll_to_top"] = True
            safe_rerun()

    _tab_button(TAB_EDITOR, TAB_EDITOR, col_tab1)
    _tab_button(TAB_TOC, TAB_TOC, col_tab2)
    _tab_button(TAB_OVERVIEW, TAB_OVERVIEW, col_tab3)
    _tab_button(TAB_RELEASE, TAB_RELEASE, col_tab4)
    _tab_button(TAB_REFERENCE, TAB_REFERENCE, col_tab5)
    
    # Editor tab with enhanced canvas
    if st.session_state["main_tab"] == TAB_EDITOR:
        all_images = idx.get("images", [])
        images = [r for r in all_images if r.get("audit_id") == active_audit] if active_audit else []

        if not active_audit:
            st.info("Bitte auf der Landing-Page ein Audit wählen.")
            return

        with st.expander("🔗 Fehlerbilder aus anderem Audit übernehmen", expanded=False):
            # Alle anderen Audits dieses Projekts
            other_audits = [a for a in audits if a.get("audit_id") != active_audit]

            if not other_audits:
                st.caption("In diesem Projekt gibt es keine weiteren Audits als Quelle.")
            else:
                internal_audits = [a for a in other_audits if a.get("scope") == "Internes Audit"]
                source_audits = internal_audits or other_audits
                audit_labels = [
                    f"{a.get('date','')} · {a.get('type','')} · {a.get('scope','')}"
                    for a in source_audits
                ]
                audit_options = list(range(len(source_audits)))
                selected_audit_idx = st.selectbox(
                    "Quell-Audit (z. B. Internes Audit)",
                    options=audit_options,
                    format_func=lambda i: audit_labels[i],
                    key="copy_src_audit",
                )
                src_audit = source_audits[selected_audit_idx]
                src_audit_id = src_audit.get("audit_id")
                src_images = [r for r in all_images if r.get("audit_id") == src_audit_id]

                if not src_images:
                    st.caption("Das ausgewählte Audit enthält noch keine Fehlerbilder.")
                else:
                    img_labels = []
                    for r in src_images:
                        f = r.get("fehler", {}) or {}
                        ort = f.get("Fehlerort", "") or "-"
                        bi = f.get("BI_alt", "") or ""
                        fa = ", ".join(f.get("Fehlerart", []) or [])
                        img_labels.append(
                            f"Nr {r.get('nr','')} · Ort: {ort} · BI: {bi} · Art: {fa}"
                        )

                    img_options = list(range(len(src_images)))
                    selected_img_indices = st.multiselect(
                        "Fehlerbilder auswählen (Mehrfachauswahl möglich)",
                        options=img_options,
                        format_func=lambda i: img_labels[i],
                        key="copy_src_images",
                    )

                    st.markdown(
                        f"*Quelle:* `{src_audit.get('scope','')}` am {src_audit.get('date','')} – "
                        f"Typ: {src_audit.get('type','')}"
                    )

                    disabled = not selected_img_indices
                    if st.button(
                        "➕ Ausgewählte Fehlerbilder in dieses Audit übernehmen",
                        key="btn_clone_images_to_current_audit",
                        use_container_width=True,
                        disabled=disabled,
                    ):
                        new_recs = []
                        for i in selected_img_indices:
                            src_rec = src_images[i]
                            new_rec = clone_image_to_audit(idx, src_rec, active_audit)
                            new_recs.append(new_rec)
                        save_index_v2(paths["index"], idx)

                        images_for_current = [
                            r for r in idx.get("images", [])
                            if r.get("audit_id") == active_audit
                        ]

                        if new_recs:
                            first_new_nr = new_recs[0].get("nr")
                            try:
                                start_idx = next(
                                    j for j, r in enumerate(images_for_current)
                                    if r.get("nr") == first_new_nr
                                )
                            except StopIteration:
                                start_idx = len(images_for_current) - 1
                            st.session_state.current_idx = max(0, start_idx)
                        st.success(f"{len(new_recs)} Fehlerbild(er) übernommen.")
                        safe_rerun()

        # ---------Falls im aktuellen Audit noch keine Bilder sind, Hinweis + Exit-------------
        if not images:
            st.info("Noch keine Bilder im Audit.")
            return

        st.session_state.current_idx = max(0, min(st.session_state.current_idx, len(images) - 1))
        rec = images[st.session_state.current_idx]
        ensure_new_fields(rec)
        a_paths = audit_paths(paths, active_audit)
        project_id = idx.get("project", {}).get("project_id", "PROJ")
        bildname = get_display_name_for_record(rec, project_id)
        st.markdown(f"#### Fehlerbild {st.session_state.current_idx+1}/{len(images)} – Nr {rec['nr']} – {bildname}")

        c1, c2, c3 = st.columns(3)
        if c1.button("↵ Zurück", disabled=st.session_state.current_idx == 0):
            st.session_state.current_idx -= 1
            st.session_state.canvas_ver += 1
            safe_rerun()
        if c2.button("↪ Weiter", disabled=st.session_state.current_idx >= len(images) - 1):
            st.session_state.current_idx += 1
            st.session_state.canvas_ver += 1
            safe_rerun()

        delete_label = "🗑️ Fehlerbildeintrag löschen"
        if rec.get("link_source"):
            delete_label = "🗑️ Verlinktes Fehlerbild im Kundenaudit löschen"

        # Eindeutiger Key für diese Sicherheitsabfrage (pro Audit + Fehlerbild)
        confirm_flag_key = f"confirm_delete_{active_audit}_{rec.get('nr')}"

        # Erster Klick: Sicherheitsabfrage aktivieren
        if c3.button(delete_label, key=f"btn_delete_{active_audit}_{rec.get('nr')}"):
            st.session_state[confirm_flag_key] = True

        # Wenn Sicherheitsabfrage aktiv ist: Warnhinweis + Ja/Nein-Buttons
        if st.session_state.get(confirm_flag_key, False):
            st.warning(
                "⚠️ **Achtung!** Beim Löschen dieses Fehlerbildes werden "
                "**alle Kommentare, Kontextbilder und Zusatzbilder "
                "(Fehlerbild & Nacharbeit)** zu diesem Fehlerbild entfernt. "
                "Diese Aktion kann nicht rückgängig gemacht werden."
            )

            col_conf_yes, col_conf_no = st.columns(2)
            if col_conf_yes.button(
                "✅ Ja, Fehlerbild wirklich löschen",
                key=f"btn_delete_confirm_yes_{active_audit}_{rec.get('nr')}"
            ):

                # Index-Eintrag entfernen (damit sind Metadaten & Kommentare weg)
                try:
                    idx["images"].remove(rec)
                except Exception:
                    pass
                save_index_v2(paths["index"], idx)

                # Navigation korrigieren und neu laden
                if st.session_state.current_idx >= len(images) - 1:
                    st.session_state.current_idx = max(0, len(images) - 2)

                st.session_state[confirm_flag_key] = False

                safe_rerun()

            if col_conf_no.button(
                "❌ Abbrechen",
                key=f"btn_delete_confirm_no_{active_audit}_{rec.get('nr')}"
            ):
                # Sicherheitsabfrage abbrechen
                st.session_state[confirm_flag_key] = False

        # ===== General Fehlerbild Metadata (Top, expanded) =====
        st.markdown('<div class="frame-title">Fehlerbild Allgemeininformationen</div>', unsafe_allow_html=True)
        
        # Create a unique key suffix based on record number to ensure proper field isolation
        rec_nr = rec.get("nr", st.session_state.current_idx)
        field_key_suffix = f"{active_audit}_{rec_nr}"
        
        col_general = st.columns(6)
        with col_general[0]:
            case_status = st.selectbox("Case Status", ["Open", "Closed"],
                                    index=0 if rec["fehler"].get("CaseStatus", "Open") == "Open" else 1,
                                    key=f"case_status_{field_key_suffix}")
        with col_general[1]:
            prioritaet = st.selectbox("Priorität", PRIORITY_OPTIONS,
                                    index=(PRIORITY_OPTIONS.index(rec["fehler"].get("Prioritaet", "Mittel"))
                                            if rec["fehler"].get("Prioritaet", "Mittel") in PRIORITY_OPTIONS else 1),
                                    key=f"prioritaet_{field_key_suffix}")
        with col_general[2]:
            qz_status = st.selectbox("QZ Status", QZ_OPTIONS,
                                    index=(QZ_OPTIONS.index(rec["fehler"].get("QZStatus", "QZS"))
                                            if rec["fehler"].get("QZStatus", "QZS") in QZ_OPTIONS else 0),
                                    key=f"qz_status_{field_key_suffix}")
        with col_general[3]:
            rqm_relevant = st.selectbox("RQM Relevanz", ["Nein", "Ja"],
                                        index=0 if not rec["fehler"].get("RQMRelevant", False) else 1,
                                        key=f"rqm_relevant_{field_key_suffix}")
        with col_general[4]:
            _default_fehlerart = [v for v in rec["fehler"].get("Fehlerart", []) if v in FEHLERART_OPTIONS]
            fehlerart = st.multiselect(
                "Fehlerart",
                FEHLERART_OPTIONS,
                default=_default_fehlerart,
                key=f"fehlerart_{field_key_suffix}",
            )
        with col_general[5]:
            fehlerort = st.text_input("Fehlerort", value=rec["fehler"].get("Fehlerort", ""), key=f"ort_{field_key_suffix}")
        
        # --- Fahrzeugbereich & System/Domäne (jetzt MULTI-SELECT) ---
        col_location = st.columns(2)

        # Fahrzeugbereich (multi)
        with col_location[0]:
            f = rec.setdefault("fehler", {})

            # Bestehende Daten abholen
            existing_multi_areas = f.get("vehicle_area_multi")
            if isinstance(existing_multi_areas, list) and existing_multi_areas:
                default_areas = [a for a in existing_multi_areas if a in VEHICLE_AREA_OPTIONS]
            else:
                default_areas = []

            selected_areas = st.multiselect(
                "Fahrzeugbereich",
                options=VEHICLE_AREA_OPTIONS,
                default=default_areas,
                format_func=lambda x: VEHICLE_AREA_LABELS.get(x, x),
                key=f"vehicle_area_{field_key_suffix}",
            )

            # Alles speichern
            f["vehicle_area_multi"] = selected_areas

            # Primärer Bereich für Sortierung/PDF (kompatibel mit bestehender Logik)
            if selected_areas:
                f["vehicle_area"] = selected_areas[0]
            else:
                # Fallback, falls nichts gewählt wird
                f["vehicle_area"] = None 

        # System/Domäne (multi)
        with col_location[1]:
            f = rec.setdefault("fehler", {})

            existing_multi_domains = f.get("system_domain_multi")
            if isinstance(existing_multi_domains, list) and existing_multi_domains:
                default_domains = [d for d in existing_multi_domains if d in SYSTEM_DOMAIN_OPTIONS]
            else:
                default_domains = []

            selected_domains = st.multiselect(
                "System/Domäne",
                options=SYSTEM_DOMAIN_OPTIONS,
                default=default_domains,
                format_func=lambda x: SYSTEM_DOMAIN_LABELS.get(x, x),
                key=f"system_domain_{field_key_suffix}",
            )

            f["system_domain_multi"] = selected_domains

            # Primäres System für Sortierung/PDF
            if selected_domains:
                f["system_domain"] = selected_domains[0]
            else:
                f["system_domain"] = None


        # ===== Detail / Nacharbeit =====
        colA, colB = st.columns(2)
        with colA:
            st.markdown('<div class="frame-title">Audit</div>', unsafe_allow_html=True)
            st.markdown("&nbsp;", unsafe_allow_html=True)
            bi_alt = st.selectbox("BI (Audit)", BI_CATEGORIES,
                                index=(BI_CATEGORIES.index(rec["fehler"].get("BI_alt", ""))
                                        if rec["fehler"].get("BI_alt", "") in BI_CATEGORIES else 0),
                                key=f"bi_alt_{field_key_suffix}")
            fehlerbeschreibung = st.text_area("Fehlerbeschreibung", value=rec["fehler"].get("Fehlerbeschreibung", ""), height=100,
                                key=f"fehlerbeschreibung_{field_key_suffix}")
            kommentar = st.text_area("Kommentar", value=rec["fehler"].get("Kommentar", ""), height=100,
                                key=f"kommentar_{field_key_suffix}")

        with colB:
            st.markdown('<div class="frame-title">Nacharbeit</div>', unsafe_allow_html=True)
            nacharbeit_done = st.checkbox("Nacharbeit erforderlich?", value=bool(rec["fehler"].get("Nacharbeit_done", False)),
                                        key=f"nacharbeit_done_{field_key_suffix}")
            bi_neu = st.selectbox("BI (Nacharbeit)", BI_CATEGORIES,
                                index=(BI_CATEGORIES.index(rec["fehler"].get("BI_neu", ""))
                                        if rec["fehler"].get("BI_neu", "") in BI_CATEGORIES else 0),
                                disabled=(not nacharbeit_done),
                                key=f"bi_neu_{field_key_suffix}")
            nacharbeitsvorschlag = st.text_area("Nacharbeitsvorschlag",
                                                value=rec["fehler"].get("Nacharbeitsvorschlag", ""),
                                                height=80, disabled=(not nacharbeit_done),
                                                key=f"nacharbeitsvorschlag_{field_key_suffix}")
            kommentar_nacharbeit = st.text_area("Kommentar Nacharbeit",
                                                value=rec["fehler"].get("Kommentar_Nacharbeit", ""),
                                                height=100, disabled=(not nacharbeit_done),
                                                key=f"kommentar_nacharbeit_{field_key_suffix}")

        # ===== Validation for Fehlerbild Allgemeininformationen =====
        missing_fields = []
        
        # Fehlerart - multiselect, must have at least one selection
        current_fehlerart = st.session_state.get(f"fehlerart_{field_key_suffix}", fehlerart)
        if not current_fehlerart or len(current_fehlerart) == 0:
            missing_fields.append("Fehlerart")
        
        # Fehlerort - text input, must not be empty
        current_fehlerort = st.session_state.get(f"ort_{field_key_suffix}", fehlerort)
        if not current_fehlerort or not str(current_fehlerort).strip():
            missing_fields.append("Fehlerort")

        # NEU: Fahrzeugbereich – mindestens eine Auswahl erforderlich
        current_vehicle_areas = st.session_state.get(f"vehicle_area_{field_key_suffix}", [])
        if not current_vehicle_areas or len(current_vehicle_areas) == 0:
            missing_fields.append("Fahrzeugbereich")

        # NEU: System/Domäne – mindestens eine Auswahl erforderlich
        current_system_domains = st.session_state.get(f"system_domain_{field_key_suffix}", [])
        if not current_system_domains or len(current_system_domains) == 0:
            missing_fields.append("System/Domäne")
        
        # Show validation status
        allgemeininformationen_valid = len(missing_fields) == 0
        
        if not allgemeininformationen_valid:
            st.warning(
                f"⚠️ **Fehlende Pflichtfelder in Allgemeininformationen:** "
                f"{', '.join(missing_fields)}"
            )

        d1, d2 = st.columns(2)
        save_meta = d1.button(
            "💾 Metadaten speichern",
            key=f"save_meta_{field_key_suffix}",
            use_container_width=True,
            disabled=not allgemeininformationen_valid,
        )
        save_meta_next = d2.button(
            "💾 Metadaten speichern & Weiter",
            key=f"save_meta_next_{field_key_suffix}",
            use_container_width=True,
            disabled=not allgemeininformationen_valid,
        )

        if save_meta or save_meta_next:
            if not allgemeininformationen_valid:
                st.error("Bitte alle Pflichtfelder in Fehlerbild Allgemeininformationen ausfüllen.")
            else:
                f = rec["fehler"]
                f["CaseStatus"] = case_status
                f["Prioritaet"] = prioritaet
                f["QZStatus"] = qz_status
                f["RQMRelevant"] = (rqm_relevant == "Ja")
                f["Fehlerart"] = [x for x in st.session_state.get(f"fehlerart_{field_key_suffix}", []) if x in FEHLERART_OPTIONS]
                f["Fehlerort"] = st.session_state.get(f"ort_{field_key_suffix}", "")
                f["BI_alt"] = bi_alt
                f["Fehlerbeschreibung"] = fehlerbeschreibung
                f["Kommentar"] = kommentar
                f["Nacharbeit_done"] = nacharbeit_done
                if nacharbeit_done:
                    f["BI_neu"] = bi_neu
                    f["Nacharbeitsvorschlag"] = nacharbeitsvorschlag
                    f["Kommentar_Nacharbeit"] = kommentar_nacharbeit
                else:
                    f["BI_neu"] = bi_alt

                # Ab hier: immer speichern – unabhängig von Nacharbeit
                save_index_v2(paths["index"], idx)
                st.success("Metadaten gespeichert.")

                # ✅ „Metadaten speichern & Weiter“: nur Navigation + scroll-to-top
                if save_meta_next and st.session_state.current_idx < len(images) - 1:
                    st.session_state.current_idx += 1
                    st.session_state.canvas_ver += 1

                    # when jumping to the next Fehlerbild, scroll to top
                    st.session_state["scroll_to_top"] = True

                    safe_rerun()


        # ===== Hauptbild-Editor =====
        st.markdown('<div class="frame-title">Fehlerbild</div>', unsafe_allow_html=True)
        is_internal_audit = bool(audit_info and audit_info.get("scope") == "Internes Audit")

        # Load base image and overlay separately
        base_ref = rec.get("base_image") or rec.get("raw")
        overlay_ref = rec.get("overlay") or rec.get("edited")
        base_abs = resolve_media_path(base_ref, paths) if base_ref else None
        overlay_abs = resolve_media_path(overlay_ref, paths) if overlay_ref else None

        if (not base_abs or not os.path.exists(base_abs)) and is_internal_audit:
            st.warning("Aktuell ist kein gültiges Bild mit diesem Fehlerbild verknüpft.")
            _raw_picker_for_main_image(rec, paths, a_paths, idx)
        elif not base_abs or not os.path.exists(base_abs):
            st.error("Bilddatei wurde nicht gefunden.")
            return
        else:
            #Composite base + overlay in memory for display
            composite_img = composite_base_with_overlay(base_abs, overlay_abs)
            if composite_img is None:
                with Image.open(base_abs) as im:
                    composite_img = im.copy().convert("RGB")
            
            disp = downscale_to_width(composite_img, st.session_state.display_width)
            
            def on_save_main(overlay):
                # Save ONLY the overlay (transparent PNG), not a baked composite
                save_annotated_as_edited(rec, overlay, a_paths)
                save_index_v2(paths["index"], idx)
                st.success("Vorher-Markierung gespeichert.")
                st.session_state.canvas_ver += 1
                safe_rerun()
            
            def on_clear_main():
                # LAYERED: Delete only the overlay file, not the base image
                overlay_path = rec.get("overlay") or rec.get("edited")
                if overlay_path and is_overlay_ref(overlay_path):
                    delete_global_media(overlay_path)
                rec["overlay"] = None
                rec["edited"] = None
                save_index_v2(paths["index"], idx)
                st.success("Vorher-Markierung entfernt.")
                st.session_state.canvas_ver += 1
                safe_rerun()
            
            render_enhanced_canvas(
                background_image=disp,
                canvas_key=f"canvas::main::{st.session_state.current_idx}::{st.session_state.canvas_ver}",
                form_key=f"form_main_{st.session_state.current_idx}",
                on_save_callback=on_save_main,
                on_clear_callback=on_clear_main,
                tool_key_prefix="main"
            )

        if is_internal_audit and base_abs and os.path.exists(base_abs):
            with st.expander("RAW-Bild aus Audit-Ordner zuweisen / entfernen", expanded=False):
                _raw_picker_for_main_image(rec, paths, a_paths, idx)

        # ===== Kontextbild =====
        ctx_list = rec.get("ctx_list", []) or []
        has_kontextbild = bool(ctx_list)

        with st.expander("Kontextbild", expanded=has_kontextbild):
            st.markdown('<div class="frame-title">Kontextbild</div>', unsafe_allow_html=True)

            # --- Upload: Kontextbild als Basisbild (base_images/*) anhängen ---
            ctx_files = st.file_uploader(
                "Kontextbild hochladen (ein Bild)",
                accept_multiple_files=True,
                type=["jpg", "jpeg", "png", "heic"],
                key=f"ctx_up_{st.session_state.current_idx}",
            )
            if st.button(
                "➕ Speichern/Ersetzen Kontextbild",
                key=f"ctx_add_{st.session_state.current_idx}",
                use_container_width=True,
            ):
                if ctx_files:
                    # attach_context_images sorgt für das Basisbild (raw/base),
                    attach_context_images(ctx_files, rec, a_paths, index=idx)
                    save_index_v2(paths["index"], idx)
                    st.success("Kontextbild gesetzt (älteres ggf. überschrieben).")
                    safe_rerun()

            # --- Anzeige + Canvas für das erste Kontextbild (falls vorhanden) ---
            if ctx_list:
                entry = ctx_list[0]

                # LAYERED: Basis- und Overlay-Referenzen
                base_ref = entry.get("base") or entry.get("raw")
                overlay_ref = entry.get("overlay") or entry.get("edited")

                base_abs_ctx = resolve_media_path(base_ref, paths) if base_ref else None
                overlay_abs = resolve_media_path(overlay_ref, paths) if overlay_ref else None

                if base_abs_ctx and os.path.exists(base_abs_ctx):
                    # Basis + Overlay im Speicher zusammensetzen
                    composite_ctx = composite_base_with_overlay(base_abs_ctx, overlay_abs)
                    if composite_ctx is None:
                        with Image.open(base_abs_ctx) as cim:
                            composite_ctx = cim.copy().convert("RGB")

                    disp_ctx = downscale_to_width(
                        composite_ctx,
                        int(0.8 * st.session_state.display_width),
                    )

                    project_id = idx.get("project", {}).get("project_id", "PROJ")
                    audit_id = rec.get("audit_id", "")
                    nr = rec.get("nr", "000")

                    def on_save_ctx(overlay, ctx_entry=entry):
                        """
                        LAYERED:
                        - speichert NUR ein transparentes Overlay in GlobalMedia/overlays
                        - verknüpft dieses Overlay mit dem Kontextbild-Eintrag
                        - Basisbild (base_images/*) bleibt unverändert
                        """
                        old_overlay_ref = ctx_entry.get("overlay") or ctx_entry.get("edited")
                        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                            delete_global_media(old_overlay_ref)

                        # Neues Overlay speichern
                        filename, _ = save_canvas_overlay(
                            overlay_rgba=overlay,
                            project_id=project_id,
                            audit_id=audit_id,
                            nr=nr,
                            overlay_type=OVERLAY_KONTEXT,
                            index=0,
                        )

                        ctx_entry["overlay"] = f"overlays/{filename}"
                        ctx_entry["edited"] = ctx_entry["overlay"]

                        save_index_v2(paths["index"], idx)
                        st.success("Kontext-Markierung gespeichert.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()

                    def on_clear_ctx(ctx_entry=entry):
                        """
                        LAYERED:
                        - nur das Overlay entfernen (Datei + Referenzen)
                        - Basisbild bleibt bestehen
                        """
                        old_overlay_ref = ctx_entry.get("overlay") or ctx_entry.get("edited")
                        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                            delete_global_media(old_overlay_ref)

                        ctx_entry["overlay"] = None
                        ctx_entry["edited"] = None

                        save_index_v2(paths["index"], idx)
                        st.success("Markierung entfernt (Kontext-Overlay gelöscht).")
                        st.session_state.canvas_ver += 1
                        safe_rerun()

                    # gleicher Canvas-Editor wie beim Hauptbild 
                    render_enhanced_canvas(
                        background_image=disp_ctx,
                        canvas_key=(
                            f"canvas::ctx::"
                            f"{st.session_state.current_idx}::0::"
                            f"{st.session_state.canvas_ver}"
                        ),
                        form_key=f"form_ctx_{st.session_state.current_idx}_0",
                        on_save_callback=on_save_ctx,
                        on_clear_callback=on_clear_ctx,
                        tool_key_prefix="ctx",
                    )

                    # Kontextbild komplett löschen (Basis + Overlay)
                    if st.button(
                        "🗑️ Kontextbild löschen",
                        key=f"del_ctx_{st.session_state.current_idx}",
                        use_container_width=True,
                    ):
                        detach_context_image(rec, 0, a_paths, index=idx)
                        save_index_v2(paths["index"], idx)
                        st.success("Kontextbild gelöscht.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()
                else:
                    st.info("Kontextbild fehlt oder Datei nicht gefunden.")
            else:
                st.info("Kein Kontextbild vorhanden.")

        # ===== Zusatzbilder (Fehlerbild) =====
        add_list = rec.get("add_fehler_list", []) or []
        has_additional_pre = bool(add_list)

        with st.expander("Zusatzbilder (Fehlerbild)", expanded=has_additional_pre):
            st.markdown('<div class="frame-title">Zusatzbilder (Fehlerbild)</div>', unsafe_allow_html=True)

            # --- Upload: Basisbilder für Zusatzbilder anhängen (layered) ---
            add_files = st.file_uploader(
                "Zusatzbilder hochladen (mehrere)",
                type=["jpg", "jpeg", "png", "heic"],
                accept_multiple_files=True,
                key=f"add_pre_up_{st.session_state.current_idx}",
            )
            if st.button(
                "➕ Zusatzbilder hinzufügen",
                key=f"add_pre_add_{st.session_state.current_idx}",
                use_container_width=True,
            ):
                if add_files:
                    # attach_additional_images kümmert sich um das Basisbild (raw/base)
                    attach_additional_images(add_files, rec, a_paths, phase="FEHLER")
                    save_index_v2(paths["index"], idx)
                    st.success(f"{len(add_files)} Zusatzbild(er) hinzugefügt.")
                    safe_rerun()

            if add_list:
                # --- Thumbnails: nur das Basisbild für die Vorschau verwenden ---
                abs_list = []
                for e in add_list:
                    base_ref_add = e.get("base") or e.get("raw")
                    ap = resolve_media_path(base_ref_add, paths) if base_ref_add else None
                    if ap and os.path.exists(ap):
                        abs_list.append(ap)

                sel_idx = _banner_thumbnails(
                    abs_list,
                    key_prefix=f"add_pre_banner_{st.session_state.current_idx}",
                    per_row=6,
                    thumb_h=120,
                )

                labels = [
                    f"#{i+1}: {os.path.basename((e.get('overlay') or e.get('base') or e.get('raw') or 'unbenannt'))}"
                    for i, e in enumerate(add_list)
                ]
                dd_sel = st.selectbox(
                    "Zusatzbild wählen (Fehlerbild)",
                    options=list(range(len(add_list))),
                    format_func=lambda i: labels[i],
                    key=f"sel_add_pre_dd_{st.session_state.current_idx}",
                )

                active_sel = sel_idx if sel_idx is not None else dd_sel
                add_entry = add_list[active_sel]

                # Basis- und Overlay-Referenzen
                base_ref_add = add_entry.get("base") or add_entry.get("raw")
                overlay_ref_add = add_entry.get("overlay") or add_entry.get("edited")

                base_abs_add = resolve_media_path(base_ref_add, paths) if base_ref_add else None
                overlay_abs_add = (
                    resolve_media_path(overlay_ref_add, paths) if overlay_ref_add else None
                )

                if base_abs_add and os.path.exists(base_abs_add):
                    # Composite aus Basis + Overlay im Speicher
                    composite_img_add = composite_base_with_overlay(base_abs_add, overlay_abs_add)
                    if composite_img_add is None:
                        with Image.open(base_abs_add) as ai:
                            composite_img_add = ai.copy().convert("RGB")

                    disp_add = downscale_to_width(
                        composite_img_add,
                        int(0.8 * st.session_state.display_width),
                    )

                    project_id = idx.get("project", {}).get("project_id", "PROJ")
                    audit_id = rec.get("audit_id", "")
                    nr = rec.get("nr", "000")

                    def on_save_add_pre(overlay, idx_sel=active_sel, entry=add_entry):
                        """
                        LAYERED (Kontextbild-Pattern):
                        - Speichert NUR ein transparentes Overlay in GlobalMedia/overlays
                        - Verwendet save_canvas_overlay mit OVERLAY_ZUSATZ_FEHLER
                        - Verknüpft das Overlay mit dem Zusatzbild-Eintrag
                        - Basisbild bleibt unverändert
                        """
                        old_overlay_ref = entry.get("overlay") or entry.get("edited")
                        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                            delete_global_media(old_overlay_ref)

                        # Neues Overlay speichern mit korrektem Typ und Index
                        filename, _ = save_canvas_overlay(
                            overlay_rgba=overlay,
                            project_id=project_id,
                            audit_id=audit_id,
                            nr=nr,
                            overlay_type=OVERLAY_ZUSATZ_FEHLER,
                            index=idx_sel,
                        )

                        entry["overlay"] = f"overlays/{filename}"
                        entry["edited"] = entry["overlay"]

                        save_index_v2(paths["index"], idx)
                        st.success("Zusatz-Markierung gespeichert.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()

                    def on_clear_add_pre(entry=add_entry):
                        """
                        LAYERED (Kontextbild-Pattern):
                        - Nur das Overlay löschen (Datei + Referenzen)
                        - Basisbild bleibt bestehen
                        """
                        old_overlay_ref = entry.get("overlay") or entry.get("edited")
                        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                            delete_global_media(old_overlay_ref)

                        entry["overlay"] = None
                        entry["edited"] = None

                        save_index_v2(paths["index"], idx)
                        st.success("Zusatz-Markierung entfernt.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()

                    render_enhanced_canvas(
                        background_image=disp_add,
                        canvas_key=(
                            f"canvas::addpre::"
                            f"{st.session_state.current_idx}::{active_sel}::"
                            f"{st.session_state.canvas_ver}"
                        ),
                        form_key=f"form_add_pre_{st.session_state.current_idx}_{active_sel}",
                        on_save_callback=on_save_add_pre,
                        on_clear_callback=on_clear_add_pre,
                        tool_key_prefix="add_pre",
                    )

                    # Zusatzbild komplett löschen (Basis + evtl. Overlay)
                    if st.button(
                        "🗑️ Zusatzbild löschen",
                        key=f"del_add_pre_{st.session_state.current_idx}_{active_sel}",
                        use_container_width=True,
                    ):
                        detach_additional_image(rec, active_sel, a_paths, phase="FEHLER", index=idx)
                        save_index_v2(paths["index"], idx)
                        st.success("Zusatzbild gelöscht.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()
                else:
                    st.info("Zusatzbild fehlt oder Datei nicht gefunden.")
            else:
                st.info("Noch keine Zusatzbilder (Fehlerbild).")

        # ===== Bild nach Nacharbeit =====
        # Detect if we already have a Nacharbeit-Bild
        after_base_ref = rec.get("after_base") or rec.get("after_raw")
        after_overlay_ref = rec.get("after_overlay") or rec.get("after_edited")

        # Resolve absolute paths once
        after_base_abs = resolve_media_path(after_base_ref, paths) if after_base_ref else None
        after_overlay_abs = (
            resolve_media_path(after_overlay_ref, paths) if after_overlay_ref else None
        )

        # Only treat as "has image" if there is a real, existing file
        has_after_image = bool(after_base_abs and os.path.exists(after_base_abs))

        with st.expander("Bild nach Nacharbeit (Vorher/Nachher)", expanded=has_after_image):
            st.markdown(
                '<div class="frame-title">Bild nach Nacharbeit (Vorher/Nachher)</div>',
                unsafe_allow_html=True,
            )

            # --- Upload / Speichern Nachher-Bild ---
            after_file = st.file_uploader(
                "Nachher-Bild hochladen",
                type=["jpg", "jpeg", "png", "heic"],
                key=f"after_up_{st.session_state.current_idx}",
            )

            if st.button(
                "📥 Speichern (Nachher-Bild)",
                key=f"after_save_{st.session_state.current_idx}",
                use_container_width=True,
            ):
                if after_file is not None:
                    pil = decode_upload_to_pil(after_file.read(), after_file.name)

                    # Nachher-Bild als Basisbild im globalen Store speichern
                    base_filename, base_abs_after = save_base_image(pil, ".jpg")
                    base_ref_after = f"base_images/{base_filename}"
                    rec["after_base"] = base_ref_after
                    rec["after_raw"] = base_ref_after    
                    rec["after_overlay"] = None
                    rec["after_edited"] = None
                    save_index_v2(paths["index"], idx)
                    st.success("Nachher-Bild gespeichert.")
                    safe_rerun()

            # --- Anzeige + Canvas + Löschen innerhalb des Expanders ---
            if after_base_abs and os.path.exists(after_base_abs):
                # Composite im Speicher erzeugen (Basis + Overlay)
                composite_after = composite_base_with_overlay(after_base_abs, after_overlay_abs)
                if composite_after is None:
                    from PIL import Image as _Image
                    with _Image.open(after_base_abs) as imA:
                        composite_after = imA.copy().convert("RGB")

                dispA = downscale_to_width(
                    composite_after,
                    int(0.8 * st.session_state.display_width),
                )

                project_id = idx.get("project", {}).get("project_id", "PROJ")
                audit_id = rec.get("audit_id", "")
                nr = rec.get("nr", "000")

                def on_save_after(overlay):
                    """
                    LAYERED:
                    - Speichert nur ein transparentes Overlay im globalen Overlay-Ordner
                    - Verknüpft dieses mit dem Nacharbeit-Bild
                    """
                    old_overlay_ref = rec.get("after_overlay") or rec.get("after_edited")
                    if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                        delete_global_media(old_overlay_ref)

                    # Neues Overlay speichern
                    filename, _ = save_canvas_overlay(
                        overlay_rgba=overlay,
                        project_id=project_id,
                        audit_id=audit_id,
                        nr=nr,
                        overlay_type=OVERLAY_NACHARBEIT,
                    )

                    rec["after_overlay"] = f"overlays/{filename}"
                    # Legacy-Feld synchron halten
                    rec["after_edited"] = rec["after_overlay"]

                    save_index_v2(paths["index"], idx)
                    st.success("Nachher-Markierung gespeichert.")
                    st.session_state.canvas_ver += 1
                    safe_rerun()

                def on_clear_after():
                    """
                    LAYERED:
                    - Nur das Overlay löschen (Datei + Referenzen)
                    - Basisbild bleibt unverändert erhalten
                    """
                    old_overlay_ref = rec.get("after_overlay") or rec.get("after_edited")
                    if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                        delete_global_media(old_overlay_ref)

                    rec["after_overlay"] = None
                    rec["after_edited"] = None

                    save_index_v2(paths["index"], idx)
                    st.success("Nachher-Markierung entfernt.")
                    st.session_state.canvas_ver += 1
                    safe_rerun()

                # Canvas-Editor anzeigen
                render_enhanced_canvas(
                    background_image=dispA,
                    canvas_key=(
                        f"canvas::after::"
                        f"{st.session_state.current_idx}::"
                        f"{st.session_state.canvas_ver}"
                    ),
                    form_key=f"form_after_{st.session_state.current_idx}",
                    on_save_callback=on_save_after,
                    on_clear_callback=on_clear_after,
                    tool_key_prefix="after",
                )

                # Nachher-Bild komplett löschen (Basis-Verknüpfung + Overlay)
                if st.button(
                    "🗑️ Nachher-Bild löschen",
                    key=f"del_after_{st.session_state.current_idx}",
                    use_container_width=True,
                ):
                    # Overlay-Datei ggf. löschen
                    old_overlay_ref = rec.get("after_overlay") or rec.get("after_edited")
                    if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                        delete_global_media(old_overlay_ref)

                    # Verknüpfungen entfernen – Basisdatei im globalen Store bleibt erhalten
                    rec["after_base"] = None
                    rec["after_raw"] = None
                    rec["after_overlay"] = None
                    rec["after_edited"] = None
                    save_index_v2(paths["index"], idx)
                    st.success("Nachher-Bild gelöscht.")
                    st.session_state.canvas_ver += 1
                    safe_rerun()
            else:
                st.info("Noch kein Nachher-Bild vorhanden.")

        # ===== Zusatzbilder (Nacharbeit) =====
        add_list2 = rec.get("add_after_list", []) or []
        has_additional_post = bool(add_list2)

        with st.expander("Zusatzbilder (Nacharbeit)", expanded=has_additional_post):
            st.markdown('<div class="frame-title">Zusatzbilder (Nacharbeit)</div>', unsafe_allow_html=True)

            # --- Upload: Basisbilder für Zusatzbilder (Nacharbeit) anhängen ---
            add_files2 = st.file_uploader(
                "Zusatzbilder hochladen (mehrere)",
                type=["jpg", "jpeg", "png", "heic"],
                accept_multiple_files=True,
                key=f"add_post_up_{st.session_state.current_idx}",
            )
            if st.button(
                "➕ Zusatzbilder hinzufügen (Nacharbeit)",
                key=f"add_post_add_{st.session_state.current_idx}",
                use_container_width=True,
            ):
                if add_files2:
                    attach_additional_images(add_files2, rec, a_paths, phase="NACHARBEIT")
                    save_index_v2(paths["index"], idx)
                    st.success(f"{len(add_files2)} Zusatzbild(er) (Nacharbeit) hinzugefügt.")
                    safe_rerun()

            if add_list2:
                # --- Thumbnails: nur Basisbilder für Vorschau ---
                abs_list2 = []
                for e in add_list2:
                    base_ref2 = e.get("base") or e.get("raw")
                    ap2 = resolve_media_path(base_ref2, paths) if base_ref2 else None
                    if ap2 and os.path.exists(ap2):
                        abs_list2.append(ap2)

                sel_idx2 = _banner_thumbnails(
                    abs_list2,
                    key_prefix=f"add_post_banner_{st.session_state.current_idx}",
                    per_row=6,
                    thumb_h=120,
                )

                # Etiketten basieren auf Overlay- oder Basis-Referenz
                labels2 = [
                    f"#{i+1}: {os.path.basename((e.get('overlay') or e.get('base') or e.get('raw') or 'unbenannt'))}"
                    for i, e in enumerate(add_list2)
                ]
                dd_sel2 = st.selectbox(
                    "Zusatzbild wählen (Nacharbeit)",
                    options=list(range(len(add_list2))),
                    format_func=lambda i: labels2[i],
                    key=f"sel_add_post_dd_{st.session_state.current_idx}",
                )

                active_sel2 = sel_idx2 if sel_idx2 is not None else dd_sel2
                entry2 = add_list2[active_sel2]

                # Basis- und Overlay-Referenzen
                base_ref2 = entry2.get("base") or entry2.get("raw")
                overlay_ref2 = entry2.get("overlay") or entry2.get("edited")

                base_abs2 = resolve_media_path(base_ref2, paths) if base_ref2 else None
                overlay_abs2 = resolve_media_path(overlay_ref2, paths) if overlay_ref2 else None

                if base_abs2 and os.path.exists(base_abs2):
                    # Composite aus Basis + Overlay im Speicher
                    composite_img2 = composite_base_with_overlay(base_abs2, overlay_abs2)
                    if composite_img2 is None:
                        with Image.open(base_abs2) as ai2:
                            composite_img2 = ai2.copy().convert("RGB")

                    disp_add2 = downscale_to_width(
                        composite_img2,
                        int(0.8 * st.session_state.display_width),
                    )

                    # Get project info for overlay naming
                    project_id = idx.get("project", {}).get("project_id", "PROJ")
                    audit_id = rec.get("audit_id", "")
                    nr = rec.get("nr", "000")

                    def on_save_add_post(overlay, idx_sel=active_sel2, entry=entry2):
                        """
                        LAYERED (Kontextbild-Pattern):
                        - Speichert NUR ein transparentes Overlay in GlobalMedia/overlays
                        - Verwendet save_canvas_overlay mit OVERLAY_ZUSATZ_NACHARBEIT
                        - Verknüpft das Overlay mit dem Zusatzbild-Eintrag
                        - Basisbild bleibt unverändert
                        """
                        # Altes Overlay entfernen
                        old_overlay_ref = entry.get("overlay") or entry.get("edited")
                        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                            delete_global_media(old_overlay_ref)

                        # Neues Overlay speichern mit korrektem Typ und Index
                        filename, _ = save_canvas_overlay(
                            overlay_rgba=overlay,
                            project_id=project_id,
                            audit_id=audit_id,
                            nr=nr,
                            overlay_type=OVERLAY_ZUSATZ_NACHARBEIT,
                            index=idx_sel,
                        )

                        entry["overlay"] = f"overlays/{filename}"
                        entry["edited"] = entry["overlay"]
                        save_index_v2(paths["index"], idx)
                        st.success("Zusatz-Markierung (Nacharbeit) gespeichert.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()

                    def on_clear_add_post(entry=entry2):
                        """
                        LAYERED (Kontextbild-Pattern):
                        - Nur das Overlay löschen (Datei + Referenzen)
                        - Basisbild bleibt bestehen
                        """
                        old_overlay_ref = entry.get("overlay") or entry.get("edited")
                        if old_overlay_ref and is_overlay_ref(old_overlay_ref):
                            delete_global_media(old_overlay_ref)

                        entry["overlay"] = None
                        entry["edited"] = None

                        save_index_v2(paths["index"], idx)
                        st.success("Zusatz-Markierung (Nacharbeit) entfernt.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()

                    render_enhanced_canvas(
                        background_image=disp_add2,
                        canvas_key=(
                            f"canvas::addpost::"
                            f"{st.session_state.current_idx}::{active_sel2}::"
                            f"{st.session_state.canvas_ver}"
                        ),
                        form_key=f"form_add_post_{st.session_state.current_idx}_{active_sel2}",
                        on_save_callback=on_save_add_post,
                        on_clear_callback=on_clear_add_post,
                        tool_key_prefix="add_post",
                    )

                    # Zusatzbild komplett löschen (Basis + Overlay)
                    if st.button(
                        "🗑️ Zusatzbild löschen (Nacharbeit)",
                        key=f"del_add_post_{st.session_state.current_idx}_{active_sel2}",
                        use_container_width=True,
                    ):
                        detach_additional_image(rec, active_sel2, a_paths, phase="NACHARBEIT", index=idx)
                        save_index_v2(paths["index"], idx)
                        st.success("Zusatzbild (Nacharbeit) gelöscht.")
                        st.session_state.canvas_ver += 1
                        safe_rerun()
                else:
                    st.info("Zusatzbild (Nacharbeit) fehlt oder Datei nicht gefunden.")
            else:
                st.info("Noch keine Zusatzbilder (Nacharbeit).")

    # ---------- Inhaltsangabe ----------
    elif st.session_state["main_tab"] == TAB_TOC:

        render_inhaltsangabe_tab(
            idx=idx,
            active_audit=active_audit,
            paths=paths,
            safe_rerun=safe_rerun,
            TAB_EDITOR=TAB_EDITOR,
            load_index_v2=load_index_v2,
            save_index_v2=save_index_v2,
            reindex_audit_images=reindex_audit_images,
            index_prefers_relative=index_prefers_relative,
        )

    # ---------- Übersicht ----------
    elif st.session_state["main_tab"] == TAB_OVERVIEW:
        st.markdown('<div class="frame-title">Projektübersicht</div>', unsafe_allow_html=True)
        audits = idx.get("audits", [])
        rows = []
        for a in audits:
            a_imgs = [r for r in idx.get("images", []) if r.get("audit_id") == a["audit_id"]]
            o = sum(1 for r in a_imgs if (r.get("fehler", {}).get("CaseStatus", "Open") != "Closed"))
            c = len(a_imgs) - o
            rows.append({
                "Datum": a["date"],
                "Typ": a["type"],
                "Scope": a.get("scope", ""),
                "Auditor": a.get("auditor", ""),
                "Open": o,
                "Closed": c,
                "Total": len(a_imgs),
            })
        if rows:
            # Sort by date (oldest first / adjust if you want reverse)
            rows_sorted = sorted(rows, key=lambda r: r["Datum"])

            # ---------------------------------------------------------
            # Summary metrics – similar to badge view in Inhaltsangabe
            # ---------------------------------------------------------
            total_audits = len(rows_sorted)
            total_images = sum(r["Total"] for r in rows_sorted)
            total_open = sum(r["Open"] for r in rows_sorted)
            total_closed = sum(r["Closed"] for r in rows_sorted)

            internal_count = sum(
                1 for a in audits if (a.get("scope") or "") == "Internes Audit"
            )
            customer_count = sum(
                1 for a in audits if (a.get("scope") or "") == "Kundenaudit"
            )

            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
            col_m1.metric("Audits", total_audits)
            col_m2.metric("Fehlerbilder", total_images)
            col_m3.metric(
                "Offen",
                total_open,
                delta=f"{total_closed} geschlossen" if total_closed else None,
            )
            col_m4.metric("Interne Audits", internal_count)
            col_m5.metric("Kundenaudits", customer_count)

            st.markdown("---")

            # ---------------------------------------------------------
            # Header row – manual columns like in badge table
            # ---------------------------------------------------------
            header_cols = st.columns([0.9, 1.1, 1.2, 1.4, 0.6, 0.6, 0.6])
            header_cols[0].markdown("**Datum**")
            header_cols[1].markdown("**Typ**")
            header_cols[2].markdown("**Scope**")
            header_cols[3].markdown("**Auditor**")
            header_cols[4].markdown("**Offen**")
            header_cols[5].markdown("**Geschlossen**")
            header_cols[6].markdown("**Total**")

            # ---------------------------------------------------------
            # Rows – styled similar to badge view (colors, chips)
            # ---------------------------------------------------------
            for r in rows_sorted:
                datum = r.get("Datum", "") or ""
                typ = r.get("Typ", "") or ""
                scope = r.get("Scope", "") or ""
                auditor = r.get("Auditor", "") or "—"
                o = r.get("Open", 0) or 0
                c = r.get("Closed", 0) or 0
                t = r.get("Total", 0) or 0

                row_cols = st.columns([0.9, 1.1, 1.2, 1.4, 0.6, 0.6, 0.6])

                # Datum
                row_cols[0].write(datum)

                # Typ as neutral pill
                if typ:
                    row_cols[1].markdown(
                        f"""
                        <span style="
                            background:#F5F5F5;
                            color:#333;
                            padding:2px 10px;
                            border-radius:999px;
                            font-size:0.85rem;
                            font-weight:600;
                            white-space:nowrap;
                            border:1px solid #E0E0E0;
                        ">{typ}</span>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    row_cols[1].write("—")

                # Scope as colored pill (similar to area/system badges idea)
                if scope == "Internes Audit":
                    scope_bg = "#E3F2FD"
                    scope_fg = "#1565C0"
                elif scope == "Kundenaudit":
                    scope_bg = "#FFF3E0"
                    scope_fg = "#EF6C00"
                else:
                    scope_bg = "#EEEEEE"
                    scope_fg = "#555555"

                scope_label = scope or "—"
                row_cols[2].markdown(
                    f"""
                    <span style="
                        background:{scope_bg};
                        color:{scope_fg};
                        padding:2px 10px;
                        border-radius:999px;
                        font-size:0.80rem;
                        font-weight:600;
                        border:1px solid {scope_fg}20;
                        white-space:nowrap;
                    ">{scope_label}</span>
                    """,
                    unsafe_allow_html=True,
                )

                # Auditor plain text
                row_cols[3].write(auditor)

                # Offen / Geschlossen / Total – colored numbers like status badges
                if o > 0:
                    open_html = f'<span style="color:#cc0000;font-weight:600;">{o}</span>'
                else:
                    open_html = '<span style="color:#999;">0</span>'

                if c > 0:
                    closed_html = f'<span style="color:#009900;font-weight:600;">{c}</span>'
                else:
                    closed_html = '<span style="color:#999;">0</span>'

                total_html = f'<span style="font-weight:600;">{t}</span>'

                row_cols[4].markdown(open_html, unsafe_allow_html=True)
                row_cols[5].markdown(closed_html, unsafe_allow_html=True)
                row_cols[6].markdown(total_html, unsafe_allow_html=True)
        else:
            st.info("Noch keine Audits vorhanden.")

        # ------------------------------------------------------------------
        # RQM-relevante Fehlerbilder (alle Audits)
        # ------------------------------------------------------------------
        st.markdown("---")
        st.subheader("RQM-relevante Fehlerbilder (alle Audits)")

        # Ensure the Nacharbeit-Tooltip CSS is available here as well
        st.markdown(
            """
            <style>
            .na-tooltip-wrapper {
                position: relative;
                display: inline-block;
                cursor: help;
                font-size: 1.1rem;
            }
            .na-tooltip-placeholder {
                color: #DDD;
                cursor: default;
                font-size: 1.1rem;
                display: inline-block;
            }
            .na-tooltip-wrapper .na-tooltip-text {
                visibility: hidden;
                min-width: 350px;
                max-width: 450px;
                background-color: #333;
                color: #fff;
                text-align: left;
                padding: 10px 14px;
                border-radius: 6px;
                font-size: 1.2rem;
                line-height: 1.35rem;
                white-space: pre-line;
                position: absolute;
                z-index: 100;
                bottom: 130%;
                left: 50%;
                transform: translateX(-50%);
                opacity: 0;
                transition: opacity 0.15s ease-in-out;
                box-shadow: 0 2px 6px rgba(0,0,0,0.35);
            }
            .na-tooltip-wrapper .na-tooltip-text::after {
                content: "";
                position: absolute;
                top: 100%;
                left: 50%;
                margin-left: -6px;
                border-width: 6px;
                border-style: solid;
                border-color: #333 transparent transparent transparent;
            }
            .na-tooltip-wrapper:hover .na-tooltip-text {
                visibility: visible;
                opacity: 1;
            }
            .na-tooltip-wrapper-badge {
                font-size: 0.8rem;
            }
            .na-badge-label {
                background: linear-gradient(135deg, #E8F5E9 0%, #C8E6C9 100%);
                color: #2E7D32;
                padding: 1px 6px;
                border-radius: 4px;
                border: 1px solid #A5D6A7;
                font-weight: 600;
                white-space: nowrap;
                display: inline-block;
                user-select: none;
            }
            .na-tooltip-placeholder-badge {
                color: #CCC;
                font-size: 0.75rem;
                display: inline-block;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        all_images = idx.get("images", []) or []
        audit_by_id = {a.get("audit_id"): a for a in audits}

        # Basislisten je Audit für saubere Index-Mappings in den Editor
        audit_to_images = {}
        for rec in all_images:
            aid = rec.get("audit_id")
            if not aid:
                continue
            audit_to_images.setdefault(aid, []).append(rec)

        # Sammle alle RQM-relevanten Fehlerbilder inkl. Audit-Datum
        rqm_rows = []
        for aid, img_list in audit_to_images.items():
            a_info = audit_by_id.get(aid, {})
            audit_date = a_info.get("date", "")
            for base_idx, rec in enumerate(img_list):
                f = rec.get("fehler", {}) or {}
                if not f.get("RQMRelevant", False):
                    continue
                rqm_rows.append((audit_date, aid, base_idx, rec))

        if not rqm_rows:
            st.info("Keine RQM-relevanten Fehlerbilder vorhanden.")
        else:
            # ------------------------------------------------------------------
            # Filters (same as Inhaltsangabe tab): Nacharbeit, Bereiche, Systeme, Sortierung
            # ------------------------------------------------------------------
            # 1) Collect available Bereiche/Systeme from all RQM rows (multiselection-aware)
            all_area_keys = set()
            all_system_keys = set()
            for (_date, _aid, _base_idx, r) in rqm_rows:
                all_area_keys.update([a for a in get_all_areas(r) if a])
                all_system_keys.update([s for s in get_all_systems(r) if s])

            area_options = sorted(all_area_keys, key=lambda k: (VEHICLE_AREA_LABELS.get(k, k) or k))
            system_options = sorted(all_system_keys, key=lambda k: (SYSTEM_DOMAIN_LABELS.get(k, k) or k))

            # 2) Render filter widgets (layout analogous to Inhaltsangabe)
            col_f1, col_f2, col_f3, col_f4 = st.columns([1.2, 1.8, 1.8, 1.8])

            nacharbeit_filter = col_f1.selectbox(
                "Nacharbeit-Filter",
                ["Alle", "Nur Nacharbeit = Ja", "Nur Nacharbeit = Nein"],
                index=0,
                key="ov_rqm_filter_nacharbeit",
            )

            selected_areas = col_f2.multiselect(
                "Bereiche",
                options=area_options,
                default=[],
                format_func=lambda x: VEHICLE_AREA_LABELS.get(x, x),
                key="ov_rqm_filter_areas",
            )

            selected_systems = col_f3.multiselect(
                "Systeme",
                options=system_options,
                default=[],
                format_func=lambda x: SYSTEM_DOMAIN_LABELS.get(x, x),
                key="ov_rqm_filter_systems",
            )

            sort_option = col_f4.selectbox(
                "Sortierung",
                [
                    "Audit-Standard (Bereich → System → BI)",
                    "Nr (aufsteigend)",
                    "Nr (absteigend)",
                    "BI (kritisch zuerst)",
                    "BI (unkritisch zuerst)",
                    "Fehlerort (A→Z)",
                    "Fehlerort (Z→A)",
                    "Status (Open zuerst)",
                    "Status (Closed zuerst)",
                    "Nacharbeit = Ja zuerst",
                    "Nacharbeit = Nein zuerst",
                ],
                index=0,
                key="ov_rqm_sort_option",
            )

            # 3) Helper flags for filtering/sorting
            def _status_flag(rec: dict) -> str:
                f = rec.get("fehler", {}) or {}
                return f.get("CaseStatus", "Open")

            def _nacharbeit_flag(rec: dict) -> bool:
                f = rec.get("fehler", {}) or {}
                return bool(f.get("Nacharbeit_done", False))

            def _bi_index(rec: dict) -> int:
                f = rec.get("fehler", {}) or {}
                bi = f.get("BI_alt") or f.get("BI") or "BI0-tbd."
                try:
                    return SORT_ORDER_BI.index(bi)
                except ValueError:
                    # unknown BI goes last
                    return len(SORT_ORDER_BI) + 999

            # 4) Apply filters
            rqm_filtered = list(rqm_rows)

            if nacharbeit_filter == "Nur Nacharbeit = Ja":
                rqm_filtered = [t for t in rqm_filtered if _nacharbeit_flag(t[3])]
            elif nacharbeit_filter == "Nur Nacharbeit = Nein":
                rqm_filtered = [t for t in rqm_filtered if not _nacharbeit_flag(t[3])]

            if selected_areas:
                sel_a = set(selected_areas)
                rqm_filtered = [
                    t for t in rqm_filtered
                    if sel_a.intersection(set(get_all_areas(t[3])))
                ]

            if selected_systems:
                sel_s = set(selected_systems)
                rqm_filtered = [
                    t for t in rqm_filtered
                    if sel_s.intersection(set(get_all_systems(t[3])))
                ]

            # 5) Apply sorting (same semantics as Inhaltsangabe, but keep audit_date as stable primary key)
            if sort_option == "Audit-Standard (Bereich → System → BI)":
                rqm_filtered.sort(key=lambda t: (t[0], fehlerbild_sort_key(t[3])))
            elif sort_option == "Nr (aufsteigend)":
                rqm_filtered.sort(key=lambda t: (t[0], t[3].get("nr", "")))
            elif sort_option == "Nr (absteigend)":
                rqm_filtered.sort(key=lambda t: (t[0], t[3].get("nr", "")), reverse=True)
            elif sort_option == "BI (kritisch zuerst)":
                rqm_filtered.sort(key=lambda t: (t[0], _bi_index(t[3])))
            elif sort_option == "BI (unkritisch zuerst)":
                rqm_filtered.sort(key=lambda t: (t[0], _bi_index(t[3])), reverse=True)
            elif sort_option == "Fehlerort (A→Z)":
                rqm_filtered.sort(
                    key=lambda t: (t[0], (t[3].get("fehler", {}) or {}).get("Fehlerort", "").lower())
                )
            elif sort_option == "Fehlerort (Z→A)":
                rqm_filtered.sort(
                    key=lambda t: (t[0], (t[3].get("fehler", {}) or {}).get("Fehlerort", "").lower()),
                    reverse=True
                )
            elif sort_option == "Status (Open zuerst)":
                rqm_filtered.sort(key=lambda t: (t[0], 0 if _status_flag(t[3]) != "Closed" else 1))
            elif sort_option == "Status (Closed zuerst)":
                rqm_filtered.sort(key=lambda t: (t[0], 0 if _status_flag(t[3]) == "Closed" else 1))
            elif sort_option == "Nacharbeit = Ja zuerst":
                rqm_filtered.sort(key=lambda t: (t[0], 0 if _nacharbeit_flag(t[3]) else 1))
            elif sort_option == "Nacharbeit = Nein zuerst":
                rqm_filtered.sort(key=lambda t: (t[0], 0 if not _nacharbeit_flag(t[3]) else 1))

            # 6) Flat list (base_idx, rec) for metrics (based on filtered result)
            filtered_rows = [(base_idx, rec) for (_date, _aid, base_idx, rec) in rqm_filtered]

            # IMPORTANT: from here on, use rqm_filtered (not rqm_rows) for rendering the table


            def _status_flag(rec: dict) -> str:
                f = rec.get("fehler", {}) or {}
                return f.get("CaseStatus", "Open")

            # === Summary-Metriken – analog zur Inhaltsangabe "Mit Badges" ===
            total_count = len(filtered_rows)
            open_count = sum(1 for _, r in filtered_rows if _status_flag(r) != "Closed")

            all_areas_set = set()
            all_systems_set = set()
            nacharbeit_info_count = 0
            for _, r in filtered_rows:
                all_areas_set.update(get_all_areas(r))
                all_systems_set.update(get_all_systems(r))
                if has_nacharbeit_info(r):
                    nacharbeit_info_count += 1

            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns([1, 1, 1, 1, 1.2])
            col_m1.metric("RQM-Fehlerbilder", total_count)
            col_m2.metric(
                "Offen",
                open_count,
                delta=None if open_count == total_count else f"{total_count - open_count} geschlossen",
            )
            col_m3.metric("Bereiche", len(all_areas_set))
            col_m4.metric("Systeme", len(all_systems_set))
            col_m5.metric("Mit NA-Info", nacharbeit_info_count)

            st.markdown("---")
            # Gleiche Legende wie in der Inhaltsangabe (Badges + NA-Info)
            render_badge_legend()

            # === Tabellen-Header – Struktur wie "Mit Badges", plus Audit-Spalte ===
            header_cols = st.columns([0.9, 0.5, 1.3, 1.3, 1.8, 0.9, 0.7, 0.5, 0.6, 0.4])
            header_cols[0].markdown("**Audit**")
            header_cols[1].markdown("**Nr**")
            header_cols[2].markdown("**Bereich(e)**")
            header_cols[3].markdown("**System(e)**")
            header_cols[4].markdown("**Fehlerort**")
            header_cols[5].markdown("**Fehlerart**")
            header_cols[6].markdown("**Status**")
            header_cols[7].markdown("**NA**")
            header_cols[8].markdown("**Info**")
            header_cols[9].markdown("**Öffnen**")

            # === Zeilen – Badges + NA-Tooltip + Öffnen-Button ===
            for audit_date, aid, base_idx, rec in rqm_filtered:
                f = rec.get("fehler", {}) or {}
                status = f.get("CaseStatus", "Open")
                nacharbeit_done = bool(f.get("Nacharbeit_done", False))

                all_areas = get_all_areas(rec)
                all_systems = get_all_systems(rec)

                row_cols = st.columns([0.9, 0.5, 1.3, 1.3, 1.8, 0.9, 0.7, 0.5, 0.6, 0.4])

                a_info = audit_by_id.get(aid, {})
                audit_label = a_info.get("type", "") or a_info.get("scope", "") or "—"
                row_cols[0].write(audit_label)

                # Nr
                row_cols[1].write(rec.get("nr", ""))

                # Bereich(e) als Badges
                if all_areas:
                    row_cols[2].markdown(
                        render_area_badges(all_areas),
                        unsafe_allow_html=True,
                    )
                else:
                    row_cols[2].write("—")

                # System(e) als Badges
                if all_systems:
                    row_cols[3].markdown(
                        render_system_badges(all_systems),
                        unsafe_allow_html=True,
                    )
                else:
                    row_cols[3].write("—")

                # Fehlerort (leicht gekürzt wie in "Mit Badges")
                ort = (f.get("Fehlerort", "") or "").strip()
                if len(ort) > 60:
                    ort = ort[:57] + "..."
                row_cols[4].write(ort or "—")

                # Fehlerart (Liste -> kommagetrennt, gekürzt)
                fa_list = f.get("Fehlerart", []) or []
                fa_text = ", ".join(fa_list)
                if len(fa_text) > 60:
                    fa_text = fa_text[:57] + "..."
                row_cols[5].write(fa_text or "—")

                # Status – gleiche Farb-Logik wie in der Inhaltsangabe
                if status == "Closed":
                    row_cols[6].markdown(
                        '<span style="color:#009900;">✓ Closed</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    row_cols[6].markdown(
                        '<span style="color:#cc0000;">○ Open</span>',
                        unsafe_allow_html=True,
                    )

                # Nacharbeit-Flag (Ja/Nein)
                row_cols[7].write("Ja" if nacharbeit_done else "Nein")

                # Nacharbeit-Info Icon mit Tooltip (gleiche Funktion wie Inhaltsangabe)
                na_html = render_nacharbeit_info_icon(rec, unique_key=f"rqm_{aid}_{base_idx}")
                row_cols[8].markdown(na_html, unsafe_allow_html=True)

                # Öffnen-Button – gleiches Verhalten wie bisher
                if row_cols[9].button("➡️", key=f"btn_rqm_open_{aid}_{base_idx}"):
                    current_images = [
                        r
                        for r in idx.get("images", [])
                        if r.get("audit_id") == aid
                    ]
                    if 0 <= base_idx < len(current_images):
                        st.session_state["current_idx"] = base_idx
                        st.session_state["canvas_ver"] = st.session_state.get(
                            "canvas_ver", 0
                        ) + 1
                        st.session_state["current_audit_id"] = aid
                        st.session_state["last_audit_id"] = aid
                        st.session_state["main_tab"] = TAB_EDITOR
                        st.session_state["scroll_to_top"] = True
                        safe_rerun()



    # ---------- Release ----------
    elif st.session_state["main_tab"] == TAB_RELEASE:
        st.markdown('<div class="frame-title">Release</div>', unsafe_allow_html=True)
        all_imgs = idx.get("images", [])
        open_cases = sum(
            1 for r in all_imgs
            if (r.get("fehler", {}).get("CaseStatus", "Open") != "Closed")
        )
        st.metric("Offene Cases", open_cases)

        # --- Grund-Einstellungen für den PDF-Export ---
        mode = st.selectbox(
            "PDF Modus",
            ["All-in-One", "Audit-Report", "Audit-Report-mit-Nacharbeit"],
            index=0,
            help="All-in-One erzeugt einen Gesamtbericht; Audit-Report bezieht sich auf das aktive Audit."
        )
        scope_filter = st.multiselect(
            "Scope-Filter",
            ["Internes Audit", "Kundenaudit"],
            default=["Internes Audit", "Kundenaudit"],
            key="rel_scope_filter"
        )
        include_after = (mode in ("All-in-One", "Audit-Report-mit-Nacharbeit"))
        include_additional = st.checkbox("Zusatzbilder in PDF (Galerien)", value=False)

        hires_pdf = st.checkbox(
            "Maximale Bildauflösung (große PDF-Datei)",
            value=False,
            key=f"hires_pdf_release_{st.session_state.get('current_audit_id','noaudit')}",
            help="Verwendet die Originalauflösung der Bilder im PDF. "
                "Achtung: Kann deutlich größere Dateien und längere Exportzeiten verursachen."
        )

        st.markdown("**Kapitel in der PDF berücksichtigen:**")
        kap1 = st.checkbox(
            "Kapitel 1 – Gesamtübersicht",
            value=True,
            key="rel_kap1",
        )
        kap2 = st.checkbox(
            "Kapitel 2 – Fehlerliste",
            value=True,
            key="rel_kap2",
        )
        kap3 = st.checkbox(
            "Kapitel 3 – Fehlerbilder",
            value=True,
            key="rel_kap3",
        )
        selected_chapters = [
            i for i, flag in enumerate([kap1, kap2, kap3], start=1) if flag
        ]
        if not selected_chapters:
            st.warning("Bitte mindestens ein Kapitel auswählen, sonst wird nur das Deckblatt erzeugt.")

        # --- Sortierung für PDF-Export ---
        st.markdown("**Sortierung der Fehlerbilder im PDF:**")
        sorting_mode = st.selectbox(
            "Sortierung für PDF-Export",
            options=SORTING_MODE_OPTIONS,
            index=0,  # Default: "Audit-Standard (Bereich → System → BI)"
            key="rel_pdf_sorting_mode",
            help=(
                "Wähle die Sortierung der Fehlerbilder in Kapitel 2 (Fehlerliste) "
                "und Kapitel 3 (Fehlerbilder). Diese Sortierung entspricht den "
                "Optionen im Inhaltsangabe-Tab."
            ),
        )


        target_audit_id = active_audit if mode.startswith("Audit-Report") else None
        # -------------------------------------------------------------
        # Audits auswählen, die in den PDF-Export einfließen sollen
        # -------------------------------------------------------------
        selected_audit_ids: Optional[List[str]] = None

        # mehrere Audits des Projekts auswählbar
        if mode == "All-in-One":
            audits_for_choice = [
                a for a in audits
                if (not scope_filter or (a.get("scope") in scope_filter))
            ]

            if audits_for_choice:
                def _audit_label(a: dict) -> str:
                    return f"{a.get('type','')} · {a.get('date','')} · {a.get('scope','')}"

                # Standard: alle passenden Audits sind vorgewählt
                default_selection = audits_for_choice

                selected_audits = st.multiselect(
                    "Audits dieses Projekts, die in den Export einfließen sollen",
                    options=audits_for_choice,
                    default=default_selection,
                    format_func=_audit_label,
                    key="rel_audit_selection",
                )

                if selected_audits:
                    selected_audit_ids = [a["audit_id"] for a in selected_audits]
                else:
                    selected_audit_ids = []
            else:
                selected_audit_ids = []

        # Für Audit-Report-Varianten: Single-Audit (aktuelles aktive Audit)
        elif mode.startswith("Audit-Report") and target_audit_id:
            selected_audit_ids = [target_audit_id]

        # --- Fehlerbilder-Auswahl in einem einklappbaren Tab (Expander) ---
        # eigener Key pro Modus/Audit, damit sich die Auswahl merkt
        img_sel_state_key = f"rel_selected_images_{mode}_{target_audit_id or 'all'}"
        selected_image_keys = None  # None = kein Filter, alle Fehlerbilder

        # Expander-State tracken, damit er nach Interaktion offen bleibt
        expander_state_key = f"rel_expander_open_{mode}_{target_audit_id or 'all'}"
        if expander_state_key not in st.session_state:
            st.session_state[expander_state_key] = False  # Initial geschlossen

        with st.expander("Fehlerbilder für den Export auswählen", expanded=st.session_state[expander_state_key]):
            # Sobald der Expander geöffnet wird und Interaktion stattfindet, merken wir uns das
            # Wir setzen den State auf True, sobald wir im Expander sind und Checkboxen rendern
            if kap2 or kap3:
                # Bilder mit derselben Logik wie beim PDF-Export holen
                candidate_images = select_images(
                    idx,
                    mode,
                    scope_filter,
                    target_audit_id,
                    selected_audit_ids,
                )

                if not candidate_images:
                    st.info("Für diese Auswahl sind keine Fehlerbilder vorhanden.")
                else:
                    # Expander offen halten nach erster Interaktion
                    st.session_state[expander_state_key] = False

                    # ---------------------------------------------------------
                    # Aktuelle Fehlbild-Keys bestimmen
                    # ---------------------------------------------------------
                    img_keys = [
                        f"{rec.get('audit_id','')}__{rec.get('nr','')}"
                        for rec in candidate_images
                    ]
                    img_keys_set = set(img_keys)
                    total_count = len(img_keys)

                    # ---------------------------------------------------------
                    # SINGLE SOURCE OF TRUTH: img_sel_state_key im Session-State
                    # Initialisierung: alle Fehlerbilder vorausgewählt (Standardverhalten)
                    # ---------------------------------------------------------
                    if img_sel_state_key not in st.session_state:
                        # Erste Initialisierung: alle auswählen
                        st.session_state[img_sel_state_key] = list(img_keys)
                    else:
                        # Bereits vorhanden: nur gültige Keys behalten (falls sich Kandidaten geändert haben)
                        existing = st.session_state[img_sel_state_key]
                        if existing is None:
                            st.session_state[img_sel_state_key] = list(img_keys)
                        else:
                            # Nur Keys behalten, die noch in den aktuellen Kandidaten sind
                            st.session_state[img_sel_state_key] = [k for k in existing if k in img_keys_set]

                    # Arbeite mit einer lokalen Kopie als Set für einfache Operationen
                    selected_set = set(st.session_state[img_sel_state_key])

                    # ---------------------------------------------------------
                    # Master-Checkbox
                    # ---------------------------------------------------------
                    all_selected = (len(selected_set) == total_count) and (total_count > 0)

                    master_widget_key = f"rel_img_select_all_{mode}_{target_audit_id or 'all'}"

                    # Callback für Master-Checkbox: wird VOR dem Rerun ausgeführt
                    def on_master_change():
                        st.session_state[expander_state_key] = True
                        master_new_val = st.session_state[master_widget_key]
                        if master_new_val:
                            st.session_state[img_sel_state_key] = list(img_keys)
                        else:
                            st.session_state[img_sel_state_key] = []

                    st.checkbox(
                        "Alle Fehlerbilder auswählen",
                        value=all_selected,
                        key=master_widget_key,
                        on_change=on_master_change,
                        help="Aktiviert/ deaktiviert alle Fehlerbilder in diesem Bereich.",
                    )

                    # ---------------------------------------------------------
                    # Einzel-Checkboxen pro Fehlerbild
                    # ---------------------------------------------------------
                    def make_child_callback(img_key_local, exp_state_key):
                        def on_child_change():
                            # Expander offen halten
                            st.session_state[exp_state_key] = True
                            child_widget_key = f"rel_img_{img_key_local}"
                            child_new_val = st.session_state[child_widget_key]
                            current_selection = set(st.session_state.get(img_sel_state_key, []))
                            if child_new_val:
                                current_selection.add(img_key_local)
                            else:
                                current_selection.discard(img_key_local)
                            st.session_state[img_sel_state_key] = list(current_selection)
                        return on_child_change

                    for rec in candidate_images:
                        img_key = f"{rec.get('audit_id','')}__{rec.get('nr','')}"
                        fdata = rec.get("fehler", {}) or {}
                        short_desc = (fdata.get("Fehlerbeschreibung", "") or "").strip()
                        if len(short_desc) > 60:
                            short_desc = short_desc[:57] + "..."
                        label = f"FB {rec.get('nr','?')} – {short_desc}"
                        is_checked = img_key in selected_set
                        child_key = f"rel_img_{img_key}"

                        st.checkbox(
                            label,
                            value=is_checked,
                            key=child_key,
                            on_change=make_child_callback(img_key, expander_state_key),
                        )

                    # ---------------------------------------------------------
                    # Finale Auswahl für Export
                    # ---------------------------------------------------------
                    final_selection = st.session_state.get(img_sel_state_key, [])
                    selected_image_keys = final_selection if final_selection else None
            else:
                st.info("Aktiviere Kapitel 2 oder 3, um einzelne Fehlerbilder auswählen zu können.")
                st.session_state[img_sel_state_key] = None
                selected_image_keys = None

        # --- Export-Button ---
        can_export = (mode == "All-in-One") or (mode.startswith("Audit-Report") and bool(target_audit_id))
        export_btn = st.button("📄 PDF exportieren", type="primary", use_container_width=True, disabled=not can_export)

        if not can_export and mode.startswith("Audit-Report"):
            st.info("Bitte zunächst ein Audit oben im Editor wählen.")

        if export_btn:
            try:
                idx_latest = load_index_v2(paths["index"])
                pdf_bytes = build_pdf_with_modes(
                    idx_latest,
                    paths,
                    mode,
                    scope_filter,
                    target_audit_id,
                    include_after,
                    include_additional,
                    hires_pdf,
                    selected_chapters,
                    selected_image_keys,
                    selected_audit_ids,
                    sorting_mode=sorting_mode, 
                )

                if isinstance(pdf_bytes, (bytes, bytearray)) and len(pdf_bytes) > 0:
                    # ------- Dateinamen aus Projekt-ID, Audit-Namen und heutigem Datum bauen -------------
                    idx_for_name = idx_latest or {}
                    project_info = idx_for_name.get("project", {}) or {}

                    # Rohwerte
                    project_id_raw = project_info.get("project_id") or "PROJ"
                    audit_name_raw = audit_name or ""

                    # Spaces -> "_" und dann filenamemäßig säubern
                    safe_project_id = sanitize_filename(str(project_id_raw).replace(" ", "_"))
                    safe_audit_name = sanitize_filename(str(audit_name_raw).replace(" ", "_"))

                    # Fallback: wenn kein Auditname vorhanden ist (z. B. All-in-One ohne aktives Audit)
                    if not safe_audit_name:
                        safe_audit_name = sanitize_filename(mode.replace(" ", "_")) or "Report"

                    today_str = datetime.now().strftime("%d-%m-%Y")
                    base_filename = f"{safe_project_id}_{safe_audit_name}_{today_str}"
                    st.session_state.last_report_pdf = pdf_bytes
                    st.session_state.last_report_name = base_filename
                    st.success(f"PDF erfolgreich erzeugt: {base_filename}.pdf")
                    st.download_button(
                        "⬇ PDF herunterladen",
                        data=st.session_state.last_report_pdf,
                        file_name=f"{st.session_state.last_report_name}.pdf",
                        mime="application/pdf",
                        key=f"rel_download_{mode}_{target_audit_id or 'all'}",
                    )
                else:
                    st.error("PDF konnte nicht erzeugt werden (leere Daten).")
            except Exception as ex:
                st.error(f"Fehler beim PDF-Export: {ex}")

        # Bereits erzeugten Report erneut herunterladen
        if st.session_state.get("last_report_pdf") is not None:
            st.download_button(
                "📥 Letzten Report erneut herunterladen",
                data=st.session_state.last_report_pdf,
                file_name=f"{st.session_state.last_report_name}.pdf",
                mime="application/pdf",
                key="rel_download_last",
            )
    
    # ---------- Reference Tab (Video) ----------
    elif st.session_state["main_tab"] == TAB_REFERENCE:
        st.markdown('<div class="frame-title">Referenz-Videos</div>', unsafe_allow_html=True)
        
        all_images = idx.get("images", [])
        images = [r for r in all_images if r.get("audit_id") == active_audit] if active_audit else []
        
        if not active_audit:
            st.info("Bitte auf der Landing-Page ein Audit wählen.")
            return
            
        if not images:
            st.info("Noch keine Fehlerbilder im Audit. Bitte zuerst Bilder hinzufügen.")
            return
        
        st.session_state.current_idx = max(0, min(st.session_state.current_idx, len(images) - 1))
        rec = images[st.session_state.current_idx]
        
        # Navigation buttons für Videos
        c1, c2 = st.columns(2)
        if c1.button("↵ Zurück (Fehlerbild)", disabled=st.session_state.current_idx == 0):
            st.session_state.current_idx -= 1
            safe_rerun()
        if c2.button("↪ Weiter (Fehlerbild)", disabled=st.session_state.current_idx >= len(images) - 1):
            st.session_state.current_idx += 1
            safe_rerun()
        
        st.markdown(f"#### Fehlerbild {st.session_state.current_idx+1}/{len(images)} – Nr {rec['nr']}")
        
        # Video-Upload im Reference Tab
        with st.expander("📹 Video hochladen", expanded=True):
            video_files = st.file_uploader(
                "Video-Dateien hochladen (MP4, MOV, AVI, MKV)",
                type=["mp4", "mov", "avi", "mkv"],
                accept_multiple_files=True,
                key=f"video_upload_{st.session_state.current_idx}"
            )
            
            if st.button("📥 Videos speichern", key=f"save_videos_{st.session_state.current_idx}", use_container_width=True):
                if video_files:
                    a_paths = audit_paths(paths, active_audit)
                    idx2 = load_index_v2(paths["index"])
                    prefer_rel = index_prefers_relative(idx2)
                    
                    saved_count = 0
                    for video_file in video_files:
                        saved_path = save_video_file(
                            video_file.read(),
                            video_file.name,
                            idx2,
                            active_audit,
                            paths,
                            prefer_rel,
                            rec.get("nr")
                        )
                        if saved_path:
                            saved_count += 1
                    
                    save_index_v2(paths["index"], idx2)
                    st.success(f"{saved_count} Video(s) gespeichert.")
                    safe_rerun()
                else:
                    st.warning("Bitte wähle mindestens eine Video-Datei aus.")
        
        st.markdown("---")
        st.subheader("Videos zu diesem Fehlerbild")
        
        video_paths = get_videos_for_record(rec, paths)
        
        if not video_paths:
            st.info("Noch keine Videos für dieses Fehlerbild vorhanden.")
        else:
            for i, video_path in enumerate(video_paths):
                if os.path.exists(video_path):
                    with st.expander(f"Video {i+1}: {os.path.basename(video_path)}", expanded=True):
                        st.video(video_path)
                        
                        if st.button(f"🗑️ Video löschen", key=f"delete_video_{st.session_state.current_idx}_{i}"):
                            try:
                                video_ref = rec.get("videos", [])[i] if i < len(rec.get("videos", [])) else None
                                
                                if video_ref and is_media_shared(idx, video_ref, exclude_rec=rec):
                                    if "videos" in rec:
                                        rec_videos = rec.get("videos", [])
                                        if i < len(rec_videos):
                                            del rec_videos[i]
                                        rec["videos"] = rec_videos
                                        save_index_v2(paths["index"], idx)
                                    st.success("Video-Verknüpfung entfernt (Datei wird von anderen Fehlerbildern verwendet).")
                                else:
                                    os.remove(video_path)
                                    
                                    if "videos" in rec:
                                        rec_videos = rec.get("videos", [])
                                        if video_path in rec_videos or to_rel_path(video_path, {"root": paths["root"]}) in rec_videos:
                                            rec_videos = [v for v in rec_videos if v != video_path and v != to_rel_path(video_path, {"root": paths["root"]})]
                                            rec["videos"] = rec_videos
                                            save_index_v2(paths["index"], idx)
                                    st.success("Video gelöscht.")
                                safe_rerun()
                            except Exception as e:
                                st.error(f"Fehler beim Löschen: {e}")
                else:
                    st.warning(f"Video-Datei nicht gefunden: {os.path.basename(video_path)}")