# common.py

import os
import io
import json
import copy
import base64
import shutil
import math
import matplotlib.patheffects as pe
from datetime import date
from typing import Optional, List, Dict, Tuple, Any

from PIL import Image

from media_store import (
    MEDIA_BASE_IMAGES, MEDIA_BASE_VIDEOS, MEDIA_OVERLAYS, OVERLAY_FEHLERBILD,
    OVERLAY_KONTEXT, OVERLAY_NACHARBEIT, OVERLAY_ZUSATZ_FEHLER,
    OVERLAY_ZUSATZ_NACHARBEIT, JPEG_QUALITY_FULL,
    ensure_media_dirs, ensure_dirs_exist, sanitize_filename, decode_upload_to_pil,
    pil_to_jpg, generate_canvas_overlay_filename, get_overlay_path, is_overlay_ref,
    resolve_media_path, media_ref_from_global_path, attach_media, save_base_image,
    save_base_video, save_canvas_overlay, composite_base_with_overlay,
    delete_global_media, _compute_pil_hash, _save_media_registry, _compute_file_hash
)

from fpdf import FPDF
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ==== Constants & Configuration ==============================================

RODING_GREEN_RGB = (0, 204, 184)
EDITOR_BLUE_RGB = (30, 80, 110)

BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROJECTS_ROOT: str = os.path.join(BASE_DIR, "AuditProjects")
PDF_CACHE: str = os.path.join(BASE_DIR, "PDF_CACHE")

DEFAULT_DISPLAY_WIDTH: int = 900

BI_CATEGORIES: List[str] = [
    "BI0-tbd.", "BI1", "BI2", "BI3", "BI4", "BI5",
    "BI6-nein", "BI6", "BI6-ja", "BI7", "BI8",
]
BI_COLOR_MAP = {
    "BI0-tbd.": "#9E9E9E",   # Grey
    "BI1": "#D32F2F",        # Red
    "BI2": "#F57C00",        # Orange
    "BI3": "#FBC02D",        # Yellow
    "BI4": "#7CB342",        # Light Green
    "BI5": "#388E3C",        # Green
    "BI6-ja": "#0288D1",     # Blue
    "BI6": "#1976D2",        # Dark Blue
    "BI6-nein": "#455A64",   # Blue Grey
    "BI7": "#6A1B9A",        # Purple
    "BI8": "#512DA8",        # Deep Purple
}
PRIORITY_OPTIONS: List[str] = ["Niedrig", "Mittel", "Hoch"]
QZ_OPTIONS: List[str] = ["QZS", "QZF"]
FEHLERART_OPTIONS: List[str] = [
    "Beschädigung", "Optik/Erscheinungsbild", "Passungsfehler", "Fehlteil",
    "Montagefehler", "Lackfehler", "Funktion", "Geräusch",
]
DEFAULT_FONT_FALLBACK: Tuple[str, str] = ("Helvetica", "")
DEFAULT_UNICODE_FONT: Tuple[str, str] = ("DejaVu", "DejaVuSans.ttf")

# =============================================================================
# SORTING FRAMEWORK CONSTANTS (BMW-aligned)
# =============================================================================

VEHICLE_AREA_OPTIONS: List[str] = [
    "Front_Exterieur",
    "Rechte_Seite",
    "Heck_Exterieur",
    "Linke_Seite",
    "Dach",
    "Interieur_Vorne",
    "Interieur_Hinten",
    "Motorraum",
    "Unterboden",
]

VEHICLE_AREA_LABELS: Dict[str, str] = {
    "Front_Exterieur": "Front (Exterieur)",
    "Rechte_Seite": "Rechte Seite",
    "Heck_Exterieur": "Heck (Exterieur)",
    "Linke_Seite": "Linke Seite",
    "Dach": "Dach / Oberseite",
    "Interieur_Vorne": "Interieur Vorne",
    "Interieur_Hinten": "Interieur Hinten",
    "Motorraum": "Motorraum",
    "Unterboden": "Unterboden",
}

SYSTEM_DOMAIN_OPTIONS: List[str] = [
    "Karosserie",
    "Lack",
    "Exterieur",
    "Interieur",
    "Elektrik",
    "Antrieb",
    "Fahrwerk",
    "Software",
    "Sonstige",
]

SYSTEM_DOMAIN_LABELS: Dict[str, str] = {
    "Karosserie": "Karosserie / Struktur",
    "Lack": "Lack / Oberfläche",
    "Exterieur": "Exterieur-Umfänge",
    "Interieur": "Interieur-Umfänge",
    "Elektrik": "Elektrik / Elektronik",
    "Antrieb": "Antrieb",
    "Fahrwerk": "Fahrwerk",
    "Software": "Funktionen / Software",
    "Sonstige": "Sonstige",
}

def fehlerbild_sort_key(rec: dict) -> tuple:
    """
    (area_rank, domain_rank, bi_rank, status_rank, nr_int)
    """
    f = rec.get("fehler", {}) or {}

    # 1) Fahrzeugbereich
    area = f.get("vehicle_area", "Interieur_Vorne")
    try:
        area_rank = SORT_ORDER_VEHICLE_AREA.index(area)
    except ValueError:
        area_rank = len(SORT_ORDER_VEHICLE_AREA)

    # 2) System / Domäne
    domain = f.get("system_domain", "Sonstige")
    try:
        domain_rank = SORT_ORDER_SYSTEM_DOMAIN.index(domain)
    except ValueError:
        domain_rank = len(SORT_ORDER_SYSTEM_DOMAIN)

    # 3) BI (Audit)
    bi = f.get("BI_alt", "BI0-tbd.")
    try:
        bi_rank = SORT_ORDER_BI.index(bi)
    except ValueError:
        bi_rank = 0  # Unknown -> treat as unclassified

    # 4) Status
    status = f.get("CaseStatus", "Open")
    status_rank = 0 if status != "Closed" else 1

    # 5) Fehlerbild-Nummer
    nr_str = rec.get("nr", "999")
    try:
        nr_int = int(nr_str)
    except (ValueError, TypeError):
        nr_int = 9999

    return (area_rank, domain_rank, bi_rank, status_rank, nr_int)

def sort_fehlerbilder(records: List[dict]) -> List[dict]:
    """Return records sorted with the BMW Fehlerbild sort order."""
    return sorted(records, key=fehlerbild_sort_key)

# All available sorting modes - must match the Inhaltsangabe tab selectbox exactly
SORTING_MODE_OPTIONS: List[str] = [
    "Audit-Standard (Bereich → System → BI)",
    "Nr (aufsteigend)",
    "Nr (absteigend)",
    "BI (kritisch zuerst)",
    "BI (unkritisch zuerst)",
    "Fehlerort (A→Z)",
    "Fehlerort (Z→A)",
    "Status Open (zuerst)",
    "Status Closed (zuerst)",
    "Nacharbeit = Ja (zuerst)",
    "Nacharbeit = Nein (zuerst)",
]
DEFAULT_SORTING_MODE = "Audit-Standard (Bereich → System → BI)"

