# =============================================================================
# INHALTSANGABE VISUALIZATION ENHANCEMENT
# =============================================================================
# This module provides an enhanced visualization for the Fehlerbilder table
# in the Inhaltsangabe tab, with MULTISELECTION SUPPORT for Fahrzeugbereich
# and System/Domäne displayed as color-coded badges.
#
# ENHANCED: Added hover tooltips for Nacharbeitsmaßnahme and Kommentar Nacharbeit
# across ALL view modes (Mit Badges, Hierarchisch, Kompakt, Klassisch).
#==============================================================================

import streamlit as st
from html import escape as html_escape
from typing import List, Dict, Tuple, Callable

from common import (
    VEHICLE_AREA_LABELS,
    SYSTEM_DOMAIN_LABELS,
    SORT_ORDER_BI,
    fehlerbild_sort_key,
)


# =============================================================================
# STYLING CONSTANTS
# =============================================================================

# Color scheme for vehicle areas (background colors for section headers)
AREA_COLORS: Dict[str, str] = {
    "Front_Exterieur": "#E3F2FD",      # Light Blue
    "Rechte_Seite": "#FFF3E0",          # Light Orange
    "Heck_Exterieur": "#F3E5F5",        # Light Purple
    "Linke_Seite": "#FFF3E0",           # Light Orange 
    "Dach": "#E8F5E9",                  # Light Green
    "Interieur_Vorne": "#FFFDE7",       # Light Yellow
    "Interieur_Hinten": "#FFFDE7",      # Light Yellow
    "Motorraum": "#FFEBEE",             # Light Red
    "Unterboden": "#ECEFF1",            # Light Grey
}

# Badge colors for vehicle areas (text_color, background_color)
AREA_BADGE_COLORS: Dict[str, Tuple[str, str]] = {
    "Front_Exterieur": ("#1565C0", "#E3F2FD"),      # Blue
    "Rechte_Seite": ("#EF6C00", "#FFF3E0"),          # Orange
    "Heck_Exterieur": ("#7B1FA2", "#F3E5F5"),        # Purple
    "Linke_Seite": ("#EF6C00", "#FFF3E0"),           # Orange
    "Dach": ("#2E7D32", "#E8F5E9"),                  # Green
    "Interieur_Vorne": ("#F9A825", "#FFFDE7"),       # Yellow
    "Interieur_Hinten": ("#F9A825", "#FFFDE7"),      # Yellow
    "Motorraum": ("#C62828", "#FFEBEE"),             # Red
    "Unterboden": ("#546E7A", "#ECEFF1"),            # Grey
}

# Badge colors for systems (text_color, background_color)
SYSTEM_BADGE_COLORS: Dict[str, Tuple[str, str]] = {
    "Karosserie": ("#4E342E", "#EFEBE9"),    # Brown
    "Lack": ("#AD1457", "#FCE4EC"),          # Pink
    "Exterieur": ("#1565C0", "#E3F2FD"),     # Blue
    "Interieur": ("#6A1B9A", "#F3E5F5"),     # Purple
    "Elektrik": ("#FF6F00", "#FFF8E1"),      # Amber
    "Antrieb": ("#2E7D32", "#E8F5E9"),       # Green
    "Fahrwerk": ("#37474F", "#ECEFF1"),      # Blue Grey
    "Software": ("#0277BD", "#E1F5FE"),      # Light Blue
    "Sonstige": ("#757575", "#FAFAFA"),      # Grey
}

AREA_SHORT_LABELS: Dict[str, str] = {
    "Front_Exterieur": "Front",
    "Rechte_Seite": "Rechts",
    "Heck_Exterieur": "Heck",
    "Linke_Seite": "Links",
    "Dach": "Dach",
    "Interieur_Vorne": "Int.V",
    "Interieur_Hinten": "Int.H",
    "Motorraum": "Motor",
    "Unterboden": "Unter",
}

SYSTEM_SHORT_LABELS: Dict[str, str] = {
    "Karosserie": "Karos.",
    "Lack": "Lack",
    "Exterieur": "Ext.",
    "Interieur": "Int.",
    "Elektrik": "Elek.",
    "Antrieb": "Antr.",
    "Fahrwerk": "Fahrw.",
    "Software": "SW",
    "Sonstige": "Sonst.",
}

# Icons for vehicle areas
AREA_ICONS: Dict[str, str] = {
    "Front_Exterieur": "🚗",
    "Rechte_Seite": "➡️",
    "Heck_Exterieur": "🔙",
    "Linke_Seite": "⬅️",
    "Dach": "⬆️",
    "Interieur_Vorne": "🪑",
    "Interieur_Hinten": "💺",
    "Motorraum": "⚙️",
    "Unterboden": "⬇️",
}

# Icons for systems
SYSTEM_ICONS: Dict[str, str] = {
    "Karosserie": "🏗️",
    "Lack": "🎨",
    "Exterieur": "🚙",
    "Interieur": "🛋️",
    "Elektrik": "⚡",
    "Antrieb": "🔧",
    "Fahrwerk": "🔩",
    "Software": "💻",
    "Sonstige": "📦",
}


# =============================================================================
# NACHARBEIT INFO TOOLTIP HELPER FUNCTIONS
# =============================================================================

def escape_tooltip_text(text: str) -> str:
    """
    Escape text for use in HTML title attributes.
    Handles special characters to prevent breaking HTML.
    """
    if not text:
        return ""
    # Escape HTML entities
    escaped = html_escape(str(text))
    # Replace newlines with HTML entity for tooltip line breaks
    escaped = escaped.replace("\n", "&#10;")
    escaped = escaped.replace("\r", "")
    # Replace quotes that might break the attribute
    escaped = escaped.replace('"', "&quot;")
    escaped = escaped.replace("'", "&#39;")
    return escaped


