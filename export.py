# export.py
# =============================================================================
# PDF EXPORT MODULE - v2.0 (Enhanced with Bereich/System fields)
# =============================================================================
# Updates:
# - Added vehicle_area (Fahrzeugbereich) and system_domain (System/Domäne) fields
# - Enhanced Kapitel 2 table with new columns
# - Enhanced Kapitel 3 pages with full metadata display
# - Uses sort_fehlerbilder_with_mode for consistent sorting
# =============================================================================

import os
import io
import math
from functools import lru_cache
from typing import List, Dict, Optional, Tuple
from PIL import Image

from common import (
    PDFU,
    abs_fwd,
    save_pie_chart_square,
    draw_bi_table_absolute,
    ensure_new_fields,
    pil_to_jpg,
    resolve_media_path,
    composite_base_with_overlay,
    ensure_dirs_exist,
    sort_fehlerbilder_with_mode, 
    RODING_GREEN_RGB, EDITOR_BLUE_RGB, PDF_CACHE,
    VEHICLE_AREA_LABELS, SYSTEM_DOMAIN_LABELS,
)
from media_store import (
    to_abs_path
)

# ==============================================================================================
# Tunable layout knobs
# ==============================================================================================
K2_INFO_HEADER_GAP_MM = 2.0

# ==============================================================================================
# LAYERED ARCHITECTURE: Helper for composited image rendering
# ==============================================================================================

def _get_composite_path_for_record(rec: dict, paths: dict, field_type: str = "main") -> Optional[str]:
    """
    Get the path for a composited image for PDF rendering.
    """
    if field_type == "main":
        base_ref = rec.get("base_image") or rec.get("raw")
        overlay_ref = rec.get("overlay") or rec.get("edited")
        edited_ref = rec.get("edited")

        if edited_ref and not edited_ref.startswith("overlays/") and not edited_ref.startswith("CANVAS__"):
            abs_path = resolve_media_path(edited_ref, paths)
            if abs_path and os.path.exists(abs_path):
                return abs_path
            
    elif field_type == "after":
        base_ref = rec.get("after_base") or rec.get("after_raw")
        overlay_ref = rec.get("after_overlay") or rec.get("after_edited")
        after_edited = rec.get("after_edited")

        if after_edited and not after_edited.startswith("overlays/") and not after_edited.startswith("CANVAS__"):
            abs_path = resolve_media_path(after_edited, paths)
            if abs_path and os.path.exists(abs_path):
                return abs_path
            
    elif field_type == "ctx":
        base_ref = rec.get("base") or rec.get("raw")
        overlay_ref = rec.get("overlay") or rec.get("edited")
        edited_ref = rec.get("edited")

        if edited_ref and not edited_ref.startswith("overlays/") and not edited_ref.startswith("CANVAS__"):
            abs_path = resolve_media_path(edited_ref, paths)
            if abs_path and os.path.exists(abs_path):
                return abs_path
    else:
        return None
    
    base_abs = resolve_media_path(base_ref, paths) if base_ref else None
    overlay_abs = resolve_media_path(overlay_ref, paths) if overlay_ref else None
    
    if not base_abs or not os.path.exists(base_abs):
        return None
    
    if not overlay_abs or not os.path.exists(overlay_abs):
        return base_abs
    
    composite_img = composite_base_with_overlay(base_abs, overlay_abs)
    if composite_img is None:
        return base_abs
    
    import hashlib
    cache_key = hashlib.md5(f"{base_abs}:{overlay_abs}".encode()).hexdigest()
    temp_path = os.path.join(PDF_CACHE, f"composite_{cache_key}.jpg")
    ensure_dirs_exist(PDF_CACHE)
    
    if not os.path.exists(temp_path):
        pil_to_jpg(composite_img, temp_path, 95)
    
    return temp_path

# ==============================================================================================
# Layout constants
# ==============================================================================================
K3_LABEL_PT = 7.0
K3_VALUE_MAX_PT = 7.0
K3_VALUE_GAP_PT = 2.0
K3_METADATA_BOX_H_MM = 12.0
K3_FLOW_GAP_PT = 1.0
K3_FLOW_LINE_H_MM = 4.6
K3_FLOW_MIN_H_MM = 11.0
K3_FLOW_MAX_H_MM = 18.0
K3_BOX_TOP_PAD_MM = 1.0
K3_BOX_BOTTOM_PAD_MM = 1.8
K3_CTX_ENABLED = True
K3_CTX_HEIGHT_RATIO = 0.25
K3_CTX_X_OFFSET_MM = 2.0
K3_CTX_Y_OFFSET_MM = 2.0
K3_CTX_BORDER_MM = 0.4

# ==============================================================================================
# A4 Landscape page geometry
# ==============================================================================================
PAGE_W = 297.0
PAGE_H = 210.0
MARGIN_L = 12.0
MARGIN_R = 12.0
MARGIN_T = 12.0
MARGIN_B = 12.0

# Colors & style
GRAY_BG = (240, 240, 240)
BORDER = (180, 180, 180)
PDF_IMG_DPI: int = 150
PDF_IMG_JPEG_QUALITY: int = 85
PDF_HIRES_MODE: bool = False