def sort_fehlerbilder_with_mode(records: List[dict], sorting_mode: str = None) -> List[dict]:
    """
    Sort Fehlerbilder records using the specified sorting mode.
    
    This function replicates the exact sorting logic used in the Inhaltsangabe tab,
    ensuring consistency between the UI view and the PDF export.
    
    Args:
        records: List of Fehlerbild dictionaries to sort
        sorting_mode: One of SORTING_MODE_OPTIONS, or None for default
        
    Returns:
        Sorted list of records (new list, original not modified)
    """
    if not records:
        return []
    
    # Default to the standard sorting mode if not specified
    if not sorting_mode:
        sorting_mode = DEFAULT_SORTING_MODE
    
    # Create a copy to avoid mutating the original list
    sorted_records = list(records)
    
    # Helper functions (same as in inhaltsangabe_visualization.py)
    def _nacharbeit_flag(rec):
        f = rec.get("fehler", {}) or {}
        return bool(f.get("Nacharbeit_done", False))
    
    def _status_flag(rec):
        f = rec.get("fehler", {}) or {}
        return f.get("CaseStatus", "Open")
    
    def _bi_index(rec):
        """
        Map BI (Audit) to a canonical sort index based on SORT_ORDER_BI.
        Falls back to 'BI0-tbd.' and then to the end of the list if unknown.
        """
        f = rec.get("fehler", {}) or {}
        bi = f.get("BI_alt") or f.get("BI") or "BI0-tbd."
        try:
            return SORT_ORDER_BI.index(bi)
        except ValueError:
            return len(SORT_ORDER_BI)
    
    # Apply sorting based on mode
    if sorting_mode == "Audit-Standard (Bereich → System → BI)":
        sorted_records.sort(key=fehlerbild_sort_key)
    elif sorting_mode == "Nr (aufsteigend)":
        sorted_records.sort(key=lambda r: r.get("nr", ""))
    elif sorting_mode == "Nr (absteigend)":
        sorted_records.sort(key=lambda r: r.get("nr", ""), reverse=True)
    elif sorting_mode == "BI (kritisch zuerst)":
        sorted_records.sort(key=_bi_index)
    elif sorting_mode == "BI (unkritisch zuerst)":
        sorted_records.sort(key=_bi_index, reverse=True)
    elif sorting_mode == "Fehlerort (A→Z)":
        sorted_records.sort(key=lambda r: (r.get("fehler", {}) or {}).get("Fehlerort", "").lower())
    elif sorting_mode == "Fehlerort (Z→A)":
        sorted_records.sort(key=lambda r: (r.get("fehler", {}) or {}).get("Fehlerort", "").lower(), reverse=True)
    elif sorting_mode == "Status (Open zuerst)":
        sorted_records.sort(key=lambda r: 0 if _status_flag(r) != "Closed" else 1)
    elif sorting_mode == "Status (Closed zuerst)":
        sorted_records.sort(key=lambda r: 0 if _status_flag(r) == "Closed" else 1)
    elif sorting_mode == "Nacharbeit = Ja zuerst":
        sorted_records.sort(key=lambda r: 0 if _nacharbeit_flag(r) else 1)
    elif sorting_mode == "Nacharbeit = Nein zuerst":
        sorted_records.sort(key=lambda r: 0 if not _nacharbeit_flag(r) else 1)
    else:
        # Unknown mode: fall back to default (hierarchical)
        sorted_records.sort(key=fehlerbild_sort_key)
    
    return sorted_records

# Canonical sort orders (indices used by fehlerbild_sort_key)
SORT_ORDER_VEHICLE_AREA: List[str] = VEHICLE_AREA_OPTIONS.copy()
SORT_ORDER_SYSTEM_DOMAIN: List[str] = SYSTEM_DOMAIN_OPTIONS.copy()

SORT_ORDER_BI: List[str] = [
    "BI0-tbd.",   # Unclassified – needs attention
    "BI1",        # Safety-critical
    "BI2",        # Breakdown
    "BI3",        # Severe functional
    "BI4",        # Medium functional
    "BI5",        # Minor functional
    "BI6-ja",     # Customer-relevant appearance
    "BI6",        # Standard appearance
    "BI6-nein",   # Not customer-relevant
    "BI7",        # Minor cosmetic
    "BI8",        # Minimal
]

# ==== String & Path Utilities =================================================

def sanitize(s: str) -> str:
    s = (s or "").strip()
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in s)

def sanitize_filename(s: str) -> str:
    s = (s or "").strip()
    bad = r'<>:"/\n?*\\'
    table = str.maketrans({ch: "_" for ch in bad})
    s = s.translate(table)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")

def ensure_dirs_exist(*paths: str) -> None:
    for p in paths:
        if p and not os.path.exists(p):
            os.makedirs(p, exist_ok=True)

def abs_fwd(p: str) -> str:
    return os.path.abspath(p).replace("\\", "/")

def datum_str(d: date) -> str:
    try:
        return d.strftime("%d-%m-%Y")
    except Exception:
        return str(d)
# =============================================================================
# IMAGE UTILITIES
# =============================================================================