def build_nacharbeit_tooltip(rec: dict) -> str:
    """
    Build tooltip text from Nacharbeitsmaßnahme and Kommentar Nacharbeit fields.
    
    Args:
        rec: The Fehlerbild record dictionary
        
    Returns:
        Escaped HTML tooltip text, or empty string if no content
    """
    f = rec.get("fehler", {}) or {}
    
    nacharbeitsmassnahme = f.get("Nacharbeitsmassnahme", "") or f.get("Nacharbeitsvorschlag", "") or ""
    kommentar_nacharbeit = f.get("Kommentar_Nacharbeit", "") or ""
    
    parts = []
    
    if nacharbeitsmassnahme.strip():
        parts.append(f"📋 Nacharbeitsmaßnahme:\n{nacharbeitsmassnahme.strip()}")
    
    if kommentar_nacharbeit.strip():
        parts.append(f"💬 Kommentar Nacharbeit:\n{kommentar_nacharbeit.strip()}")
    
    if not parts:
        return ""
    
    tooltip_text = "\n\n".join(parts)
    return escape_tooltip_text(tooltip_text)


def render_nacharbeit_info_icon(rec: dict, unique_key: str = "") -> str:
    """
    Generate HTML for a Nacharbeit info icon with a custom, CSS-based tooltip.

    The visual style (including text size) is controlled via the
    `.na-tooltip-*` CSS classes injected in render_inhaltsangabe_tab().
    """
    tooltip = build_nacharbeit_tooltip(rec)

    if not tooltip:
        # Placeholder to keep the layout stable
        return '<span class="na-tooltip-placeholder">○</span>'

    # We keep tooltip HTML-escaped (from build_nacharbeit_tooltip), but
    # now show it in a custom tooltip span instead of a native title=""
    return f"""
<span class="na-tooltip-wrapper">
    🛠️
    <span class="na-tooltip-text">{tooltip}</span>
</span>
"""

def render_nacharbeit_info_badge(rec: dict, compact: bool = False) -> str:
    """
    Generate HTML for a Nacharbeit info badge with a custom, CSS-based tooltip.

    Used especially in the Kompakt view. Visual style is controlled by the
    `.na-tooltip-*` classes injected in render_inhaltsangabe_tab().
    """
    tooltip = build_nacharbeit_tooltip(rec)

    if not tooltip:
        # Placeholder to keep layout stable in compact view
        return '<span class="na-tooltip-placeholder-badge">—</span>'

    # Label: in compact view only the icon, in other views "🛠️ Info"
    label = "🛠️" if compact else "🛠️ Info"

    return f"""
<span class="na-tooltip-wrapper na-tooltip-wrapper-badge">
    <span class="na-badge-label">{label}</span>
    <span class="na-tooltip-text">{tooltip}</span>
</span>
"""

def has_nacharbeit_info(rec: dict) -> bool:
    """
    Check if a record has any Nacharbeit information to display.
    
    Args:
        rec: The Fehlerbild record dictionary
        
    Returns:
        True if record has Nacharbeitsmaßnahme or Kommentar Nacharbeit
    """
    f = rec.get("fehler", {}) or {}
    nacharbeitsmassnahme = f.get("Nacharbeitsmassnahme", "") or f.get("Nacharbeitsvorschlag", "") or ""
    kommentar_nacharbeit = f.get("Kommentar_Nacharbeit", "") or ""
    return bool(nacharbeitsmassnahme.strip() or kommentar_nacharbeit.strip())


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_area_label(area_key: str) -> str:
    """Get human-readable label for vehicle area."""
    return VEHICLE_AREA_LABELS.get(area_key, area_key or "Nicht zugewiesen")


def get_system_label(system_key: str) -> str:
    """Get human-readable label for system/domain."""
    return SYSTEM_DOMAIN_LABELS.get(system_key, system_key or "Nicht zugewiesen")


def get_area_icon(area_key: str) -> str:
    """Get icon for vehicle area."""
    return AREA_ICONS.get(area_key, "📍")


def get_system_icon(system_key: str) -> str:
    """Get icon for system/domain."""
    return SYSTEM_ICONS.get(system_key, "🔹")


def get_all_areas(rec: dict) -> List[str]:
    """
    Get all vehicle areas for a record (supports multiselection).
    Returns list from vehicle_area_multi if available, else single vehicle_area.
    """
    f = rec.get("fehler", {}) or {}
    multi = f.get("vehicle_area_multi")
    if multi and isinstance(multi, list) and len(multi) > 0:
        return multi
    single = f.get("vehicle_area")
    return [single] if single else []


def get_all_systems(rec: dict) -> List[str]:
    """
    Get all systems for a record (supports multiselection).
    Returns list from system_domain_multi if available, else single system_domain.
    """
    f = rec.get("fehler", {}) or {}
    multi = f.get("system_domain_multi")
    if multi and isinstance(multi, list) and len(multi) > 0:
        return multi
    single = f.get("system_domain")
    return [single] if single else []


def get_primary_area(rec: dict) -> str:
    """Get the primary (first) vehicle area for sorting/grouping."""
    f = rec.get("fehler", {}) or {}
    return f.get("vehicle_area", "") or "Nicht_zugewiesen"


def get_primary_system(rec: dict) -> str:
    """Get the primary (first) system for sorting/grouping."""
    f = rec.get("fehler", {}) or {}
    return f.get("system_domain", "") or "Sonstige"