@lru_cache(maxsize=256)
def _load_image_bytes_cached(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None

# ==============================================================================================
# Helpers: unit conversion, boxes, text, images
# ==============================================================================================

PT_TO_MM = 0.352778
def pt_to_mm(pt: float) -> float:
    return pt * PT_TO_MM

def _set_gray_bg(pdf: PDFU, x: float, y: float, w: float, h: float) -> None:
    pdf.set_fill_color(*GRAY_BG)
    pdf.rect(x, y, w, h, style="F")
    pdf.set_fill_color(255, 255, 255)

def _fit_font_size_single_line(pdf: PDFU, text: str, max_width: float,
                            base_size: int = 9, min_size: int = 6) -> int:
    s = pdf.safe(text or "")
    size = base_size
    while size >= min_size:
        pdf.set_u("", size)
        if pdf.get_string_width(s) <= max_width:
            return size
        size -= 1
    return min_size

def _ellipsis_fit(pdf: PDFU, text: str, max_width: float, font_size: int) -> str:
    s = pdf.safe(text or "")
    ellipsis = "..."
    pdf.set_u("", font_size)
    if pdf.get_string_width(s) <= max_width:
        return s
    while len(s) > 1 and pdf.get_string_width(s + ellipsis) > max_width:
        s = s[:-1]
    return s + ellipsis if len(s) > 0 else ""

def _draw_text_field(pdf: PDFU, x: float, y: float, w: float, h: float,
                    label: str, value: str, *, single_line_value: bool = False,
                    base_size: int = int(K3_LABEL_PT), min_size: int = 6, ellipsis: bool = False) -> None:
    """Draw a grey box with bold header and value."""
    _set_gray_bg(pdf, x, y, w, h)

    label_row_mm = pt_to_mm(K3_LABEL_PT) + 0.6
    pdf.set_xy(x + 1.0, y + K3_BOX_TOP_PAD_MM)
    pdf.set_u("B", int(K3_LABEL_PT))
    pdf.cell(w - 2.0, label_row_mm, pdf.safe(label), ln=2)

    if single_line_value:
        usable_w = w - 2.0
        s = pdf.safe(value or "")
        fitted = _fit_font_size_single_line(
            pdf, s, usable_w, base_size=int(K3_VALUE_MAX_PT), min_size=min_size
            )
        size_pt = min(fitted, int(K3_VALUE_MAX_PT))
        pdf.set_u("", size_pt)

        if pdf.get_string_width(s) > usable_w and ellipsis:
            s = _ellipsis_fit(pdf, s, usable_w, size_pt)

        gap_mm = pt_to_mm(K3_VALUE_GAP_PT)
        val_line_h_mm = max(pt_to_mm(size_pt) * 1.10, 3.6)
        y_start = y + K3_BOX_TOP_PAD_MM + label_row_mm + gap_mm
        y_max   = y + h - K3_BOX_BOTTOM_PAD_MM - val_line_h_mm
        y_val   = min(y_start, y_max)
        pdf.set_xy(x + 1.0, y_val)
        pdf.cell(usable_w, val_line_h_mm, s, ln=0)

    else:
        flow_gap_mm = pt_to_mm(K3_FLOW_GAP_PT)
        text_y = y + K3_BOX_TOP_PAD_MM + label_row_mm + flow_gap_mm
        pdf.set_xy(x + 1.0, text_y)
        pdf.set_u("", int(K3_LABEL_PT))
        pdf.multi_cell(w - 2.0, K3_FLOW_LINE_H_MM, pdf.safe(value or ""))

def _draw_text_field_autoheight(pdf: PDFU, x: float, y: float, w: float,
                                label: str, value: str,
                                base_size: int = int(K3_LABEL_PT), min_size: int = int(K3_LABEL_PT),
                                min_h: float = K3_FLOW_MIN_H_MM, max_h: float = K3_FLOW_MAX_H_MM) -> float:
    """Dynamic-height flow textbox."""
    label_row_mm = pt_to_mm(K3_LABEL_PT) + 0.6
    flow_gap_mm  = pt_to_mm(K3_FLOW_GAP_PT)
    pdf.set_u("", base_size)
    lines = pdf.multi_cell(w - 2.0, K3_FLOW_LINE_H_MM, pdf.safe(value or ""), split_only=True)
    needed = K3_BOX_TOP_PAD_MM + label_row_mm + flow_gap_mm \
             + K3_FLOW_LINE_H_MM * len(lines) + K3_BOX_BOTTOM_PAD_MM
    needed_h = max(min_h, min(max_h, needed))
    _draw_text_field(pdf, x, y, w, needed_h, label, value,
                    single_line_value=False, base_size=base_size, min_size=min_size)
    return needed_h + 1.0

# --- Image helpers ----------------------------------------------------------------------------
def _image_fit_to_box(pdf: PDFU, x: float, y: float,
                    box_w: float, box_h: float, img_path: Optional[str]) -> None:
    """Fit image into box with caching."""
    if not img_path or not os.path.exists(img_path):
        return
    try:
        data = _load_image_bytes_cached(os.path.abspath(img_path))
        if not data:
            return

        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            iw, ih = im.size
            if iw <= 0 or ih <= 0:
                return

            img_ratio = iw / ih
            box_ratio = box_w / box_h
            if img_ratio > box_ratio:
                draw_w = box_w
                draw_h = draw_w / img_ratio
            else:
                draw_h = box_h
                draw_w = draw_h * img_ratio

            if (not PDF_HIRES_MODE) and PDF_IMG_DPI and draw_w > 0 and draw_h > 0:
                target_w_px = int(round(draw_w / 25.4 * PDF_IMG_DPI))
                target_h_px = int(round(draw_h / 25.4 * PDF_IMG_DPI))

                scale = min(
                    1.0,
                    target_w_px / float(iw) if target_w_px > 0 else 1.0,
                    target_h_px / float(ih) if target_h_px > 0 else 1.0,
                )
                if scale < 1.0:
                    new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
                    im = im.resize(new_size, Image.LANCZOS)

            ensure_dir = os.path.join(PDF_CACHE, "_cache")
            os.makedirs(ensure_dir, exist_ok=True)
            cache_path = os.path.join(ensure_dir, f"_img_{abs(hash((img_path, int(draw_w), int(draw_h)))) % (10**9)}.jpg")
            pil_to_jpg(im.copy(), cache_path, PDF_IMG_JPEG_QUALITY)
            x_img = x + (box_w - draw_w) / 2.0
            y_img = y + (box_h - draw_h) / 2.0
            pdf.image(abs_fwd(cache_path), x=x_img, y=y_img, w=draw_w, h=draw_h)
    except Exception:
        pass

def _draw_image_box(pdf: PDFU, x: float, y: float, w: float, h: float,
                    img_path: Optional[str], label: Optional[str] = None) -> None:
    pdf.set_draw_color(*BORDER)
    pdf.rect(x, y, w, h)
    if label:
        pdf.set_u("B", 9)
        pdf.set_text_color(*EDITOR_BLUE_RGB)
        pdf.set_xy(x + 2, y + 2)
        pdf.cell(w - 4, 5, pdf.safe(label))
        pdf.set_text_color(0, 0, 0)
        _image_fit_to_box(pdf, x + 1, y + 8, w - 2, h - 9, img_path)
    else:
        _image_fit_to_box(pdf, x + 1, y + 1, w - 2, h - 2, img_path)

# --- Kontext overlay --------------------------------------------------------------------------
def _resolve_context_path(rec: dict, paths: dict) -> Optional[str]:
    """Resolve the 'Kontext' picture path."""
    ctx_list = rec.get("ctx_list") or []
    if isinstance(ctx_list, list) and ctx_list:
        entry = ctx_list[0] or {}
        ctx_path = _get_composite_path_for_record(entry, paths, "ctx")
        if ctx_path and os.path.exists(ctx_path):
            return ctx_path

    candidates = [
        rec.get("kontext"), rec.get("context"), rec.get("ctx"),
        rec.get("context_edited"), rec.get("context_raw"),
        rec.get("kontext_edited"), rec.get("kontext_raw"),
        rec.get("ctx_edited"), rec.get("ctx_raw"),
    ]
    for src in candidates:
        if not src:
            continue
        ap = resolve_media_path(src, paths) or to_abs_path(src, {"root": paths["root"]})
        if ap and os.path.exists(ap):
            return ap
        
    f = rec.get("fehler", {}) or {}
    for key in ("Kontext", "kontext", "context"):
        src = f.get(key)
        if not src:
            continue
        ap = resolve_media_path(src, paths) or to_abs_path(src, {"root": paths["root"]})
        if ap and os.path.exists(ap):
            return ap

    return None

def _draw_ctx_overlay_top_right(pdf: PDFU,
                                area_x: float, area_y: float,
                                area_w: float, area_h: float,
                                ctx_path: Optional[str]) -> None:
    """Draw a small 'Kontext' image overlay."""
    if not K3_CTX_ENABLED or not ctx_path or not os.path.exists(ctx_path):
        return
    try:
        with Image.open(ctx_path) as im:
            iw, ih = im.size
            if iw <= 0 or ih <= 0:
                return
            ctx_ratio = iw / ih
            overlay_h = max(1.0, area_h * float(K3_CTX_HEIGHT_RATIO))
            overlay_w = max(1.0, overlay_h * ctx_ratio)
            target_x = area_x + area_w - overlay_w - float(K3_CTX_X_OFFSET_MM)
            target_y = area_y + float(K3_CTX_Y_OFFSET_MM)
            target_x = max(area_x, min(area_x + area_w - overlay_w, target_x))
            target_y = max(area_y, min(area_y + area_h - overlay_h, target_y))

            if K3_CTX_BORDER_MM and K3_CTX_BORDER_MM > 0.0:
                pdf.set_draw_color(*BORDER)
                pdf.rect(target_x, target_y, overlay_w, overlay_h)

            _image_fit_to_box(pdf, target_x, target_y, overlay_w, overlay_h, ctx_path)
    except Exception:
        pass

def _draw_title_page(pdf: PDFU, project_id: str, bezeichnung: str, logo_path: str):
    pdf.add_page(orientation="L")
    pdf.set_fill_color(0, 0, 0)
    pdf.rect(0, 0, PAGE_W, PAGE_H, style="F")
    logo_w = 120
    logo_h = 60
    logo_x = (PAGE_W - logo_w) / 2
    logo_y = (PAGE_H - logo_h) / 2 - 20

    if os.path.exists(logo_path):
        pdf.image(logo_path, x=logo_x, y=logo_y, w=logo_w, h=logo_h)

    pdf.set_text_color(255, 255, 255)
    title = bezeichnung or project_id or ""
    subtitle = project_id or ""
    pdf.set_u("B", 22)
    pdf.set_xy(0, logo_y + logo_h + 10)
    pdf.cell(PAGE_W, 14, pdf.safe(title), align="C", ln=2)

    if subtitle:
        pdf.set_u("", 14)
        pdf.set_xy(0, logo_y + logo_h + 10 + 16)
        pdf.cell(PAGE_W, 10, pdf.safe(f"Projekt-ID: {subtitle}"), align="C", ln=2)

    pdf.set_text_color(0, 0, 0) 

# ==============================================================================================
# Helper functions for new fields
# ==============================================================================================

def _get_area_display(f: dict) -> str:
    """Get display string for vehicle area(s) — show ALL multiselections (no (+x))."""
    multi = f.get("vehicle_area_multi")
    if multi and isinstance(multi, list) and len(multi) > 0:
        # Keep order, remove duplicates, map to full labels
        seen = set()
        labels = []
        for a in multi:
            if not a or a in seen:
                continue
            seen.add(a)
            labels.append(VEHICLE_AREA_LABELS.get(a, a))
        return ", ".join(labels) if labels else "—"

    single = f.get("vehicle_area", "")
    return VEHICLE_AREA_LABELS.get(single, single) if single else "—"


def _get_system_display(f: dict) -> str:
    """Get display string for system/domain(s) — show ALL multiselections (no (+x))."""
    multi = f.get("system_domain_multi")
    if multi and isinstance(multi, list) and len(multi) > 0:
        # Keep order, remove duplicates, map to full labels
        seen = set()
        labels = []
        for s in multi:
            if not s or s in seen:
                continue
            seen.add(s)
            labels.append(SYSTEM_DOMAIN_LABELS.get(s, s))
        return ", ".join(labels) if labels else "—"

    single = f.get("system_domain", "")
    return SYSTEM_DOMAIN_LABELS.get(single, single) if single else "—"


# ==============================================================================================
# Kapitel 2 — Fehlerliste (ENHANCED with Bereich/System)
# ==============================================================================================

def _measure_info_col(pdf: PDFU, w: float, body_fs: float,
                    desc: str, audit_comment: str,
                    rework_suggestion: str, rework_comment: str) -> int:
    """Measure the Information column."""
    LINE_H = 4.0
    inner_w = w - 2.0
    pdf.set_u("", int(body_fs))
    heading_lines = 4

    try:
        gap_units = K2_INFO_HEADER_GAP_MM / LINE_H
    except NameError:
        gap_units = 0.5 

    lines_desc   = pdf.multi_cell(inner_w, LINE_H, pdf.safe(desc or ""),             split_only=True)
    lines_audit  = pdf.multi_cell(inner_w, LINE_H, pdf.safe(audit_comment or ""),    split_only=True)
    lines_rework = pdf.multi_cell(inner_w, LINE_H, pdf.safe(rework_suggestion or ""),split_only=True)
    lines_rwc    = pdf.multi_cell(inner_w, LINE_H, pdf.safe(rework_comment or ""),   split_only=True)

    total = (
        heading_lines
        + 4 * gap_units
        + len(lines_desc)
        + len(lines_audit)
        + len(lines_rework)
        + len(lines_rwc)
    )
    return int(math.ceil(total + 1))

def _draw_kap2_table(
    pdf: PDFU,
    images: List[dict],
    page_w: float,
    header_bold: bool = True,
    body_bold: bool = False,
    header_font_size: float = 10.0,
    body_font_size: float = 6.0
) -> None:
    """Enhanced Kapitel 2 table with Bereich and System columns."""
    HEADER_BG = RODING_GREEN_RGB
    HEADER_FG = (0, 0, 0)
    ROW_BG1   = (255, 255, 255)
    ROW_BG2   = (240, 240, 240)
    BORDER_RGB = BORDER

    # ENHANCED: Added Bereich and System columns
    headers = ["NR", "Case", "Bereich", "System", "Fehlerort", "Fehlerart", "Status", "Information"]
    col_rel = [0.05, 0.05, 0.10, 0.10, 0.10, 0.10, 0.09, 0.41]
    col_w   = [r * page_w for r in col_rel]
    h_hdr   = 7.0
    LINE_H  = 4.0

    # --- Draw header ---
    y0 = pdf.get_y()
    x  = MARGIN_L
    pdf.set_u("B" if header_bold else "", header_font_size)
    for hdr, w in zip(headers, col_w):
        pdf.set_fill_color(*HEADER_BG)
        pdf.set_text_color(*HEADER_FG)
        pdf.rect(x, y0, w, h_hdr, style="F")
        pdf.set_xy(x + 1.0, y0 + 1.0)
        pdf.multi_cell(w - 2.0, h_hdr - 2.0, pdf.safe(hdr), align="C")
        x += w
    pdf.set_text_color(0, 0, 0)
    pdf.set_u("", body_font_size)
    pdf.set_y(y0 + h_hdr)

    # --- Data rows ---
    pdf.set_u("B" if body_bold else "", body_font_size)

    for idx, rec in enumerate(images):
        y_row_top = pdf.get_y()
        x = MARGIN_L
        row_bg = ROW_BG1 if idx % 2 == 0 else ROW_BG2
        f = rec.get("fehler", {}) or {}
        
        # ENHANCED: Build status cell with new fields
        status_cell = (
            f"Prio: {f.get('Prioritaet', '')}\n"
            f"BI(A): {f.get('BI_alt', '')}\n"
            f"BI(N): {f.get('BI_neu', f.get('BI_alt', ''))}\n"
            f"QZ: {f.get('QZStatus', '')}\n"
            f"RQM: {'Ja' if f.get('RQMRelevant') else 'Nein'}\n"
            f"NA: {'Ja' if f.get('Nacharbeit_done') else 'Nein'}"
        )

        desc              = f.get("Fehlerbeschreibung", "") or ""
        audit_comment     = f.get("Kommentar", "") or ""
        rework_suggestion = f.get("Nacharbeitsvorschlag", "") or ""
        rework_comment    = (f.get("Kommentar_Nacharbeit", "") or f.get("Kommentar\\_Nacharbeit", "")) or ""
        
        # ENHANCED: Get Bereich and System display values
        bereich_display = _get_area_display(f)
        system_display = _get_system_display(f)
        
        row_vals_simple = [
            rec.get("nr", "") or "",
            f.get("CaseStatus", "") or "",
            bereich_display,  # NEW
            system_display,   # NEW
            f.get("Fehlerort", "") or "",
            ", ".join(f.get("Fehlerart", []) or []),
            status_cell,
        ]

        # Count wrapped lines per cell
        cell_lines_counts: List[int] = []

        for val, w in zip(row_vals_simple, col_w[:-1]):
            lines = pdf.multi_cell(w - 2.0, LINE_H, pdf.safe(str(val)), split_only=True)
            cell_lines_counts.append(len(lines))

        info_lines = _measure_info_col(pdf, col_w[-1], body_font_size, desc, audit_comment, rework_suggestion, rework_comment)
        cell_lines_counts.append(info_lines)

        max_lines = max(cell_lines_counts) if cell_lines_counts else 1
        row_h = max(h_hdr, LINE_H * max_lines + 2.0)

        # Page-break handling
        if y_row_top + row_h > PAGE_H - MARGIN_B:
            pdf.add_page(orientation="L")
            pdf.set_u("B" if header_bold else "", header_font_size)
            pdf.cell(0, 10, pdf.safe("Kapitel 2 - Fehlerliste (Fortsetzung)"), ln=True)
            y0 = pdf.get_y()
            x = MARGIN_L
            for hdr, w in zip(headers, col_w):
                pdf.set_fill_color(*HEADER_BG)
                pdf.set_text_color(*HEADER_FG)
                pdf.rect(x, y0, w, h_hdr, style="F")
                pdf.set_xy(x + 1.0, y0 + 1.0)
                pdf.multi_cell(w - 2.0, h_hdr - 2.0, pdf.safe(hdr), align="C")
                x += w
            pdf.set_text_color(0, 0, 0)
            pdf.set_u("", body_font_size)
            pdf.set_y(y0 + h_hdr)
            y_row_top = pdf.get_y()

        # Row background
        pdf.set_fill_color(*row_bg)
        pdf.rect(MARGIN_L, y_row_top, sum(col_w), row_h, style="F")

        # Draw cell borders + content
        pdf.set_draw_color(*BORDER_RGB)

        def _draw_wrapped_cell_text(cell_x: float, cell_y: float, w_inner: float, text: str) -> None:
            lines = pdf.multi_cell(w_inner, LINE_H, pdf.safe(text or ""), split_only=True)
            y_cursor = cell_y
            for s in lines:
                pdf.set_xy(cell_x, y_cursor)
                pdf.multi_cell(w_inner, LINE_H, s)
                y_cursor += LINE_H

        x = MARGIN_L
        for col_i, (val, w) in enumerate(zip(row_vals_simple, col_w[:-1])):
            pdf.rect(x, y_row_top, w, row_h)
            cell_x = x + 1.0
            cell_y = y_row_top + 1.0
            _draw_wrapped_cell_text(cell_x, cell_y, w - 2.0, str(val))
            x += w
            pdf.set_xy(x, y_row_top + 1.0)

        w_info = col_w[-1]
        pdf.rect(x, y_row_top, w_info, row_h)
        inner_x = x + 1.0
        inner_y = y_row_top + 1.0
        inner_w = w_info - 2.0
        sections = [
            ("Fehlerbeschreibung:", desc),
            ("Kommentar (Audit):", audit_comment),
            ("Nacharbeitsvorschlag:", rework_suggestion),
            ("Kommentar Nacharbeit:", rework_comment),
        ]
        y_cursor = inner_y

        for label, body in sections:
            y_cursor += K2_INFO_HEADER_GAP_MM
            pdf.set_u("B", int(body_font_size))
            pdf.set_xy(inner_x, y_cursor)
            pdf.cell(inner_w, LINE_H, pdf.safe(label), ln=2)
            y_cursor += LINE_H
            pdf.set_u("", int(body_font_size))
            body_lines = pdf.multi_cell(inner_w, LINE_H, pdf.safe(body or ""), split_only=True)

            for s in body_lines:
                pdf.set_xy(inner_x, y_cursor)
                pdf.multi_cell(inner_w, LINE_H, s)
                y_cursor += LINE_H

        pdf.set_y(y_row_top + row_h)

def _draw_kap2(pdf: PDFU, images: List[dict]) -> None:
    pdf.add_page(orientation="L")
    pdf.set_u("B", 12)
    pdf.cell(0, 10, pdf.safe("Kapitel 2 - Fehlerliste"), ln=True)
    content_w = PAGE_W - MARGIN_L - MARGIN_R
    _draw_kap2_table(pdf, images, content_w)

# ==============================================================================================
#  Kapitel 3: two large images + metadata & flowing text (ENHANCED)
# ==============================================================================================

def _draw_kap3_page(pdf: PDFU, rec: dict, paths: dict, include_after: bool) -> None:
    pdf.add_page(orientation="L")
    nr = rec.get("nr", "")
    pdf.set_u("B", 13)
    pdf.cell(0, 10, pdf.safe(f"Kapitel 3 - Fehlerbilder (Audit / Nacharbeit) - Fehler {nr}"), ln=True)
    pdf.set_u("", 9)
    y = pdf.get_y() + 2.0
    f = rec.get("fehler", {}) or {}
    
    # ENHANCED: Get Bereich and System display strings
    bereich_display = _get_area_display(f)
    system_display = _get_system_display(f)
    
    # ENHANCED: Extended metadata with new fields (2 rows)
    meta_row1: List[Tuple[str, str]] = [
        ("Case", f.get("CaseStatus", "")),
        ("Priorität", f.get("Prioritaet", "")),
        ("Fehlerort", f.get("Fehlerort", "")),
        ("Fehlerart", ", ".join(f.get("Fehlerart", []))),
    ]
    
    meta_row2: List[Tuple[str, str]] = [
        ("Fahrzeugbereich", bereich_display),  
        ("System/Domäne", system_display),      
        ("BI (Audit)", f.get("BI_alt", "") or f.get("BI\\_alt", "")),
        ("BI (Nacharbeit)", f.get("BI_neu", "") or f.get("BI\\_neu", "")),
        ("QZ", f.get("QZStatus", "")),
        ("RQM", "Ja" if f.get("RQMRelevant") else "Nein"),
        ("Nacharbeit", "Ja" if f.get("Nacharbeit_done") else "Nein"),
    ]
    
    total_w = PAGE_W - MARGIN_L - MARGIN_R
    gap = 2.0
    
    # Draw first row of metadata
    field_w_row1 = (total_w - (len(meta_row1) - 1) * gap) / len(meta_row1)
    field_h = K3_METADATA_BOX_H_MM
    x = MARGIN_L

    for label, value in meta_row1:
        _draw_text_field(pdf, x, y, field_w_row1, field_h, label, value,
                        single_line_value=True, base_size=int(K3_LABEL_PT), min_size=6, ellipsis=True)
        x += field_w_row1 + gap

    y += field_h + 2.0
    
    # Draw second row of metadata (NEW)
    field_w_row2 = (total_w - (len(meta_row2) - 1) * gap) / len(meta_row2)
    x = MARGIN_L

    for label, value in meta_row2:
        _draw_text_field(pdf, x, y, field_w_row2, field_h, label, value,
                        single_line_value=True, base_size=int(K3_LABEL_PT), min_size=6, ellipsis=True)
        x += field_w_row2 + gap

    y += field_h + 2.0
    
    # Text fields
    y += _draw_text_field_autoheight(pdf, MARGIN_L, y, total_w, "Fehlerbeschreibung",
                                    f.get("Fehlerbeschreibung", ""))
    y += _draw_text_field_autoheight(pdf, MARGIN_L, y, total_w, "Nacharbeitsvorschlag",
                                    f.get("Nacharbeitsvorschlag", ""))
    y += _draw_text_field_autoheight(pdf, MARGIN_L, y, total_w, "Kommentar",
                                    f.get("Kommentar", ""))
    y += _draw_text_field_autoheight(pdf, MARGIN_L, y, total_w, "Kommentar Nacharbeit",
                                    f.get("Kommentar_Nacharbeit", "") or f.get("Kommentar\\_Nacharbeit", ""))
    
    # Images
    box_y = y
    col_gap = 8.0
    box_w = (PAGE_W - MARGIN_L - MARGIN_R - col_gap) / 2.0
    box_h = PAGE_H - box_y - MARGIN_B
    main_abs = _get_composite_path_for_record(rec, paths, "main")
    ctx_abs  = _resolve_context_path(rec, paths)
    _draw_image_box(pdf, MARGIN_L, box_y, box_w, box_h, main_abs, "Fehlerbild Audit")
    audit_area_x = MARGIN_L + 1.0
    audit_area_y = box_y + 8.0
    audit_area_w = box_w - 2.0
    audit_area_h = box_h - 9.0
    _draw_ctx_overlay_top_right(pdf, audit_area_x, audit_area_y, audit_area_w, audit_area_h, ctx_abs)
    after_abs = _get_composite_path_for_record(rec, paths, "after") if include_after else None
    _draw_image_box(pdf, MARGIN_L + box_w + col_gap, box_y, box_w, box_h,
                    after_abs, "Fehlerbild Nacharbeit")

# ==============================================================================================
#  Fixed gallery (3x2 tiles per column) for additional images
# ==============================================================================================

TILE_ROWS = 3
TILE_COLS = 2
MAX_PER_COL = TILE_ROWS * TILE_COLS
X_GAP = 2.0
Y_GAP = 2.0
BORDER_MM = 0.4
FIT_MODE = "contain" 

def _image_into_tile(pdf: PDFU, x: float, y: float, tile_w: float, tile_h: float,
                    img_path: Optional[str], fit: str = FIT_MODE) -> None:
    if BORDER_MM and BORDER_MM > 0.0:
        pdf.set_draw_color(*BORDER)
        pdf.rect(x, y, tile_w, tile_h)

    if not img_path or not os.path.exists(img_path):
        return
    try:
        with Image.open(img_path) as im:
            iw, ih = im.size
            if iw <= 0 or ih <= 0:
                return
            tile_ratio = tile_w / tile_h
            img_ratio = iw / ih
            if fit == "cover":
                if img_ratio > tile_ratio:
                    new_h = ih
                    new_w = int(round(tile_ratio * ih))
                    x0 = (iw - new_w) // 2
                    y0 = 0
                else:
                    new_w = iw
                    new_h = int(round(iw / tile_ratio))
                    x0 = 0
                    y0 = (ih - new_h) // 2
                im_out = im.crop((x0, y0, x0 + new_w, y0 + new_h))
            else:
                im_out = im 

            iw2, ih2 = im_out.size
            img_ratio2 = iw2 / ih2
            if img_ratio2 > tile_ratio:
                draw_w = tile_w
                draw_h = draw_w / img_ratio2
            else:
                draw_h = tile_h
                draw_w = draw_h * img_ratio2
            x_img = x + (tile_w - draw_w) / 2.0
            y_img = y + (tile_h - draw_h) / 2.0

            cache_dir = os.path.join(PDF_CACHE, "_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, f"_tile_{abs(hash(img_path)) % (10**9)}.jpg")
            pil_to_jpg(im_out.copy(), cache_path, 90)
            pdf.image(abs_fwd(cache_path), x=x_img, y=y_img, w=draw_w, h=draw_h)
    except Exception:
        pass

def _draw_gallery_fixed(pdf: PDFU,
                        left_imgs: List[str], right_imgs: List[str],
                        left_label: str, right_label: str) -> None:
    title_h = 10.0

    def _draw_headers():
        pdf.set_u("B", 13)
        pdf.cell(0, title_h, pdf.safe("Kapitel 3 - Zusatzbilder Galerie"), ln=True)
        nonlocal y_top, col_w
        y_top = pdf.get_y() + 2.0
        col_gap = 8.0
        col_w = (PAGE_W - MARGIN_L - MARGIN_R - col_gap) / 2.0

        def _draw_col_header(x: float, title: str) -> None:
            pdf.set_fill_color(*RODING_GREEN_RGB)
            pdf.rect(x, y_top, col_w, 10.0, style="F")
            pdf.set_xy(x + 2.0, y_top + 2.0)
            pdf.set_text_color(255, 255, 255)
            pdf.set_u("B", 11)
            pdf.cell(col_w - 4.0, 6.0, pdf.safe(title))
            pdf.set_text_color(0, 0, 0)

        _draw_col_header(MARGIN_L, left_label)
        _draw_col_header(MARGIN_L + col_w + col_gap, right_label)

    pdf.add_page(orientation="L")
    y_top, col_w = 0.0, 0.0
    _draw_headers()

    y_images_top = y_top + 12.0
    col_h = PAGE_H - y_images_top - MARGIN_B
    tile_w = (col_w - (TILE_COLS + 1) * X_GAP) / TILE_COLS
    tile_h = (col_h - (TILE_ROWS + 1) * Y_GAP) / TILE_ROWS
    n_pages = max(
        (len(left_imgs) + MAX_PER_COL - 1) // MAX_PER_COL,
        (len(right_imgs) + MAX_PER_COL - 1) // MAX_PER_COL,
        1,
    )

    def _draw_column(x0: float, imgs: List[str]) -> None:
        for r in range(TILE_ROWS):
            for c in range(TILE_COLS):
                x = x0 + X_GAP + c * (tile_w + X_GAP)
                y = y_images_top + Y_GAP + r * (tile_h + Y_GAP)
                idx = r * TILE_COLS + c
                img = imgs[idx] if idx < len(imgs) else None
                _image_into_tile(pdf, x, y, tile_w, tile_h, img, fit=FIT_MODE)

    for page in range(n_pages):
        if page > 0:
            pdf.add_page(orientation="L")
            _draw_headers()
        left_page_imgs = left_imgs[page * MAX_PER_COL: (page + 1) * MAX_PER_COL]
        right_page_imgs = right_imgs[page * MAX_PER_COL: (page + 1) * MAX_PER_COL]
        _draw_column(MARGIN_L, left_page_imgs)
        _draw_column(MARGIN_L + col_w + 8.0, right_page_imgs)

# ==============================================================================================
#  Selection & BI counts
# ==============================================================================================

def select_images(
    idx: dict,
    mode: str,
    scope_filter: List[str],
    audit_id: Optional[str],
    audit_ids: Optional[List[str]] = None,
) -> List[dict]:
    """Select all relevant Fehlerbilder for PDF export."""
    imgs = idx.get("images", []) or []
    audits_map = {a["audit_id"]: a for a in idx.get("audits", [])}

    if scope_filter:
        imgs = [
            r for r in imgs
            if audits_map.get(r.get("audit_id"), {}).get("scope") in scope_filter
        ]

    if audit_ids:
        allowed = set(audit_ids)
        imgs = [r for r in imgs if r.get("audit_id") in allowed]

    elif mode in ("Audit-Report", "Audit-Report-mit-Nacharbeit"):
        imgs = [r for r in imgs if r.get("audit_id") == audit_id] if audit_id else []

    return imgs

def bi_counts_of(imgs: List[dict]):
    pre, post = {}, {}
    for rec in imgs:
        f = rec.get("fehler", {}) or {}
        bi_pre_k = f.get("BI_alt", "") or ""

        if not bi_pre_k or bi_pre_k.strip() == "":
            bi_pre_k = "BI0-tbd."
        pre[bi_pre_k] = pre.get(bi_pre_k, 0) + 1
        bi_post_k = (f.get("BI_neu") if f.get("Nacharbeit_done") else f.get("BI_alt")) or ""

        if not bi_post_k or bi_post_k.strip() == "":
            bi_post_k = "BI0-tbd."
        post[bi_post_k] = post.get(bi_post_k, 0) + 1

    return pre, post

# ==============================================================================================
#  Kapitel 1 helpers 
# ==============================================================================================
def _draw_prop_bar(pdf: PDFU, y: float, counts: Dict[str, int], labels, title: str) -> float:
    content_w = PAGE_W - MARGIN_L - MARGIN_R
    total = max(1, sum(counts.values()))
    bar_h = 6.0
    title_h = 4.0

    pdf.set_xy(MARGIN_L, y)
    pdf.set_u("B", 9)
    pdf.cell(content_w, title_h, pdf.safe(title), ln=True, align="C")

    y_bar = y + title_h + 1.0
    pdf.rect(MARGIN_L, y_bar, content_w, bar_h)

    x_cursor = MARGIN_L
    pdf.set_u("", 9)
    for key, color in labels:
        seg_w = content_w * (counts.get(key, 0) / total)
        r, g, b = color
        pdf.set_fill_color(r, g, b)
        pdf.rect(x_cursor, y_bar, max(0.0, seg_w), bar_h, style="F")
        if seg_w >= 18.0:
            pdf.set_text_color(255, 255, 255)
            pdf.set_xy(x_cursor, y_bar)
            pdf.cell(seg_w, bar_h, pdf.safe(f"{key.upper()} {counts.get(key, 0)}"), align="C")
            pdf.set_text_color(0, 0, 0)
        x_cursor += seg_w
    return y_bar + bar_h

def render_bi_overview(
    pdf: PDFU,
    counts_audit: Dict[str, int],
    counts_nacharbeit: Dict[str, int],
) -> None:
    """Kapitel 1 – Übersicht: Verteilung nach BI (Audit) + (Nacharbeit)"""
    pdf.add_page()
    pdf.set_u("B", 14)
    pdf.cell(0, 8, pdf.safe("Kapitel 1 – Übersicht"), ln=1)
    pdf.ln(2)
    pdf.set_u("", 11)
    pdf.cell(0, 6, pdf.safe("Verteilung der Befunde nach BI-Kategorien"), ln=1)
    pdf.ln(4)
    x = 10.0
    y_top = pdf.get_y()
    w = pdf.w - 2 * x 

    used_h1 = draw_bi_table_absolute(
        pdf=pdf,
        title="Verteilung nach BI (Audit)",
        counts=counts_audit,
        x=x,
        y=y_top,
        w=w,
        line_h=5.0,
        header_h=5.0,
        title_h=5.5,
        pad=1.0,
    )

    y_second = y_top + used_h1 + 4.0 

    used_h2 = draw_bi_table_absolute(
        pdf=pdf,
        title="Verteilung nach BI (Nacharbeit)",
        counts=counts_nacharbeit,
        x=x,
        y=y_second,
        w=w,
        line_h=5.0,
        header_h=5.0,
        title_h=5.5,
        pad=1.0,
    )

    pdf.set_xy(x, y_second + used_h2 + 4.0)

# ==============================================================================================
#  Main: PDF export
# ==============================================================================================

def build_pdf_with_modes(
    idx: dict,
    paths: dict,
    mode: str,
    scope_filter: List[str],
    audit_id: Optional[str],
    include_after: bool,
    include_additional: bool,
    hires: bool = False,
    chapters: Optional[List[int]] = None,
    selected_image_keys: Optional[List[str]] = None,
    selected_audit_ids: Optional[List[str]] = None,
    sorting_mode: str = None,
) -> bytes:
    if os.path.exists(PDF_CACHE):
        try:
            import shutil
            shutil.rmtree(PDF_CACHE, ignore_errors=True)
        except Exception:
            pass
    os.makedirs(PDF_CACHE, exist_ok=True)
    
    global PDF_HIRES_MODE, PDF_IMG_JPEG_QUALITY
    PDF_HIRES_MODE = bool(hires)
    PDF_IMG_JPEG_QUALITY = 95 if hires else 85

    audits = idx.get("audits", []) or []
    images = select_images(idx, mode, scope_filter, audit_id, selected_audit_ids)

    # Optional: nur ausgewählte Fehlerbilder exportieren
    if selected_image_keys:
        key_set = set(selected_image_keys)

        def _img_key(rec: dict) -> str:
            return f"{rec.get('audit_id', '')}__{rec.get('nr', '')}"

        images = [r for r in images if _img_key(r) in key_set]

    for r in images:
        ensure_new_fields(r)
    
    if chapters is None:
        chapters_set = {1, 2, 3}
    else:
        chapters_set = {int(c) for c in chapters if int(c) in (1, 2, 3)}
        if not chapters_set:
            chapters_set = {1, 2, 3}

    pdf = PDFU()
    
    # --- Title page ---
    logo_path = os.path.join("assets", "WiiGoRLogo.png")
    project = idx.get("project", {}) or {}

    project_id = project.get("project_id", "")
    bezeichnung = project.get("vehicle") or project.get("bezeichnung", "")

    _draw_title_page(pdf, project_id, bezeichnung, logo_path)

    # ---- Kapitel 1 --------------------------------------------------------------------------
    if 1 in chapters_set:
        pdf.add_page(orientation="L")
        pdf.set_u("B", 14)
        pdf.cell(0, 10, pdf.safe("Kapitel 1 - Gesamtübersicht"), ln=True, align="C")

        pdf.set_u("", 11)
        info = f"WiiGoR · Projekt: {project_id} · Fahrzeug: {bezeichnung} · Modus: {mode}"
        pdf.cell(0, 7, pdf.safe(info), ln=True)
        pdf.ln(3)

        pdf.set_u("B", 10)
        pdf.cell(0, 6, pdf.safe("Audits - Kurzüberblick"), ln=True)

        def _short_auditor_name(aud_str: str) -> str:
            if not aud_str:
                return ""
            main = aud_str.split("/")[0].split(",")[0].strip()
            parts = main.split()
            if len(parts) >= 2:
                return f"{parts[0]} {parts[1]}"
            return parts[0] if parts else ""

        pdf.set_u("", 9)
        rows = []

        for a in audits:
            if scope_filter and a.get("scope") not in scope_filter:
                continue
            a_imgs = [r for r in images if r.get("audit_id") == a["audit_id"]]
            open_n = sum(1 for r in a_imgs if (r.get("fehler", {}).get("CaseStatus", "Open") != "Closed"))
            closed_n = len(a_imgs) - open_n
            short_aud = _short_auditor_name(a.get("auditor", ""))

            rows.append([
                a.get("date", ""),
                a.get("type", ""),
                a.get("scope", ""),
                short_aud,
                str(open_n),
                str(closed_n),
                str(len(a_imgs)),
            ])

        col_w_total = PAGE_W - MARGIN_L - MARGIN_R
        widths = [0.15, 0.26, 0.17, 0.17, 0.10, 0.07, 0.08]
        widths = [w * col_w_total for w in widths]

        def _draw_simple_table(hdr, data, wlist):
            pdf.set_u("B", 9)
            y0 = pdf.get_y()
            h = 6.2
            x = MARGIN_L
            for t, w in zip(hdr, wlist):
                pdf.rect(x, y0, w, h)
                pdf.set_xy(x + 1, y0 + 1)
                pdf.cell(w - 2, h - 2, pdf.safe(t))
                x += w
            pdf.set_y(y0 + h)

            pdf.set_u("", 9)
            for row in data:
                if pdf.get_y() + h > PAGE_H - MARGIN_B:
                    pdf.add_page(orientation="L")
                    _draw_simple_table(hdr, [], wlist)
                x = MARGIN_L
                y = pdf.get_y()
                for val, w in zip(row, wlist):
                    pdf.rect(x, y, w, h)
                    pdf.set_xy(x + 1, y + 1)
                    pdf.cell(w - 2, h - 2, pdf.safe(str(val)))
                    x += w
                pdf.set_y(y + h)

        _draw_simple_table(
            ["Datum", "Typ", "Scope", "Auditor", "Open", "Closed", "Total"],
            rows,
            widths,
        )

        status_counts = {"Open": 0, "Closed": 0}
        rqm_counts = {"No": 0, "Yes": 0}
        qz_counts = {"QZS": 0, "QZF": 0}
        for rec in images:
            f = rec.get("fehler", {}) or {}
            status_counts["Closed" if f.get("CaseStatus", "Open") == "Closed" else "Open"] += 1
            rqm_counts["Yes" if f.get("RQMRelevant") else "No"] += 1
            qz = f.get("QZStatus", "QZS")
            qz_counts[qz] = qz_counts.get(qz, 0) + 1

        y = pdf.get_y() + 4.0
        y = _draw_prop_bar(pdf, y, status_counts,
                        labels=[("Closed", (46, 204, 113)), ("Open", (243, 156, 18))],
                        title="Case Status (nach Filter)")
        y = _draw_prop_bar(pdf, y + 3.0, rqm_counts,
                        labels=[("No", (39, 174, 96)), ("Yes", (192, 57, 43))],
                        title="RQM Relevant (Findings)") + 3.0
        y = _draw_prop_bar(pdf, y + 3.0, qz_counts,
                        labels=[("QZS", (52, 152, 219)), ("QZF", (155, 89, 182))],
                        title="QZ Status (Findings)") + 4.0

        # === BI-Charts und Verteilungstabellen ===
        pre, post = bi_counts_of(images)
        page_w = pdf.w
        gap = 10.0 
        content_w = page_w - MARGIN_L - MARGIN_R
        col_w = (content_w - gap) / 2.0
        col_eff = max(10.0, col_w - 1.0)
        x_left = MARGIN_L
        x_right = x_left + col_w + gap

        # Pie-Charts erstellen
        pie_left = os.path.join(PDF_CACHE, "bi_pie_pre_sq.png")
        pie_right = os.path.join(PDF_CACHE, "bi_pie_post_sq.png")
        save_pie_chart_square(pie_left, pre, "Fehler nach BI (Audit)")
        
        if not post or sum(post.values()) == 0:
            post = pre.copy()
        
        save_pie_chart_square(pie_right, post, "Fehler nach BI (Nacharbeit)")

        try:
            from PIL import Image
            with Image.open(abs_fwd(pie_left)) as im:
                iw, ih = im.size
                img_ratio = (iw / ih) if ih else 1.0
        except Exception:
            img_ratio = 1.0

        chart_w = min(col_eff, 90.0)
        chart_h = chart_w / img_ratio

        estimated_h1 = 6.0 + 5.5 + (len(pre) * 5.5)
        estimated_h2 = 6.0 + 5.5 + (len(post) * 5.5)
        max_estimated_h = max(estimated_h1, estimated_h2)
        total_needed = chart_h + 5.0 + max_estimated_h
        page_height = pdf.h
        remaining_space = page_height - y - MARGIN_B
        
        if remaining_space < total_needed:
            pdf.add_page(orientation="L")
            y = MARGIN_T

        pdf.image(
            abs_fwd(pie_left),
            x=x_left + (col_w - chart_w) / 2.0,
            y=y,
            w=chart_w,
        )
        pdf.image(
            abs_fwd(pie_right),
            x=x_right + (col_w - chart_w) / 2.0,
            y=y,
            w=chart_w,
        )

        pdf.rect(x_left, y, col_w, chart_h)
        pdf.rect(x_right, y, col_w, chart_h)
        y2 = y + chart_h + 5.0 
        h1 = draw_bi_table_absolute(
            pdf,
            "Verteilung nach BI (Audit)",
            pre,
            x_left,
            y2,
            col_w,
        )

        h2 = draw_bi_table_absolute(
            pdf,
            "Verteilung nach BI (Nacharbeit)",
            post,
            x_right,
            y2,
            col_w,
        )

    # ---- Kapitel 2 -------------------------------------------------------------
    # Apply BMW Fehlerbild sorting (Bereich -> System -> BI -> Status -> Nr)
    images_sorted = sort_fehlerbilder_with_mode(images, sorting_mode)

    if 2 in chapters_set:
        _draw_kap2(pdf, images_sorted)

    # ---- Kapitel 3 + optional gallery -------------------------------------------------------
    if 3 in chapters_set and images_sorted:
        for rec in images_sorted:
            _draw_kap3_page(pdf, rec, paths, include_after)
            if include_additional:
                add_list_left = rec.get("add_fehler_list", []) or []
                add_list_right = rec.get("add_after_list", []) or []
                left_abs, right_abs = [], []

                for e in add_list_left:
                    ap = _get_composite_path_for_record(e, paths, "ctx")
                    if ap and os.path.exists(ap):
                        left_abs.append(ap)
                if include_after:
                    for e in add_list_right:
                        ap = _get_composite_path_for_record(e, paths, "ctx")
                        if ap and os.path.exists(ap):
                            right_abs.append(ap)

                if left_abs or right_abs:
                    _draw_gallery_fixed(pdf, left_abs, right_abs, "Zusatzbilder Audit", "Zusatzbilder Nacharbeit")

    # Output ----------------------------------------------------------------------------------
    try:
        out = pdf.output(dest="S")
        if isinstance(out, bytes):
            return out
        if isinstance(out, str):
            return out.encode("latin-1")
        raise ValueError("PDF-Export: Unerwartetes Format.")
    except Exception as ex:
        pdf_fb = PDFU()
        pdf_fb.add_page(orientation="L")
        pdf_fb.set_u("", 12)
        pdf_fb.multi_cell(0, 8, pdf_fb.safe(f"PDF-Generierung fehlgeschlagen: {ex}"))
        out_fb = pdf_fb.output(dest="S")
        return out_fb if isinstance(out_fb, bytes) else str(out_fb).encode("latin-1")