def img_to_data_uri(abs_path: str, max_width: int = 900, quality: int = 85) -> Optional[str]:
    try:
        with Image.open(abs_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > max_width:
                im = im.resize((max_width, int(h * max_width / w)), Image.LANCZOS)
            bio = io.BytesIO()
            im.save(bio, format="JPEG", quality=quality, optimize=True)
            b64 = base64.b64encode(bio.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


ASSETS_DIR = os.path.join(BASE_DIR, "assets")

def resolve_wiigor_logo() -> Optional[str]:
    """Find WiiGoR logo - EXEMPT from global media migration."""
    if not os.path.isdir(ASSETS_DIR):
        return None
    candidates = ["WiiGoRLogo", "WiiGoRLogo.png", "WiiGoRLogo.jpg", "WiiGoR Logo.png", "WiiGoR Logo.jpg"]
    for name in candidates:
        path = os.path.join(ASSETS_DIR, name)
        if os.path.exists(path):
            return abs_fwd(path)
    try:
        for fn in os.listdir(ASSETS_DIR):
            if fn.lower().startswith("wiigorlogo"):
                path = os.path.join(ASSETS_DIR, fn)
                if os.path.isfile(path):
                    return abs_fwd(path)
    except Exception:
        pass
    try:
        for fn in os.listdir(ASSETS_DIR):
            if fn.lower().endswith((".png", ".jpg", ".jpeg")):
                path = os.path.join(ASSETS_DIR, fn)
                if os.path.isfile(path):
                    return abs_fwd(path)
    except Exception:
        pass
    return None

# =============================================================================
# Video Helpers
# =============================================================================

def get_display_name_for_record(rec: dict, project_id: str) -> str:
    """
    Get the display name for a record based on the canvas overlay name.
    This is used in UI to show the canvas-specific name, not the base image name.
    """
    audit_id = rec.get("audit_id", "AUDIT")
    nr = rec.get("nr", "000")
    return generate_canvas_overlay_filename(project_id, audit_id, nr, OVERLAY_FEHLERBILD)


def index_prefers_relative(index: dict) -> bool:
    """Always prefer relative in new architecture."""
    return True


def get_video_paths(paths: dict, audit_id: str) -> Dict[str, str]:
    ensure_media_dirs()
    return {
        "videos": MEDIA_BASE_VIDEOS, 
        "audit_root": os.path.join(paths.get("audits", ""), audit_id) if paths.get("audits") else ""
    }

def save_video_file(
    video_data: bytes, filename: str, index: dict, audit_id: str,
    project_paths: dict, prefer_relative: bool, record_nr: Optional[str] = None
) -> Optional[str]:
    """Save a video file using the new immutable naming scheme."""
    try:
        ensure_media_dirs()
        vid_filename, abs_path = save_base_video(video_data, filename)
        store_ref = f"base_videos/{vid_filename}"
        
        if record_nr:
            for rec in index.get("images", []):
                if rec.get("audit_id") == audit_id and rec.get("nr") == record_nr:
                    rec.setdefault("videos", [])
                    if store_ref not in rec["videos"]:
                        rec["videos"].append(store_ref)
                    break
        
        return abs_path
    except Exception as e:
        print(f"Error saving video file: {e}")
        return None

def get_videos_for_record(rec: dict, paths: dict) -> List[str]:
    video_paths = []
    if "videos" in rec:
        for video_ref in rec.get("videos", []):
            if video_ref:
                abs_path = resolve_media_path(video_ref, paths)
                if abs_path and os.path.exists(abs_path):
                    video_paths.append(abs_path)
    return video_paths

def link_existing_video_to_record(
    video_abs_path: str, index: dict, audit_id: str, project_paths: dict,
    prefer_relative: bool, record_nr: str, rename_to_canonical: bool = False
) -> Optional[str]:
    """
    Link an existing video to a record. 
    In new architecture, we do NOT rename base videos (they're immutable).
    """
    try:
        if not os.path.isabs(video_abs_path):
            video_abs_path = resolve_media_path(video_abs_path, project_paths)
        if not video_abs_path or not os.path.exists(video_abs_path):
            return None
        
        store_ref = media_ref_from_global_path(video_abs_path)
        
        for rec in index.get("images", []):
            if rec.get("audit_id") == audit_id and rec.get("nr") == record_nr:
                rec.setdefault("videos", [])
                if store_ref not in rec["videos"]:
                    rec["videos"].append(store_ref)
                break
        
        return video_abs_path
    except Exception:
        return None

# =============================================================================
# Index Schema & IO
# =============================================================================

def new_project_v2(project_id: str, vehicle: str, notes: str = "") -> dict:
    return {
        "schema_version": 3,  # Updated schema version for layered architecture
        "project": {"project_id": project_id, "vehicle": vehicle, "created_at": str(date.today()), "notes": notes},
        "audits": [], "images": [], "counters": {"images": 0},
    }

def ensure_v2_schema(data: dict) -> dict:
    if data.get("schema_version") in (2, 3) and "project" in data:
        return data
    basis = data.get("basis", {})
    vehicle = basis.get("Fahrzeug", "Unbekannt")
    auditor = basis.get("Auditor", "")
    datum = str(basis.get("Datum", "")) or str(date.today())
    project_id = f"veh__{sanitize(vehicle)}"
    v2 = new_project_v2(project_id, vehicle)
    audit_id = sanitize_filename(f"{datum}__Legacy__{auditor or 'NA'}")
    v2["audits"].append({"audit_id": audit_id, "type": "Legacy Import", "scope": "Internes Audit", "date": datum, "auditor": auditor, "notes": ""})
    imgs = data.get("images", [])
    for r in imgs:
        ensure_new_fields(r)
        r["audit_id"] = audit_id
    v2["images"] = imgs
    v2["counters"]["images"] = len(imgs)
    v2["schema_version"] = 3
    return v2

def project_paths_v2(project_id: str) -> Dict[str, str]:
    root = os.path.join(PROJECTS_ROOT, project_id)
    return {
        "root": root, 
        "audits": os.path.join(root, "audits"), 
        "index": os.path.join(root, "index.json"), 
        "bqp_measures": os.path.join(root, "BQP_MEASURES.json")
    }

def init_project_v2(project_id: str, vehicle: str) -> Dict[str, str]:
    prj = new_project_v2(project_id, vehicle)
    paths = project_paths_v2(project_id)
    ensure_dirs_exist(paths["root"], paths["audits"])
    ensure_media_dirs()
    with open(paths["index"], "w", encoding="utf-8") as f:
        json.dump(prj, f, ensure_ascii=False, indent=2)
    return paths

def load_index_v2(idx_path: str) -> dict:
    with open(idx_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ensure_v2_schema(data)

def save_index_v2(idx_path: str, data: dict) -> None:
    ensure_dirs_exist(os.path.dirname(idx_path))
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def create_audit(idx: dict, paths: dict, date_val: date, typ_txt: str, auditor: str, scope: str, notes: str = "") -> dict:
    audit_id = sanitize_filename(f"{datum_str(date_val)}__{sanitize(typ_txt) or 'Audit'}__{sanitize(auditor) or 'NA'}")
    a = {"audit_id": audit_id, "type": typ_txt, "scope": scope, "date": datum_str(date_val), "auditor": auditor, "notes": notes}
    idx.setdefault("audits", []).append(a)
    base = os.path.join(paths["audits"], audit_id)
    ensure_dirs_exist(base, os.path.join(base, "pdf"))
    ensure_media_dirs()
    return a

def _pick_dir(primary: str, *fallbacks: str) -> str:
    for p in (primary,) + fallbacks:
        if p and os.path.isdir(p):
            return p
    return primary

def audit_paths(paths: dict, audit_id: str) -> dict:
    audit_id = sanitize_filename(audit_id or "")
    base = os.path.join(paths["audits"], audit_id)
    in_root = os.path.join(base, "in")
    out_root = os.path.join(base, "out")
    raw_new = os.path.join(in_root, "raw")
    ctx_new = os.path.join(in_root, "context")
    add_new = os.path.join(in_root, "additional")
    after_new = os.path.join(in_root, "after")
    annotated_new = os.path.join(out_root, "annotated")
    raw_old = os.path.join(base, "RAW")
    edited_old = os.path.join(base, "EDITED")
    after_raw_old = os.path.join(base, "AFTER_RAW")
    after_edited_old = os.path.join(base, "AFTER_EDITED")
    add_raw_old = os.path.join(base, "ADD_RAW")
    add_edited_old = os.path.join(base, "ADD_EDITED")
    ensure_media_dirs()
    return {
        "root": paths["root"], "index": paths["index"], "in_root": in_root, "out_root": out_root,
        "raw": MEDIA_BASE_IMAGES, "edited": MEDIA_OVERLAYS, "after_raw": MEDIA_BASE_IMAGES,
        "after_edited": MEDIA_OVERLAYS, "add_raw": MEDIA_BASE_IMAGES, "add_edited": MEDIA_OVERLAYS,
        "after_add_raw": MEDIA_BASE_IMAGES, "after_add_edited": MEDIA_OVERLAYS, "context": MEDIA_BASE_IMAGES,
        "overlays": MEDIA_OVERLAYS,
        "legacy_raw": _pick_dir(raw_new, raw_old), "legacy_edited": _pick_dir(annotated_new, edited_old),
        "legacy_after_raw": _pick_dir(after_new, after_raw_old), "legacy_after_edited": _pick_dir(annotated_new, after_edited_old),
        "legacy_add_raw": _pick_dir(add_new, add_raw_old), "legacy_add_edited": _pick_dir(annotated_new, add_edited_old),
        "legacy_context": ctx_new, "thumbnails": os.path.join(out_root, "thumbnails"),
        "pdf_out": os.path.join(out_root, "pdf"), "videos": MEDIA_BASE_VIDEOS,
    }

# =============================================================================
# Finding Records & Field Normalization
# =============================================================================

def add_image_record(index: dict, raw_path: str, number: str) -> dict:
    """
    Add a new image record with the new layered architecture fields.
    Supports both legacy (raw/edited) and new (base_image/overlay) field names.
    """
    rec = {
        "nr": number, 
        # New layered fields
        "base_image": raw_path,
        "overlay": None, 
        # Legacy fields (for backward compatibility)
        "raw": raw_path, 
        "edited": None, 
        # After-work fields
        "after_base": None,
        "after_overlay": None,
        "after_raw": None, 
        "after_edited": None,
        # Lists
        "ctx_list": [], 
        "add_fehler_list": [], 
        "add_after_list": [],
        "videos": [],
        # Fehler data
        "fehler": {
            "Fehlerort": "", "Fehlerart": [], "BI_alt": "", "Fehlerbeschreibung": "",
            "Nacharbeit_done": False, "BI_neu": "", "Nacharbeitsmassnahme": "", "Kommentar_Nacharbeit": "",
            "CaseStatus": "Open", "Prioritaet": "Mittel", "RQMRelevant": False, "QZStatus": "QZS"
        },
    }
    index["images"].append(rec)
    return rec

def clone_image_to_audit(index: dict, source_rec: dict, target_audit_id: str) -> dict:
    """
    Clone an image record to another audit.
    In layered architecture: base image reference is SHARED, new overlay is created.
    """
    counters = index.setdefault("counters", {})
    cur = int(counters.get("images", 0)) + 1
    counters["images"] = cur
    new_nr = f"{cur:03d}"
    new_rec = copy.deepcopy(source_rec)
    new_rec["nr"] = new_nr
    new_rec["audit_id"] = target_audit_id
    new_rec["link_source"] = {"audit_id": source_rec.get("audit_id"), "nr": source_rec.get("nr")}
    
    # Reset overlay references (new record needs its own overlays)
    new_rec["overlay"] = None
    new_rec["after_overlay"] = None
    new_rec["edited"] = None  # Legacy
    new_rec["after_edited"] = None  # Legacy
    
    # Clear overlays in lists too
    for entry in new_rec.get("ctx_list", []) or []:
        entry["overlay"] = None
        entry["edited"] = None
    for entry in new_rec.get("add_fehler_list", []) or []:
        entry["overlay"] = None
        entry["edited"] = None
    for entry in new_rec.get("add_after_list", []) or []:
        entry["overlay"] = None
        entry["edited"] = None
    
    ensure_new_fields(new_rec)
    index.setdefault("images", []).append(new_rec)
    return new_rec

def _map_caseclosed_to_status(f: dict) -> None:
    if "CaseClosed" in f and "CaseStatus" not in f:
        f["CaseStatus"] = "Closed" if bool(f.get("CaseClosed")) else "Open"
    if "CaseStatus" not in f:
        f["CaseStatus"] = "Closed" if bool(f.get("CaseClosed")) else "Open"
    f["CaseClosed"] = (f.get("CaseStatus", "Open") == "Closed")

def ensure_new_fields(rec: dict) -> None:
    """Ensure all required fields exist in a record."""
    # ----------Fehler-Meta normalisieren---------------
    f = rec.get("fehler", {}) or {}
    if "BQPRelevant" in f and "RQMRelevant" not in f:
        f["RQMRelevant"] = bool(f.get("BQPRelevant"))
    f.setdefault("RQMRelevant", False)
    f.setdefault("BI_alt", f.get("Kategorie", ""))
    f.setdefault("Fehlerbeschreibung", f.get("Kommentar_Audit", ""))
    f.setdefault("Nacharbeit_done", False)
    f.setdefault("BI_neu", f.get("BI_alt", ""))
    f.setdefault("Nacharbeitsmassnahme", f.get("Massnahme", f.get("Massnahme_geplant", "")))
    f.setdefault("Kommentar_Nacharbeit", f.get("Nacharbeit", ""))
    f.setdefault("vehicle_area", "Interieur_Vorne")
    f.setdefault("system_domain", "Sonstige")


    _map_caseclosed_to_status(f)

    if f.get("Prioritaet") not in PRIORITY_OPTIONS:
        f["Prioritaet"] = "Mittel"
    f.setdefault("QZStatus", "QZS")

    val = f.get("Fehlerart", [])
    if isinstance(val, str):
        parts = [p.strip() for p in val.split(",") if p.strip()] if val else []
        f["Fehlerart"] = parts
    elif isinstance(val, list):
        f["Fehlerart"] = [str(p).strip() for p in val if str(p).strip()]
    else:
        f["Fehlerart"] = []
    f["Fehlerart"] = [x for x in f["Fehlerart"] if x in FEHLERART_OPTIONS]

    rec["fehler"] = f


    # ----------------Kern-Listen / Legacy-Felder (für After & Zusatzbilder)---------------
    rec.setdefault("ctx_list", [])
    rec.setdefault("after_raw", rec.get("after_raw"))
    rec.setdefault("after_edited", rec.get("after_edited"))
    rec.setdefault("add_fehler_list", rec.get("add_fehler_list", []))
    rec.setdefault("add_after_list", rec.get("add_after_list", []))
    rec.setdefault("videos", rec.get("videos", []))


    # -----------------NEW LAYERED FIELDS – Hauptbild + Nacharbeit------------------------
    # Haupt-Fehlerbild
    rec.setdefault("base_image", rec.get("raw"))
    rec.setdefault("overlay", rec.get("edited"))

    # Bild nach Nacharbeit
    rec.setdefault("after_base", rec.get("after_raw"))
    rec.setdefault("after_overlay", rec.get("after_edited"))

    # -------------------------------------------------------------------------
    # LAYERED-Topologie für Kontextbild + Zusatzbilder
    #  - Jedes Element hat base + overlay
    #  - raw/edited bleiben als Legacy-Alias erhalten
    # -------------------------------------------------------------------------

    # Kontextbild(er)
    ctx_list = rec.get("ctx_list") or []
    rec["ctx_list"] = ctx_list
    for entry in ctx_list:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("base", entry.get("raw"))
        entry.setdefault("overlay", entry.get("edited"))
        if entry.get("raw") is None and entry.get("base") is not None:
            entry["raw"] = entry["base"]
        if entry.get("edited") is None and entry.get("overlay") is not None:
            entry["edited"] = entry["overlay"]

    # Zusatzbilder (Fehlerbild)
    add_fehler_list = rec.get("add_fehler_list") or []
    rec["add_fehler_list"] = add_fehler_list
    for entry in add_fehler_list:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("base", entry.get("raw"))
        entry.setdefault("overlay", entry.get("edited"))
        if entry.get("raw") is None and entry.get("base") is not None:
            entry["raw"] = entry["base"]
        if entry.get("edited") is None and entry.get("overlay") is not None:
            entry["edited"] = entry["overlay"]

    # Zusatzbilder (Nacharbeit)
    add_after_list = rec.get("add_after_list") or []
    rec["add_after_list"] = add_after_list
    for entry in add_after_list:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("base", entry.get("raw"))
        entry.setdefault("overlay", entry.get("edited"))
        if entry.get("raw") is None and entry.get("base") is not None:
            entry["raw"] = entry["base"]
        if entry.get("edited") is None and entry.get("overlay") is not None:
            entry["edited"] = entry["overlay"]

# =============================================================================
# Overlay Save Helpers - NEW LAYERED ARCHITECTURE
# =============================================================================

def save_overlay_for_record(
    rec: dict, 
    overlay_rgba: Image.Image, 
    a_paths: dict,
    overlay_type: str = OVERLAY_FEHLERBILD
) -> str:
    """
    Save a canvas overlay for a record.
    Returns the overlay reference.
    """
    project_id = os.path.basename(a_paths["root"])
    audit_id = rec.get("audit_id", "AUDIT")
    nr = rec.get("nr", "000")
    filename, abs_path = save_canvas_overlay(
        overlay_rgba, project_id, audit_id, nr, overlay_type
    )
    overlay_ref = f"overlays/{filename}"

    if overlay_type == OVERLAY_FEHLERBILD:
        rec["overlay"] = overlay_ref
        rec["edited"] = overlay_ref
    elif overlay_type == OVERLAY_NACHARBEIT:
        rec["after_overlay"] = overlay_ref
        rec["after_edited"] = overlay_ref
    
    return overlay_ref

def save_annotated_as_edited(rec: dict, overlay_rgba: Image.Image, a_paths: dict) -> None:
    """Save overlay for main Fehlerbild (legacy compatible function name)."""
    save_overlay_for_record(rec, overlay_rgba, a_paths, OVERLAY_FEHLERBILD)

def save_after_annotated(rec: dict, overlay_rgba: Image.Image, a_paths: dict) -> None:
    """Save overlay for Nacharbeit image (legacy compatible function name)."""
    save_overlay_for_record(rec, overlay_rgba, a_paths, OVERLAY_NACHARBEIT)

def save_ctx_annotated_index(rec: dict, ctx_index: int, annotated_rgba: Image.Image, a_paths: dict) -> None:
    """Save overlay for a context image."""
    if ctx_index < 0 or ctx_index >= len(rec.get("ctx_list", [])):
        return
    entry = rec["ctx_list"][ctx_index]
    project_id = os.path.basename(a_paths["root"])
    audit_id = rec.get("audit_id", "AUDIT")
    nr = rec.get("nr", "000")
    
    filename, abs_path = save_canvas_overlay(
        annotated_rgba, project_id, audit_id, nr, OVERLAY_KONTEXT, index=ctx_index+1
    )
    
    overlay_ref = f"overlays/{filename}"
    entry["overlay"] = overlay_ref
    entry["edited"] = overlay_ref

def save_additional_annotated_index(rec: dict, idx_sel: int, annotated_rgba: Image.Image, a_paths: dict, phase: str = "FEHLER") -> None:
    """Save overlay for an additional image."""
    if phase.upper() == "FEHLER":
        lst = rec.get("add_fehler_list", [])
        overlay_type = OVERLAY_ZUSATZ_FEHLER
    else:
        lst = rec.get("add_after_list", [])
        overlay_type = OVERLAY_ZUSATZ_NACHARBEIT
    
    if idx_sel < 0 or idx_sel >= len(lst):
        return
    
    entry = lst[idx_sel]
    project_id = os.path.basename(a_paths["root"])
    audit_id = rec.get("audit_id", "AUDIT")
    nr = rec.get("nr", "000")
    
    filename, abs_path = save_canvas_overlay(
        annotated_rgba, project_id, audit_id, nr, overlay_type, index=idx_sel+1
    )
    
    overlay_ref = f"overlays/{filename}"
    entry["overlay"] = overlay_ref
    entry["edited"] = overlay_ref

def save_overlay_on_source(source_abs: str, overlay_rgba: Image.Image, out_abs: str) -> None:
    """Legacy function - composites and saves to disk (for PDF export compatibility)."""
    ensure_dirs_exist(os.path.dirname(out_abs))
    with Image.open(source_abs) as raw_im:
        raw_rgba = raw_im.convert("RGBA")
        overlay_resized = overlay_rgba.resize(raw_rgba.size, Image.BILINEAR)
        composited = Image.alpha_composite(raw_rgba, overlay_resized).convert("RGB")
        pil_to_jpg(composited, out_abs, JPEG_QUALITY_FULL)

# =============================================================================
# Get Composite Image (for display and export)
# =============================================================================

def get_composite_image_for_record(rec: dict, paths: dict, image_type: str = "main") -> Optional[Image.Image]:
    """
    Get the composited image (base + overlay) for display or export.
    image_type: 'main', 'after', 'ctx', 'add_fehler', 'add_after'
    Returns PIL Image (RGB) or None.
    """
    if image_type == "main":
        base_ref = rec.get("base_image") or rec.get("raw")
        overlay_ref = rec.get("overlay") or rec.get("edited")
    elif image_type == "after":
        base_ref = rec.get("after_base") or rec.get("after_raw")
        overlay_ref = rec.get("after_overlay") or rec.get("after_edited")
    else:
        return None
    
    base_path = resolve_media_path(base_ref, paths)
    overlay_path = resolve_media_path(overlay_ref, paths) if overlay_ref else None
    
    return composite_base_with_overlay(base_path, overlay_path)

def get_display_image_path(rec: dict, paths: dict, use_edited: bool = True) -> Optional[str]:
    """
    Get the path to display for a record.
    In layered architecture, we need to composite on-the-fly or use cached composite.
    For now, returns the base image path (overlay compositing done in display code).
    """
    base_ref = rec.get("base_image") or rec.get("raw")
    return resolve_media_path(base_ref, paths)

# =============================================================================
# Context & Additional Images
# =============================================================================

def attach_context_images(files, rec: dict, a_paths: dict, index: dict = None) -> None:
    """Attach context images to a record with deduplication, replacing any existing ones."""
    if not files:
        return
    
    # Delete old overlays (not base images - they might be shared)
    for entry in rec.get("ctx_list", []):
        overlay_ref = entry.get("overlay") or entry.get("edited")
        if overlay_ref and is_overlay_ref(overlay_ref):
            delete_global_media(overlay_ref)
    
    rec["ctx_list"] = []
    f = files[0]
    
    # Use attach_media for deduplication
    ref = attach_media(uploaded_file=f, media_type="image")
    if ref:
        rec.setdefault("ctx_list", []).append({
            "base": ref,
            "overlay": None,
            "raw": ref,
            "edited": None
        })

def attach_additional_images(files, rec: dict, a_paths: dict, phase: str = "FEHLER") -> None:
    """Attach additional images to a record with deduplication."""
    if not files:
        return
    
    if phase.upper() == "FEHLER":
        lst = rec.setdefault("add_fehler_list", [])
    else:
        lst = rec.setdefault("add_after_list", [])
    
    for f in files:
        # Use attach_media for deduplication
        ref = attach_media(uploaded_file=f, media_type="image")
        if ref:
            lst.append({
                "base": ref,
                "overlay": None,
                "raw": ref, 
                "edited": None
            })

def detach_context_image(rec: dict, ctx_index: int = None, a_paths: dict = None, index: dict = None) -> None:
    """Detach context image(s) from a record. Only deletes overlays, not base images."""
    if ctx_index is None:
        for entry in rec.get("ctx_list", []):
            overlay_ref = entry.get("overlay") or entry.get("edited")
            if overlay_ref and is_overlay_ref(overlay_ref):
                delete_global_media(overlay_ref)
        rec["ctx_list"] = []
        return
    
    if 0 <= ctx_index < len(rec.get("ctx_list", [])):
        entry = rec["ctx_list"][ctx_index]
        overlay_ref = entry.get("overlay") or entry.get("edited")
        if overlay_ref and is_overlay_ref(overlay_ref):
            delete_global_media(overlay_ref)
        try:
            del rec["ctx_list"][ctx_index]
        except Exception:
            pass

def detach_additional_image(rec: dict, idx_sel: int, a_paths: dict, phase: str = "FEHLER", index: dict = None) -> None:
    """Detach additional image from a record. Only deletes overlays, not base images."""
    phase_up = str(phase or "FEHLER").upper()
    lst = rec.get("add_fehler_list" if phase_up == "FEHLER" else "add_after_list", [])
    if not (0 <= idx_sel < len(lst)):
        return
    
    entry = lst[idx_sel]
    overlay_ref = entry.get("overlay") or entry.get("edited")
    if overlay_ref and is_overlay_ref(overlay_ref):
        delete_global_media(overlay_ref)
    
    try:
        del lst[idx_sel]
    except Exception:
        pass
    
    if phase_up == "FEHLER":
        rec["add_fehler_list"] = lst
    else:
        rec["add_after_list"] = lst

# =============================================================================
# RAW Scan & Index
# =============================================================================

def scan_raw_and_index(paths: dict, active_audit_id: str) -> int:
    idx = load_index_v2(paths["index"])
    a_paths = audit_paths(paths, active_audit_id)
    legacy_dirs = [
        a_paths.get("legacy_raw"), 
        os.path.join(paths["audits"], active_audit_id, "RAW"), 
        os.path.join(paths["audits"], active_audit_id, "in", "raw")
    ]
    
    known_basenames = set()
    for r in idx.get("images", []):
        raw_p = r.get("base_image") or r.get("raw")
        if raw_p:
            raw_abs = resolve_media_path(raw_p, paths)
            if raw_abs:
                known_basenames.add(os.path.basename(raw_abs))
    
    new_count = 0
    
    for raw_dir in legacy_dirs:
        if not raw_dir or not os.path.isdir(raw_dir):
            continue
        for fn in sorted(os.listdir(raw_dir)):
            ext = os.path.splitext(fn.lower())[1]
            if ext not in (".jpg", ".jpeg", ".png", ".heic"):
                continue
            abs_in = os.path.join(raw_dir, fn)
            
            if ext == ".heic":
                with open(abs_in, "rb") as f:
                    pil = decode_upload_to_pil(f.read(), fn)
                idx["counters"]["images"] += 1
                nr = f"{idx['counters']['images']:03d}"
                filename, new_abs = save_base_image(pil, ".jpg")
                base_ref = f"base_images/{filename}"
            else:
                if os.path.basename(abs_in) in known_basenames:
                    continue
                idx["counters"]["images"] += 1
                nr = f"{idx['counters']['images']:03d}"

                with open(abs_in, "rb") as f:
                    pil = Image.open(f).convert("RGB")
                filename, new_abs = save_base_image(pil, ext)
                base_ref = f"base_images/{filename}"
            
            rec = add_image_record(idx, base_ref, nr)
            rec["audit_id"] = active_audit_id
            ensure_new_fields(rec)
            new_count += 1
    
    if new_count > 0:
        save_index_v2(paths["index"], idx)
    return new_count

# =============================================================================
# Charts
# =============================================================================

def save_pie_chart_square(path: str, counts: Dict[str, int], title: str) -> None:
    """
    Render a square BI pie chart with robust percentage labels:
    - Large slices: percent label inside wedge with contrast-aware color + outline
    - Small slices: percent label outside with leader line and anti-overlap spacing
    """
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    labels = [k if k else "—" for k, _ in sorted_items]
    sizes = [v for _, v in sorted_items]

    fig, ax = plt.subplots(figsize=(8.0, 8.0), dpi=220)

    if not sizes or sum(sizes) == 0:
        ax.text(0.5, 0.5, "Keine Daten", ha="center", va="center", fontsize=22)
        ax.axis("off")
        fig.tight_layout()
        ensure_dirs_exist(os.path.dirname(path))
        fig.savefig(path, bbox_inches="tight", dpi=220)
        plt.close(fig)
        return

    # --- Styling knobs (tuned for your PDF size) ---
    MIN_PCT_SHOW = 1.5          # below this: hide label entirely (reduces clutter)
    INSIDE_PCT_THRESHOLD = 8.0  # at/above this: label inside wedge
    OUT_R = 1.22                # outside label radius
    LINE_R = 1.02               # leader line start radius
    MIN_DY = 0.09               # minimum vertical separation (in pie radius units)

    colors = [BI_COLOR_MAP.get(lbl, "#BDBDBD") for lbl in labels]

    wedges, _texts = ax.pie(
        sizes,
        labels=None,
        startangle=90,
        colors=colors,
        radius=1.0,
        explode=[0.02] * len(sizes),
        wedgeprops={"linewidth": 1.2, "edgecolor": "white"},
    )

    total = float(sum(sizes))
    MIN_PCT_INSIDE = 8.0

    # Helper: choose black/white depending on wedge brightness
    def _best_text_color(rgb):
        r, g, b = rgb
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return "black" if lum > 0.62 else "white"

    for w, size in zip(wedges, sizes):
        pct = (size / total) * 100.0
        if pct < MIN_PCT_INSIDE:
            continue  # small slice -> no label (legend is enough)

        ang = (w.theta1 + w.theta2) / 2.0
        rad = math.radians(ang)
        x = math.cos(rad)
        y = math.sin(rad)

        fc = w.get_facecolor()  # RGBA in 0..1
        rgb = (fc[0], fc[1], fc[2])
        txt_color = _best_text_color(rgb)

        t = ax.text(
            0.62 * x,
            0.62 * y,
            f"{pct:.1f}%",
            ha="center",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=txt_color,
            zorder=5,
        )

        t.set_path_effects([
            pe.withStroke(linewidth=3.2, foreground=("black" if txt_color == "white" else "white"))
        ])

        # Legend (keep your existing structure, but it remains readable and separate)
        legend_labels = [
            f"{label}: {size} ({(size/total)*100:.1f}%)"
            for label, size in zip(labels, sizes)
        ]
    ax.legend(
        legend_labels,
        loc="center left",
        bbox_to_anchor=(1.05, 0.5),
        fontsize=16,
        frameon=True,
        fancybox=True,
        shadow=True,
        title="BI-Kategorien",
        title_fontsize=18,
    )

    ax.set_title(title, fontsize=20, weight="bold", pad=30)
    ax.axis("equal")
    ax.set_aspect("equal", adjustable="box")

    fig.tight_layout()
    ensure_dirs_exist(os.path.dirname(path))
    fig.savefig(path, bbox_inches="tight", dpi=220)
    plt.close(fig)

# =============================================================================
# PDF Helpers
# =============================================================================

class PDFU(FPDF):
    def __init__(self):
        super().__init__(orientation="L")
        self.set_auto_page_break(auto=True, margin=15)
        self._unicode = False
        try:
            self.add_font(DEFAULT_UNICODE_FONT[0], "", DEFAULT_UNICODE_FONT[1], uni=True)
            self.add_font(DEFAULT_UNICODE_FONT[0], "B", DEFAULT_UNICODE_FONT[1], uni=True)
            self._unicode = True
        except Exception:
            self._unicode = False

    def set_u(self, style: str = "", size: int = 12):
        if self._unicode:
            self.set_font(DEFAULT_UNICODE_FONT[0], style, size)
        else:
            self.set_font(DEFAULT_FONT_FALLBACK[0], style, size)

    def safe(self, s: Any) -> str:
        if self._unicode:
            return str(s)
        return str(s).encode("latin-1", "replace").decode("latin-1")

def wrap_text(pdf: FPDF, text: str, width: float) -> List[str]:
    if not text:
        return [""]
    words = str(text).split()
    lines, line = [], ""
    for w in words:
        test = w if line == "" else f"{line} {w}"
        if pdf.get_string_width(test) <= width:
            line = test
        else:
            lines.append(line if line else w)
            line = w
    if line != "":
        lines.append(line)
    return lines or [""]

def draw_table_text_row(pdf: PDFU, label: str, value: str, label_w: float, value_w: float, line_h: float = 6.5) -> None:
    x_start, y_start = pdf.get_x(), pdf.get_y()
    if y_start + line_h > pdf.page_break_trigger:
        pdf.add_page()
        x_start, y_start = pdf.get_x(), pdf.get_y()
    pdf.set_u("B", 10)
    label_lines = wrap_text(pdf, label, label_w - 2)
    pdf.set_u("", 10)
    value_lines = wrap_text(pdf, value or "", value_w - 2)
    max_lines = max(len(label_lines), len(value_lines))
    row_h = max_lines * line_h
    if y_start + row_h > pdf.page_break_trigger:
        pdf.add_page()
        x_start, y_start = pdf.get_x(), pdf.get_y()
    prev_bm = getattr(pdf, "b_margin", 15)
    prev_ap = getattr(pdf, "auto_page_break", True)
    pdf.set_auto_page_break(False)
    try:
        pdf.rect(x_start, y_start, label_w, row_h)
        pdf.set_xy(x_start + 1, y_start + 1)
        pdf.set_u("B", 10)
        pdf.multi_cell(label_w - 2, line_h, pdf.safe("\n".join(label_lines)), border=0)
        pdf.rect(x_start + label_w, y_start, value_w, row_h)
        pdf.set_xy(x_start + label_w + 1, y_start + 1)
        pdf.set_u("", 10)
        pdf.multi_cell(value_w - 2, line_h, pdf.safe("\n".join(value_lines)), border=0)
        pdf.set_xy(x_start, y_start + row_h)
    finally:
        pdf.set_auto_page_break(prev_ap, prev_bm)

def draw_bi_table_absolute(
    pdf: PDFU, title: str, counts: Dict[str, int], x: float, y: float, w: float,
    line_h: float = 5.5, header_h: float = 5.5, title_h: float = 6.0, pad: float = 1.0
) -> float:
    prev_auto = getattr(pdf, "auto_page_break", True)
    prev_margin = getattr(pdf, "b_margin", 15)
    pdf.set_auto_page_break(auto=False)
    try:
        pdf.set_u("B", 10)
        pdf.set_xy(x, y)
        pdf.cell(w, title_h, pdf.safe(title), ln=False)
        y_cur = y + title_h
        c1_w, c2_w = w * 0.65, w * 0.35
        pdf.rect(x, y_cur, c1_w, header_h)
        pdf.rect(x + c1_w, y_cur, c2_w, header_h)
        pdf.set_u("B", 9)
        pdf.set_xy(x + pad, y_cur + (header_h - line_h) / 2.0)
        pdf.cell(c1_w - 2 * pad, line_h, pdf.safe("Kategorie"), ln=False)
        pdf.set_xy(x + c1_w + pad, y_cur + (header_h - line_h) / 2.0)
        pdf.cell(c2_w - 2 * pad, line_h, pdf.safe("Anzahl"), ln=False)
        pdf.set_u("", 9)
        y_cur += header_h
        
        def sort_bi_key(k):
            if not k:
                return (999, "")
            k_lower = k.lower()
            if k_lower.startswith("bi"):
                try:
                    num = int(k_lower[2:].split("-")[0].split("_")[0])
                    return (num, k)
                except ValueError:
                    pass
            return (100, k)
        
        sorted_cats = sorted(counts.keys(), key=sort_bi_key)
        for cat in sorted_cats:
            cnt = counts[cat]
            pdf.rect(x, y_cur, c1_w, line_h)
            pdf.rect(x + c1_w, y_cur, c2_w, line_h)
            pdf.set_xy(x + pad, y_cur)
            pdf.cell(c1_w - 2 * pad, line_h, pdf.safe(cat or "—"), ln=False)
            pdf.set_xy(x + c1_w + pad, y_cur)
            pdf.cell(c2_w - 2 * pad, line_h, pdf.safe(str(cnt)), ln=False)
            y_cur += line_h
        
        return y_cur - y
    finally:
        pdf.set_auto_page_break(prev_auto, prev_margin)

# =============================================================================
# Sanitize Audit Folder Names
# =============================================================================

def sanitize_audit_folder_names(paths: dict, idx: dict) -> None:
    audits_root = paths.get("audits", "")
    if not os.path.isdir(audits_root):
        return
    changed_map = {}
    for name in os.listdir(audits_root):
        old = os.path.join(audits_root, name)
        if not os.path.isdir(old):
            continue
        safe = sanitize_filename(name)
        if safe != name:
            new = os.path.join(audits_root, safe)
            try:
                os.rename(old, new)
                changed_map[name] = safe
            except Exception:
                pass
    if changed_map:
        for a in idx.get("audits", []):
            if a.get("audit_id") in changed_map:
                a["audit_id"] = changed_map[a["audit_id"]]
        for r in idx.get("images", []):
            if r.get("audit_id") in changed_map:
                r["audit_id"] = changed_map[r["audit_id"]]
        save_index_v2(paths["index"], idx)

# =============================================================================
# Reindex Audit Images -LAYERED ARCHITECTURE
# =============================================================================

def reindex_audit_images(index: dict, audit_id: str, paths: dict, prefer_relative: bool = True) -> Tuple[int, List[str]]:
    """
    Reindex all Fehlerbilder for a given audit.
    
    CRITICAL RULES (Layered Architecture):
    - Base images (MEDIA_IMG__*) are NEVER renamed
    - Base videos (MEDIA_VID__*) are NEVER renamed
    - ONLY canvas overlays (CANVAS__*) are renamed to reflect new numbering
    """
    errors = []
    audit_images = [r for r in index.get("images", []) if r.get("audit_id") == audit_id]
    if not audit_images:
        return (0, ["Keine Fehlerbilder in diesem Audit gefunden."])
    
    audit_images.sort(key=lambda r: r.get("nr", "999"))
    project_id = index.get("project", {}).get("project_id", "PROJ")
    
    def rename_overlay(old_ref: str, new_nr: str, overlay_type: str, idx: Optional[int] = None) -> Optional[str]:
        """Rename an overlay file to match new numbering."""
        if not old_ref:
            return None
        
        # Only rename overlays, not base images
        if not is_overlay_ref(old_ref):
            return old_ref
        
        old_abs = resolve_media_path(old_ref, paths)
        if not old_abs or not os.path.exists(old_abs):
            return old_ref
        
        # Generate new overlay filename
        new_filename = generate_canvas_overlay_filename(project_id, audit_id, new_nr, overlay_type, idx)
        new_abs = get_overlay_path(new_filename)
        
        if os.path.normpath(old_abs) == os.path.normpath(new_abs):
            return f"overlays/{new_filename}"
        
        # Handle collision
        if os.path.exists(new_abs):
            counter = 1
            base, ext = os.path.splitext(new_abs)
            while os.path.exists(new_abs):
                new_abs = f"{base}_{counter}{ext}"
                counter += 1
            new_filename = os.path.basename(new_abs)
        
        try:
            ensure_dirs_exist(os.path.dirname(new_abs))
            shutil.move(old_abs, new_abs)
            return f"overlays/{new_filename}"
        except Exception as e:
            errors.append(f"Overlay rename error: {e}")
            return old_ref
    
    def rename_overlays_in_list(items: list, new_nr: str, overlay_type: str) -> None:
        """Rename overlays in ctx_list, add_fehler_list, etc."""
        if not items:
            return
        for i, item in enumerate(items, 1):
            # Only rename overlays, keep base references unchanged
            overlay_ref = item.get("overlay") or item.get("edited")
            if overlay_ref:
                new_ref = rename_overlay(overlay_ref, new_nr, overlay_type, i)
                item["overlay"] = new_ref
                item["edited"] = new_ref 
    
    # Pass 1: Rename to temporary names to avoid collisions
    for i, rec in enumerate(audit_images):
        temp_nr = f"_TMP_{i:03d}"
        
        # Rename main overlay
        overlay_ref = rec.get("overlay") or rec.get("edited")
        if overlay_ref:
            new_ref = rename_overlay(overlay_ref, temp_nr, OVERLAY_FEHLERBILD)
            rec["overlay"] = new_ref
            rec["edited"] = new_ref
        
        # Rename after overlay
        after_overlay = rec.get("after_overlay") or rec.get("after_edited")
        if after_overlay:
            new_ref = rename_overlay(after_overlay, temp_nr, OVERLAY_NACHARBEIT)
            rec["after_overlay"] = new_ref
            rec["after_edited"] = new_ref
        
        # Rename overlays in lists
        rename_overlays_in_list(rec.get("ctx_list"), temp_nr, OVERLAY_KONTEXT)
        rename_overlays_in_list(rec.get("add_fehler_list"), temp_nr, OVERLAY_ZUSATZ_FEHLER)
        rename_overlays_in_list(rec.get("add_after_list"), temp_nr, OVERLAY_ZUSATZ_NACHARBEIT)
    
    # Pass 2: Rename to final numbers
    for i, rec in enumerate(audit_images):
        new_nr = f"{i + 1:03d}"
        
        # Rename main overlay
        overlay_ref = rec.get("overlay") or rec.get("edited")
        if overlay_ref:
            new_ref = rename_overlay(overlay_ref, new_nr, OVERLAY_FEHLERBILD)
            rec["overlay"] = new_ref
            rec["edited"] = new_ref
        
        # Rename after overlay
        after_overlay = rec.get("after_overlay") or rec.get("after_edited")
        if after_overlay:
            new_ref = rename_overlay(after_overlay, new_nr, OVERLAY_NACHARBEIT)
            rec["after_overlay"] = new_ref
            rec["after_edited"] = new_ref
        
        # Rename overlays in lists
        rename_overlays_in_list(rec.get("ctx_list"), new_nr, OVERLAY_KONTEXT)
        rename_overlays_in_list(rec.get("add_fehler_list"), new_nr, OVERLAY_ZUSATZ_FEHLER)
        rename_overlays_in_list(rec.get("add_after_list"), new_nr, OVERLAY_ZUSATZ_NACHARBEIT)
        
        # Update record number
        rec["nr"] = new_nr
    
    return (len(audit_images), errors)

# =============================================================================
# Migration Helper
# =============================================================================

def migrate_to_layered_architecture(paths: dict, index: dict) -> Tuple[int, List[str]]:
    """
    Migrate existing data to the new layered architecture.
    
    This function:
    1. Converts legacy 'raw'/'edited' references to 'base_image'/'overlay'
    2. Moves baked edited images to separate overlay files (if possible)
    3. Updates index references
    """
    migrated = 0
    errors = []
    
    for rec in index.get("images", []):
        try:
            # Migrate main image
            if rec.get("raw") and not rec.get("base_image"):
                rec["base_image"] = rec["raw"]
                migrated += 1
            
            if rec.get("edited") and not rec.get("overlay"):
                rec["overlay"] = rec["edited"]
            
            # Migrate after image
            if rec.get("after_raw") and not rec.get("after_base"):
                rec["after_base"] = rec["after_raw"]
                migrated += 1
            
            if rec.get("after_edited") and not rec.get("after_overlay"):
                rec["after_overlay"] = rec["after_edited"]
            
            # Migrate ctx_list
            for entry in rec.get("ctx_list", []) or []:
                if entry.get("raw") and not entry.get("base"):
                    entry["base"] = entry["raw"]
                if entry.get("edited") and not entry.get("overlay"):
                    entry["overlay"] = entry["edited"]
            
            # Migrate add_fehler_list
            for entry in rec.get("add_fehler_list", []) or []:
                if entry.get("raw") and not entry.get("base"):
                    entry["base"] = entry["raw"]
                if entry.get("edited") and not entry.get("overlay"):
                    entry["overlay"] = entry["edited"]
            
            # Migrate add_after_list
            for entry in rec.get("add_after_list", []) or []:
                if entry.get("raw") and not entry.get("base"):
                    entry["base"] = entry["raw"]
                if entry.get("edited") and not entry.get("overlay"):
                    entry["overlay"] = entry["edited"]
                    
        except Exception as e:
            errors.append(f"Migration error for record {rec.get('nr')}: {e}")
    
    return (migrated, errors)


# =============================================================================
# Build Registry from Existing Files (for migration)
# =============================================================================

def rebuild_media_registry() -> Tuple[int, int]:
    """
    Rebuild the media registry from existing files in base_images and base_videos.
    Useful for initial migration or if registry is corrupted.
    
    This scans all existing files and creates hash entries for deduplication.
    Run once after deployment to enable dedup for existing files.
    
    Returns (images_count, videos_count).
    """
    ensure_media_dirs()
    registry = {"images": {}, "videos": {}}
    img_count = 0
    vid_count = 0
    
    # Scan base_images
    if os.path.isdir(MEDIA_BASE_IMAGES):
        for fn in os.listdir(MEDIA_BASE_IMAGES):
            ext = os.path.splitext(fn.lower())[1]
            if ext in (".jpg", ".jpeg", ".png"):
                abs_path = os.path.join(MEDIA_BASE_IMAGES, fn)
                try:
                    with Image.open(abs_path) as img:
                        content_hash = _compute_pil_hash(img)
                        ref = f"base_images/{fn}"
                        # Only add if this hash doesn't exist yet (keep first file)
                        if content_hash not in registry["images"]:
                            registry["images"][content_hash] = ref
                            img_count += 1
                except Exception:
                    pass
    
    # Scan base_videos
    if os.path.isdir(MEDIA_BASE_VIDEOS):
        for fn in os.listdir(MEDIA_BASE_VIDEOS):
            ext = os.path.splitext(fn.lower())[1]
            if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
                abs_path = os.path.join(MEDIA_BASE_VIDEOS, fn)
                try:
                    with open(abs_path, "rb") as f:
                        content_hash = _compute_file_hash(f.read())
                        ref = f"base_videos/{fn}"
                        if content_hash not in registry["videos"]:
                            registry["videos"][content_hash] = ref
                            vid_count += 1
                except Exception:
                    pass
    
    _save_media_registry(registry)
    return (img_count, vid_count)