def render_area_badges(areas: List[str], exclude: str = None) -> str:
    """
    Generate HTML for area badges.
    
    Args:
        areas: List of area keys to render
        exclude: Optional area key to exclude (e.g., when already shown in header)
    """
    if not areas:
        return '<span style="color: #999;">—</span>'
    
    # Filter out excluded area if specified
    display_areas = [a for a in areas if a != exclude] if exclude else areas
    
    if not display_areas:
        return '<span style="color: #999;">—</span>'
    
    badges = []
    for area in display_areas:
        text_color, bg_color = AREA_BADGE_COLORS.get(area, ("#666", "#EEE"))
        label = AREA_SHORT_LABELS.get(area, (area or "?")[:6])
        full_label = VEHICLE_AREA_LABELS.get(area, area or "Unbekannt")
        badges.append(
            f'<span title="{full_label}" style="'
            f'background: {bg_color}; '
            f'color: {text_color}; '
            f'padding: 2px 6px; '
            f'border-radius: 4px; '
            f'font-size: 0.75rem; '
            f'font-weight: 600; '
            f'margin-right: 3px; '
            f'display: inline-block; '
            f'border: 1px solid {text_color}20; '
            f'white-space: nowrap;'
            f'">{label}</span>'
        )
    return "".join(badges)


def render_system_badges(systems: List[str], exclude: str = None) -> str:
    """
    Generate HTML for system badges.
    
    Args:
        systems: List of system keys to render
        exclude: Optional system key to exclude
    """
    if not systems:
        return '<span style="color: #999;">—</span>'
    
    display_systems = [s for s in systems if s != exclude] if exclude else systems
    
    if not display_systems:
        return '<span style="color: #999;">—</span>'
    
    badges = []
    for system in display_systems:
        text_color, bg_color = SYSTEM_BADGE_COLORS.get(system, ("#666", "#EEE"))
        label = SYSTEM_SHORT_LABELS.get(system, (system or "?")[:5])
        full_label = SYSTEM_DOMAIN_LABELS.get(system, system or "Unbekannt")
        badges.append(
            f'<span title="{full_label}" style="'
            f'background: {bg_color}; '
            f'color: {text_color}; '
            f'padding: 2px 6px; '
            f'border-radius: 4px; '
            f'font-size: 0.75rem; '
            f'font-weight: 600; '
            f'margin-right: 3px; '
            f'display: inline-block; '
            f'border: 1px solid {text_color}20; '
            f'white-space: nowrap;'
            f'">{label}</span>'
        )
    return "".join(badges)


def render_badge_legend() -> None:
    """Render a collapsible legend explaining the badge colors."""
    with st.expander("🏷️ Legende Badges", expanded=False):
        leg_col1, leg_col2, leg_col3 = st.columns(3)
        with leg_col1:
            st.markdown("**Fahrzeugbereiche:**")
            for area_key, (text_c, bg_c) in AREA_BADGE_COLORS.items():
                label = AREA_SHORT_LABELS.get(area_key, area_key)
                full = VEHICLE_AREA_LABELS.get(area_key, area_key)
                st.markdown(
                    f'<span style="background:{bg_c};color:{text_c};padding:2px 6px;'
                    f'border-radius:4px;font-size:0.75rem;font-weight:600;'
                    f'border:1px solid {text_c}20;">{label}</span> = {full}',
                    unsafe_allow_html=True
                )
        with leg_col2:
            st.markdown("**System/Domäne:**")
            for sys_key, (text_c, bg_c) in SYSTEM_BADGE_COLORS.items():
                label = SYSTEM_SHORT_LABELS.get(sys_key, sys_key)
                full = SYSTEM_DOMAIN_LABELS.get(sys_key, sys_key)
                st.markdown(
                    f'<span style="background:{bg_c};color:{text_c};padding:2px 6px;'
                    f'border-radius:4px;font-size:0.75rem;font-weight:600;'
                    f'border:1px solid {text_c}20;">{label}</span> = {full}',
                    unsafe_allow_html=True
                )
        with leg_col3:
            st.markdown("**Nacharbeit Info:**")
            st.markdown(
                '<span style="background:linear-gradient(135deg, #E8F5E9 0%, #C8E6C9 100%);'
                'color:#2E7D32;padding:2px 6px;border-radius:4px;font-size:0.75rem;'
                'font-weight:600;border:1px solid #A5D6A7;">🛠️ Info</span> = '
                'Hover für Nacharbeitsmaßnahme & Kommentar',
                unsafe_allow_html=True
            )
            st.markdown(
                '<span style="color:#DDD;">○</span> = Keine Nacharbeit-Info vorhanden',
                unsafe_allow_html=True
            )


def group_fehlerbilder(rows: List[Tuple[int, dict]]) -> Dict[str, Dict[str, List[Tuple[int, dict]]]]:
    """
    Group Fehlerbilder by PRIMARY Bereich → PRIMARY System.
    
    Args:
        rows: List of (base_index, record) tuples, already sorted by fehlerbild_sort_key
        
    Returns:
        Nested dict: {bereich: {system: [(idx, rec), ...]}}
    """
    grouped: Dict[str, Dict[str, List[Tuple[int, dict]]]] = {}
    
    for idx, rec in rows:
        bereich = get_primary_area(rec)
        system = get_primary_system(rec)
        
        if bereich not in grouped:
            grouped[bereich] = {}
        if system not in grouped[bereich]:
            grouped[bereich][system] = []
        
        grouped[bereich][system].append((idx, rec))
    
    return grouped


# =============================================================================
# VIEW 1: FLAT TABLE WITH BADGE COLUMNS (Shows all multiselections)
# =============================================================================

def render_inhaltsangabe_with_badges(
    rows: List[Tuple[int, dict]],
    safe_rerun: Callable,
    TAB_EDITOR: str,
    only_open: bool = False,
    nacharbeit_filter: str = "Alle",
    max_chars: int = 100,
) -> None:
    """
    Render Inhaltsangabe as a flat table with badge columns for Bereich and System.
    Shows ALL multiselections without duplicating rows.
    ENHANCED: Added Nacharbeit info icon column with hover tooltip.
    
    Args:
        rows: List of (base_index, record) tuples, pre-sorted
        safe_rerun: Streamlit rerun function
        TAB_EDITOR: Tab constant for navigation
        only_open: Filter for open cases only
        nacharbeit_filter: Filter for Nacharbeit status
        max_chars: Max characters before truncation
    """
    
    # Helper functions
    def _nacharbeit_flag(rec):
        f = rec.get("fehler", {}) or {}
        return bool(f.get("Nacharbeit_done", False))
    
    def _status_flag(rec):
        f = rec.get("fehler", {}) or {}
        return f.get("CaseStatus", "Open")
    
    # Apply filters
    filtered_rows = rows
    if only_open:
        filtered_rows = [(i, r) for (i, r) in filtered_rows if _status_flag(r) != "Closed"]
    if nacharbeit_filter == "Nur Nacharbeit = Ja":
        filtered_rows = [(i, r) for (i, r) in filtered_rows if _nacharbeit_flag(r)]
    elif nacharbeit_filter == "Nur Nacharbeit = Nein":
        filtered_rows = [(i, r) for (i, r) in filtered_rows if not _nacharbeit_flag(r)]
    
    if not filtered_rows:
        st.info("Keine Fehlerbilder gefunden, die den Filtern entsprechen.")
        return
    
    # Summary metrics
    total_count = len(filtered_rows)
    open_count = sum(1 for _, r in filtered_rows if _status_flag(r) != "Closed")
    
    # Count unique areas and systems across all records (including multiselections)
    all_areas_set = set()
    all_systems_set = set()
    nacharbeit_info_count = 0
    for _, r in filtered_rows:
        all_areas_set.update(get_all_areas(r))
        all_systems_set.update(get_all_systems(r))
        if has_nacharbeit_info(r):
            nacharbeit_info_count += 1
    
    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
    col_m1.metric("Fehlerbilder", total_count)
    col_m2.metric("Bereiche", len(all_areas_set))
    col_m3.metric("Systeme", len(all_systems_set))
    col_m4.metric("Offen", open_count, delta=f"{total_count - open_count} geschlossen" if open_count < total_count else None)
    col_m5.metric("Mit NA-Info", nacharbeit_info_count)
    
    st.markdown("---")
    
    # Legend
    render_badge_legend()
    
    # Table header - added Info column
    header_cols = st.columns([0.5, 1.3, 1.3, 1.3, 1.3, 0.7, 0.5, 0.6, 0.4])
    header_cols[0].markdown("**Nr**")
    header_cols[1].markdown("**Bereich**")
    header_cols[2].markdown("**System**")
    header_cols[3].markdown("**Fehlerort**")
    header_cols[4].markdown("**Fehlerart**")
    header_cols[5].markdown("**Status**")
    header_cols[6].markdown("**NA**")
    header_cols[7].markdown("**Info**")
    header_cols[8].markdown("**Öffnen**")
    
    for base_idx, r in filtered_rows:
        f = r.get("fehler", {}) or {}
        case_status = f.get("CaseStatus", "Open")
        nacharbeit_done = bool(f.get("Nacharbeit_done", False))
        
        cols = st.columns([0.5, 1.3, 1.3, 1.3, 1.3, 0.7, 0.5, 0.6, 0.4])
        
        nr = r.get("nr", "")
        fehlerort = f.get("Fehlerort", "")
        fehlerart = ", ".join(f.get("Fehlerart", []) or [])
        
        # Get multiselection values
        areas = get_all_areas(r)
        systems = get_all_systems(r)
        
        cols[0].write(nr)
        
        # Render badges for areas
        cols[1].markdown(render_area_badges(areas), unsafe_allow_html=True)
        
        # Render badges for systems
        cols[2].markdown(render_system_badges(systems), unsafe_allow_html=True)
        
        # Truncate fehlerort if needed
        if len(fehlerort) > 25:
            fehlerort_display = fehlerort[:22] + "..."
        else:
            fehlerort_display = fehlerort
        cols[3].write(fehlerort_display)
        
        # Truncate fehlerart if needed
        if len(fehlerart) > 25:
            fehlerart_display = fehlerart[:22] + "..."
        else:
            fehlerart_display = fehlerart
        cols[4].write(fehlerart_display)
        
        # Status with color
        if case_status == "Closed":
            status_html = '<span style="color: #009900; font-weight: 600;">✓ Closed</span>'
        else:
            status_html = '<span style="color: #cc0000; font-weight: 600;">○ Open</span>'
        cols[5].markdown(status_html, unsafe_allow_html=True)
        
        # Nacharbeit
        cols[6].write("✅" if nacharbeit_done else "❌")
        
        # Nacharbeit Info icon with tooltip
        cols[7].markdown(render_nacharbeit_info_icon(r, f"badge_{base_idx}"), unsafe_allow_html=True)
        
        # Open button
        if cols[8].button("➡️", key=f"toc_badge_open_{base_idx}"):
            st.session_state["current_idx"] = base_idx
            st.session_state["canvas_ver"] = st.session_state.get("canvas_ver", 0) + 1
            st.session_state["main_tab"] = TAB_EDITOR
            st.session_state["scroll_to_top"] = True
            safe_rerun()


# =============================================================================
# VIEW 2: HIERARCHICAL SECTIONS WITH ADDITIONAL BADGES
# =============================================================================

def render_inhaltsangabe_hierarchical(
    rows: List[Tuple[int, dict]],
    safe_rerun: Callable,
    TAB_EDITOR: str,
    only_open: bool = False,
    nacharbeit_filter: str = "Alle",
    max_chars: int = 120,
) -> None:
    """
    Render Inhaltsangabe with hierarchical grouping by PRIMARY Bereich → PRIMARY System.
    Additional selections are shown as badges in a dedicated column.
    ENHANCED: Added Nacharbeit info icon column with hover tooltip.
    
    Args:
        rows: List of (base_index, record) tuples, pre-sorted
        safe_rerun: Streamlit rerun function
        TAB_EDITOR: Tab constant for navigation
        only_open: Filter for open cases only
        nacharbeit_filter: Filter for Nacharbeit status
        max_chars: Max characters before truncation
    """
    
    # Helper functions
    def _nacharbeit_flag(rec):
        f = rec.get("fehler", {}) or {}
        return bool(f.get("Nacharbeit_done", False))
    
    def _status_flag(rec):
        f = rec.get("fehler", {}) or {}
        return f.get("CaseStatus", "Open")
    
    # Apply filters
    filtered_rows = rows
    if only_open:
        filtered_rows = [(i, r) for (i, r) in filtered_rows if _status_flag(r) != "Closed"]
    if nacharbeit_filter == "Nur Nacharbeit = Ja":
        filtered_rows = [(i, r) for (i, r) in filtered_rows if _nacharbeit_flag(r)]
    elif nacharbeit_filter == "Nur Nacharbeit = Nein":
        filtered_rows = [(i, r) for (i, r) in filtered_rows if not _nacharbeit_flag(r)]
    
    if not filtered_rows:
        st.info("Keine Fehlerbilder gefunden, die den Filtern entsprechen.")
        return
    
    # Group by PRIMARY Bereich → PRIMARY System
    grouped = group_fehlerbilder(filtered_rows)
    
    # Statistics summary
    total_count = len(filtered_rows)
    bereich_count = len(grouped)
    system_count = sum(len(systems) for systems in grouped.values())
    open_count = sum(1 for _, r in filtered_rows if _status_flag(r) != "Closed")
    nacharbeit_info_count = sum(1 for _, r in filtered_rows if has_nacharbeit_info(r))
    
    # Summary bar
    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
    col_s1.metric("Gesamt", total_count)
    col_s2.metric("Bereiche", bereich_count)
    col_s3.metric("Systeme", system_count)
    col_s4.metric("Offen", open_count, delta=None if open_count == total_count else f"{total_count - open_count} geschlossen")
    col_s5.metric("Mit NA-Info", nacharbeit_info_count)
    
    st.markdown("---")
    
    # Legend for badges
    render_badge_legend()
    
    # Render each Bereich section
    for bereich, systems in grouped.items():
        bereich_label = get_area_label(bereich)
        bereich_icon = get_area_icon(bereich)
        bereich_color = AREA_COLORS.get(bereich, "#F5F5F5")
        bereich_total = sum(len(items) for items in systems.values())
        
        # Bereich header with colored background
        st.markdown(
            f"""
            <div style="
                background: linear-gradient(90deg, {bereich_color} 0%, #FFFFFF 100%);
                padding: 12px 16px;
                border-radius: 8px 8px 0 0;
                border-left: 4px solid #00ccb8;
                margin-top: 16px;
            ">
                <span style="font-size: 1.3rem; font-weight: 700; color: #1a1a1a;">
                    {bereich_icon} {bereich_label}
                </span>
                <span style="
                    background: #00ccb8;
                    color: white;
                    padding: 2px 10px;
                    border-radius: 12px;
                    font-size: 0.85rem;
                    margin-left: 12px;
                    font-weight: 600;
                ">
                    {bereich_total} Fehler
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        # Render each System within this Bereich
        for system, items in systems.items():
            system_label = get_system_label(system)
            system_icon = get_system_icon(system)
            
            # System subheader
            st.markdown(
                f"""
                <div style="
                    background: #FAFAFA;
                    padding: 8px 16px 8px 32px;
                    border-left: 4px solid #E0E0E0;
                    margin-bottom: 4px;
                ">
                    <span style="font-size: 1.05rem; font-weight: 600; color: #424242;">
                        {system_icon} {system_label}
                    </span>
                    <span style="color: #757575; font-size: 0.85rem; margin-left: 8px;">
                        ({len(items)} Einträge)
                    </span>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            # Table header for this group - includes columns for additional selections + Info
            hdr_cols = st.columns([0.4, 0.9, 0.9, 1.2, 1.2, 0.6, 0.4, 0.5, 0.35])
            hdr_cols[0].markdown("**Nr**")
            hdr_cols[1].markdown("**+Bereiche**")
            hdr_cols[2].markdown("**+Systeme**")
            hdr_cols[3].markdown("**Fehlerort**")
            hdr_cols[4].markdown("**Fehlerart**")
            hdr_cols[5].markdown("**Status**")
            hdr_cols[6].markdown("**NA**")
            hdr_cols[7].markdown("**Info**")
            hdr_cols[8].markdown("**Öffnen**")
            
            # Rows for this group
            for base_idx, r in items:
                f = r.get("fehler", {}) or {}
                case_status = f.get("CaseStatus", "Open")
                nacharbeit_done = bool(f.get("Nacharbeit_done", False))
                
                cols = st.columns([0.4, 0.9, 0.9, 1.2, 1.2, 0.6, 0.4, 0.5, 0.35])
                
                nr = r.get("nr", "")
                fehlerort = f.get("Fehlerort", "")[:22]
                fehlerart = ", ".join(f.get("Fehlerart", []) or [])[:22]
                
                # Get ALL areas and systems
                all_areas = get_all_areas(r)
                all_systems = get_all_systems(r)
                
                # Get additional areas (excluding the primary/grouping one)
                additional_areas = [a for a in all_areas if a != bereich]
                additional_systems = [s for s in all_systems if s != system]
                
                cols[0].write(nr)
                
                # Show additional areas (if any)
                if additional_areas:
                    cols[1].markdown(render_area_badges(additional_areas), unsafe_allow_html=True)
                else:
                    cols[1].markdown('<span style="color:#CCC;">—</span>', unsafe_allow_html=True)
                
                # Show additional systems (if any)
                if additional_systems:
                    cols[2].markdown(render_system_badges(additional_systems), unsafe_allow_html=True)
                else:
                    cols[2].markdown('<span style="color:#CCC;">—</span>', unsafe_allow_html=True)
                
                cols[3].write(fehlerort)
                cols[4].write(fehlerart)
                
                if case_status == "Closed":
                    cols[5].markdown('<span style="color:#009900;font-weight:600;">✓ Closed</span>', unsafe_allow_html=True)
                else:
                    cols[5].markdown('<span style="color:#cc0000;font-weight:600;">○ Open</span>', unsafe_allow_html=True)
                
                cols[6].write("✅" if nacharbeit_done else "❌")
                
                # Nacharbeit Info icon with tooltip
                cols[7].markdown(render_nacharbeit_info_icon(r, f"hier_{base_idx}"), unsafe_allow_html=True)
                
                if cols[8].button("➡️", key=f"toc_hier_open_{base_idx}"):
                    st.session_state["current_idx"] = base_idx
                    st.session_state["canvas_ver"] = st.session_state.get("canvas_ver", 0) + 1
                    st.session_state["main_tab"] = TAB_EDITOR
                    st.session_state["scroll_to_top"] = True
                    safe_rerun()
        
        # Visual separator between Bereiche
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)


# =============================================================================
# VIEW 3: EXPANDER-BASED VIEW
# =============================================================================

def render_inhaltsangabe_expanders(
    rows: List[Tuple[int, dict]],
    safe_rerun: Callable,
    TAB_EDITOR: str,
    only_open: bool = False,
    nacharbeit_filter: str = "Alle",
    max_chars: int = 120,
) -> None:
    """
    Render Inhaltsangabe with expandable sections per Bereich.
    Shows all multiselections as badges.
    ENHANCED: Added Nacharbeit info icon column with hover tooltip.
    """
    
    def _nacharbeit_flag(rec):
        f = rec.get("fehler", {}) or {}
        return bool(f.get("Nacharbeit_done", False))
    
    def _status_flag(rec):
        f = rec.get("fehler", {}) or {}
        return f.get("CaseStatus", "Open")
    
    # Apply filters
    filtered_rows = rows
    if only_open:
        filtered_rows = [(i, r) for (i, r) in filtered_rows if _status_flag(r) != "Closed"]
    if nacharbeit_filter == "Nur Nacharbeit = Ja":
        filtered_rows = [(i, r) for (i, r) in filtered_rows if _nacharbeit_flag(r)]
    elif nacharbeit_filter == "Nur Nacharbeit = Nein":
        filtered_rows = [(i, r) for (i, r) in filtered_rows if not _nacharbeit_flag(r)]
    
    if not filtered_rows:
        st.info("Keine Fehlerbilder gefunden, die den Filtern entsprechen.")
        return
    
    # Group by PRIMARY Bereich
    grouped = group_fehlerbilder(filtered_rows)
    
    # Summary
    total_count = len(filtered_rows)
    nacharbeit_info_count = sum(1 for _, r in filtered_rows if has_nacharbeit_info(r))
    st.markdown(f"**{total_count} Fehlerbilder** in **{len(grouped)} Bereichen** ({nacharbeit_info_count} mit NA-Info)")
    
    # Legend
    render_badge_legend()
    
    # Render expanders for each Bereich
    for bereich, systems in grouped.items():
        bereich_label = get_area_label(bereich)
        bereich_icon = get_area_icon(bereich)
        bereich_total = sum(len(items) for items in systems.values())
        open_in_bereich = sum(
            1 for items in systems.values() 
            for _, r in items 
            if _status_flag(r) != "Closed"
        )
        
        # Expander title with counts
        expander_title = f"{bereich_icon} {bereich_label} — {bereich_total} Fehler"
        if open_in_bereich > 0:
            expander_title += f" ({open_in_bereich} offen)"
        
        with st.expander(expander_title, expanded=False):
            for system, items in systems.items():
                system_label = get_system_label(system)
                system_icon = get_system_icon(system)
                
                st.markdown(f"#### {system_icon} {system_label} ({len(items)})")
                
                # Build DataFrame for display with badges
                for base_idx, r in items:
                    f = r.get("fehler", {}) or {}
                    
                    # Get all selections
                    all_areas = get_all_areas(r)
                    all_systems = get_all_systems(r)
                    additional_areas = [a for a in all_areas if a != bereich]
                    additional_systems = [s for s in all_systems if s != system]
                    
                    # Row layout - added Info column
                    # Row layout - add Fehlerart column right of Fehlerort
                    row_cols = st.columns([0.4, 1.2, 1.2, 1.55, 1.05, 0.8, 0.6, 0.45])

                    row_cols[0].write(r.get("nr", ""))

                    # Additional areas
                    if additional_areas:
                        row_cols[1].markdown(render_area_badges(additional_areas), unsafe_allow_html=True)
                    else:
                        row_cols[1].write("—")

                    # Additional systems
                    if additional_systems:
                        row_cols[2].markdown(render_system_badges(additional_systems), unsafe_allow_html=True)
                    else:
                        row_cols[2].write("—")

                    # Fehlerort (truncate)
                    fehlerort = (f.get("Fehlerort", "") or "").strip()
                    if len(fehlerort) > 28:
                        fehlerort = fehlerort[:25] + "."
                    row_cols[3].write(fehlerort or "—")

                    # Fehlerart (list -> comma separated, truncate)
                    fa_list = f.get("Fehlerart", []) or []
                    fa_text = ", ".join([x for x in fa_list if str(x).strip()])
                    if len(fa_text) > 28:
                        fa_text = fa_text[:25] + "."
                    row_cols[4].write(fa_text or "—")

                    # Status (shifted index because of new column)
                    status = f.get("CaseStatus", "Open")
                    if status == "Closed":
                        row_cols[5].markdown('<span style="color:#009900;">✓ Closed</span>', unsafe_allow_html=True)
                    else:
                        row_cols[5].markdown('<span style="color:#cc0000;">○ Open</span>', unsafe_allow_html=True)

                    # Nacharbeit Info badge with tooltip (compact version) (shifted index)
                    row_cols[6].markdown(render_nacharbeit_info_badge(r, compact=True), unsafe_allow_html=True)

                    # Open button (shifted index)
                    if row_cols[7].button("➡️", key=f"toc_exp_open_{bereich}_{system}_{base_idx}"):
                        st.session_state["current_idx"] = base_idx
                        st.session_state["canvas_ver"] = st.session_state.get("canvas_ver", 0) + 1
                        st.session_state["main_tab"] = TAB_EDITOR
                        st.session_state["scroll_to_top"] = True
                        safe_rerun()

                
                st.markdown("---")

# =============================================================================
# MAIN INTEGRATION FUNCTION
# =============================================================================

def render_inhaltsangabe_tab(
    idx: dict,
    active_audit: str,
    paths: dict,
    safe_rerun: Callable,
    TAB_EDITOR: str,
    load_index_v2: Callable,
    save_index_v2: Callable,
    reindex_audit_images: Callable,
    index_prefers_relative: Callable,
) -> None:
    """
    Complete replacement for the Inhaltsangabe tab rendering.
    Supports multiselection display with badges.
    ENHANCED: All views now include Nacharbeit info with hover tooltips.
    
    Usage in editor.py:
        elif st.session_state["main_tab"] == TAB_TOC:
            from inhaltsangabe_visualization import render_inhaltsangabe_tab
            render_inhaltsangabe_tab(
                idx, active_audit, paths, safe_rerun, TAB_EDITOR,
                load_index_v2, save_index_v2, reindex_audit_images, index_prefers_relative
            )
    """
    
    idx2 = load_index_v2(paths["index"])
    
    st.markdown('<div class="frame-title">Inhaltsangabe Fehlerbilder</div>', unsafe_allow_html=True)

        # --- Custom tooltip styling for Nacharbeit-Info icons ---
    st.markdown("""
    <style>
    .na-tooltip-wrapper {
        position: relative;
        display: inline-block;
        cursor: help;
        font-size: 1.1rem;              /* Icon size */
    }

    .na-tooltip-placeholder {
        color: #DDD;
        cursor: default;
        font-size: 1.1rem;
        display: inline-block;
    }

    .na-tooltip-wrapper .na-tooltip-text {
        visibility: hidden;
        min-width: 350px;     /* ensures width */
        max-width: 450px;     /* allows expansion */
        background-color: #333;
        color: #fff;
        text-align: left;
        padding: 10px 14px;
        border-radius: 6px;
        font-size: 1.2rem;             /* <<< TOOLTIP TEXT SIZE */
        line-height: 1.35rem;
        white-space: pre-line;          /* respects line breaks */

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
        font-size: 0.8rem;  /* smaller base size for Kompakt badge */
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
    """, unsafe_allow_html=True)
    
    all_images = idx2.get("images", [])
    images_audit_base = [r for r in all_images if r.get("audit_id") == active_audit]
    
    # --- Reindex section (keep existing functionality) ---
    with st.expander("🔢 Fehlerbilder neu nummerieren", expanded=False):
        st.markdown(
            "**Hinweis:** Diese Funktion nummeriert alle Fehlerbilder dieses Audits "
            "fortlaufend neu (001, 002, 003, ...) und benennt alle zugehörigen Dateien "
            "(Bilder, Videos, etc.) entsprechend um."
        )
        st.warning(
            "⚠️ **Achtung:** Diese Aktion kann nicht rückgängig gemacht werden. "
            "Stelle sicher, dass keine anderen Programme auf die Dateien zugreifen."
        )
        
        if images_audit_base:
            current_nrs = sorted([r.get("nr", "?") for r in images_audit_base])
            expected_nrs = [f"{i+1:03d}" for i in range(len(images_audit_base))]
            
            if current_nrs == expected_nrs:
                st.success("✅ Die Nummerierung ist bereits fortlaufend und konsistent.")
            else:
                st.info(f"Aktuelle Nummern: {', '.join(current_nrs)}")
                st.info(f"Nach Reindex: {', '.join(expected_nrs)}")
        
        reindex_confirm_key = f"confirm_reindex_{active_audit}"
        
        if st.button("🔄 Neu nummerieren starten", key=f"btn_reindex_{active_audit}"):
            st.session_state[reindex_confirm_key] = True
        
        if st.session_state.get(reindex_confirm_key, False):
            col_ri_yes, col_ri_no = st.columns(2)
            if col_ri_yes.button("✅ Ja, jetzt neu nummerieren", key=f"btn_reindex_yes_{active_audit}"):
                try:
                    idx_fresh = load_index_v2(paths["index"])
                    prefer_rel = index_prefers_relative(idx_fresh)
                    
                    count, errors = reindex_audit_images(
                        idx_fresh,
                        active_audit,
                        paths,
                        prefer_rel
                    )
                    
                    save_index_v2(paths["index"], idx_fresh)
                    
                    if errors:
                        for err in errors:
                            st.warning(err)
                    
                    st.success(f"✅ {count} Fehlerbild(er) erfolgreich neu nummeriert!")
                    st.session_state[reindex_confirm_key] = False
                    st.session_state.current_idx = 0
                    safe_rerun()
                    
                except Exception as e:
                    st.error(f"Fehler beim Neu-Nummerieren: {e}")
                    st.session_state[reindex_confirm_key] = False
            
            if col_ri_no.button("❌ Abbrechen", key=f"btn_reindex_no_{active_audit}"):
                st.session_state[reindex_confirm_key] = False
    
    st.markdown("---")
    
    # --- Filters and View Selection ---
    # Collect available Bereiche/Systeme from this audit (multiselection-aware)
    all_area_keys = set()
    all_system_keys = set()
    for r in images_audit_base:
        all_area_keys.update([a for a in get_all_areas(r) if a])
        all_system_keys.update([s for s in get_all_systems(r) if s])

    area_options = sorted(all_area_keys, key=lambda k: (VEHICLE_AREA_LABELS.get(k, k) or k))
    system_options = sorted(all_system_keys, key=lambda k: (SYSTEM_DOMAIN_LABELS.get(k, k) or k))

    col_f1, col_f2, col_f3, col_f4, col_f5, col_f6 = st.columns([1.0, 1.0, 1.4, 1.4, 1.5, 1.0])

    only_open = col_f1.checkbox("Nur offene Fälle", value=False)

    nacharbeit_filter = col_f2.selectbox(
        "Nacharbeit-Filter",
        ["Alle", "Nur Nacharbeit = Ja", "Nur Nacharbeit = Nein"],
        index=0,
    )

    selected_areas = col_f3.multiselect(
        "Bereiche",
        options=area_options,
        default=[],
        format_func=get_area_label,   # uses your existing mapping helper
        key=f"toc_filter_areas__{active_audit}",
    )

    selected_systems = col_f4.multiselect(
        "Systeme",
        options=system_options,
        default=[],
        format_func=get_system_label, # uses your existing mapping helper
        key=f"toc_filter_systems__{active_audit}",
    )

    sort_option = col_f5.selectbox(
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
    )

    # View mode selection with multiselection-aware options
    view_mode = col_f6.selectbox(
        "Ansicht",
        ["Mit Badges", "Hierarchisch", "Kompakt"],
        index=0,
        help="Mit Badges: Alle Bereiche/Systeme als farbige Tags. Hierarchisch: Gruppiert mit zusätzlichen Badges. Kompakt: Expander pro Bereich."
    )

    
    # Build rows list
    rows = [(i, r) for i, r in enumerate(images_audit_base)]

    # --- Apply Bereich/System multiselect filters (multiselection-aware) ---
    if selected_areas:
        sel_a = set(selected_areas)
        rows = [(i, r) for (i, r) in rows if set(get_all_areas(r)) & sel_a]

    if selected_systems:
        sel_s = set(selected_systems)
        rows = [(i, r) for (i, r) in rows if set(get_all_systems(r)) & sel_s]

    
    # Helper functions for sorting
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

    
    # Apply sorting
    if sort_option == "Audit-Standard (Bereich → System → BI)":
        rows.sort(key=lambda t: fehlerbild_sort_key(t[1]))
    elif sort_option == "Nr (aufsteigend)":
        rows.sort(key=lambda t: t[1].get("nr", ""))
    elif sort_option == "Nr (absteigend)":
        rows.sort(key=lambda t: t[1].get("nr", ""), reverse=True)
    elif sort_option == "BI (kritisch zuerst)":
        rows.sort(key=lambda t: _bi_index(t[1]))
    elif sort_option == "BI (unkritisch zuerst)":
        rows.sort(key=lambda t: _bi_index(t[1]), reverse=True)
    elif sort_option == "Fehlerort (A→Z)":
        rows.sort(key=lambda t: (t[1].get("fehler", {}) or {}).get("Fehlerort", "").lower())
    elif sort_option == "Fehlerort (Z→A)":
        rows.sort(key=lambda t: (t[1].get("fehler", {}) or {}).get("Fehlerort", "").lower(), reverse=True)
    elif sort_option == "Status (Open zuerst)":
        rows.sort(key=lambda t: 0 if _status_flag(t[1]) != "Closed" else 1)
    elif sort_option == "Status (Closed zuerst)":
        rows.sort(key=lambda t: 0 if _status_flag(t[1]) == "Closed" else 1)
    elif sort_option == "Nacharbeit = Ja zuerst":
        rows.sort(key=lambda t: 0 if _nacharbeit_flag(t[1]) else 1)
    elif sort_option == "Nacharbeit = Nein zuerst":
        rows.sort(key=lambda t: 0 if not _nacharbeit_flag(t[1]) else 1)
    
    # Render based on selected view mode
    if view_mode == "Mit Badges":
        render_inhaltsangabe_with_badges(
            rows, safe_rerun, TAB_EDITOR, only_open, nacharbeit_filter
        )
    elif view_mode == "Hierarchisch":
        render_inhaltsangabe_hierarchical(
            rows, safe_rerun, TAB_EDITOR, only_open, nacharbeit_filter
        )
    else:
        render_inhaltsangabe_expanders(
            rows, safe_rerun, TAB_EDITOR, only_open, nacharbeit_filter
        )