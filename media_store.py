# media_store.py
# This module implements a centralized media storage system with IMMUTABLE base
# media and MUTABLE canvas overlays.
#
# KEY CONCEPTS:
# - Base media (images/videos) are stored ONCE with UUID-based names
# - Base media names NEVER change after upload
# - **DEDUPLICATION**: Content-hash (SHA256) ensures identical files are never duplicated
# - Canvas overlays are separate transparent PNGs containing only drawings
# - Only canvas overlay files are renamed during reindex operations
# - UI displays canvas overlay names, not base media names
#
# FOLDER STRUCTURE:
# GlobalMedia/
#   base_images/       - All original uploaded images (IMMUTABLE, UUID-named)
#   base_videos/       - All video files (IMMUTABLE, UUID-named)
#   overlays/          - All canvas overlays (named by audit/nr/role)
#   media_registry.json - Hash->filename mapping for deduplication
# =============================================================================

import os
import io
import json
import uuid
import hashlib
from typing import Optional, List, Dict, Tuple, Any

from PIL import Image
import pillow_heif

# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# GLOBAL MEDIA ROOT - Central storage for ALL media files
# =============================================================================
MEDIA_ROOT: str = os.path.join(BASE_DIR, "GlobalMedia")
MEDIA_BASE_IMAGES: str = os.path.join(MEDIA_ROOT, "base_images")
MEDIA_BASE_VIDEOS: str = os.path.join(MEDIA_ROOT, "base_videos")
MEDIA_OVERLAYS: str = os.path.join(MEDIA_ROOT, "overlays")
MEDIA_REGISTRY_PATH: str = os.path.join(MEDIA_ROOT, "media_registry.json")

# Legacy paths for backward compatibility during migration
MEDIA_IMAGES_RAW: str = MEDIA_BASE_IMAGES
MEDIA_IMAGES_EDITED: str = os.path.join(MEDIA_ROOT, "images_edited")
MEDIA_VIDEOS: str = MEDIA_BASE_VIDEOS

# =============================================================================
# Canvas Overlay Types (roles)
# =============================================================================
OVERLAY_FEHLERBILD = "FEHLERBILD"
OVERLAY_KONTEXT = "KONTEXT"
OVERLAY_NACHARBEIT = "NACHARBEIT"
OVERLAY_ZUSATZ_FEHLER = "ZUSATZ_FEHLER"
OVERLAY_ZUSATZ_NACHARBEIT = "ZUSATZ_NACHARBEIT"

# Legacy Media Type Constants (for backward compatibility)
MEDIA_TYPE_RAW = "RAW"
MEDIA_TYPE_EDITED = "EDITED"
MEDIA_TYPE_AFTER_RAW = "AFTER_RAW"
MEDIA_TYPE_AFTER_EDITED = "AFTER_EDITED"
MEDIA_TYPE_CTX = "CTX"
MEDIA_TYPE_CTX_EDITED = "CTX_EDITED"
MEDIA_TYPE_ADD = "ADD"
MEDIA_TYPE_ADD_EDITED = "ADD_EDITED"
MEDIA_TYPE_NADD = "NADD"
MEDIA_TYPE_NADD_EDITED = "NADD_EDITED"
MEDIA_TYPE_VIDEO = "VIDEO"

# Image quality settings
JPEG_QUALITY_FULL: int = 90
MAX_IMAGE_WIDTH: int = 1800

# =============================================================================
# UTILITY FUNCTIONS (shared with common.py)
# =============================================================================

def sanitize_filename(s: str) -> str:
    """Sanitize a string for use in filenames."""
    s = (s or "").strip()
    bad = r'<>:"/\n?*\\'
    table = str.maketrans({ch: "_" for ch in bad})
    s = s.translate(table)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def ensure_dirs_exist(*paths: str) -> None:
    """Ensure all specified directories exist."""
    for p in paths:
        if p and not os.path.exists(p):
            os.makedirs(p, exist_ok=True)


# =============================================================================
# PIL/HEIC HELPERS
# =============================================================================

def ensure_rgb(img: Image.Image) -> Image.Image:
    """Ensure image is in RGB mode."""
    return img.convert("RGB")


def decode_upload_to_pil(data: bytes, filename: str) -> Image.Image:
    """Decode uploaded bytes to PIL Image, handling HEIC format."""
    if str(filename or "").lower().endswith(".heic"):
        with io.BytesIO(data) as bio:
            heif = pillow_heif.open_heif(bio, convert_hdr_to_8bit=True)
            return ensure_rgb(heif.to_pillow())
    return ensure_rgb(Image.open(io.BytesIO(data)))


def downscale_to_width(img: Image.Image, target_w: int) -> Image.Image:
    """Downscale image to target width, preserving aspect ratio."""
    w, h = img.size
    if w <= target_w:
        return img
    scale = target_w / float(w)
    return img.resize((target_w, int(round(h * scale))), Image.LANCZOS)


def pil_to_jpg(img: Image.Image, out_path: str, quality: int = JPEG_QUALITY_FULL) -> str:
    """Save PIL image as JPEG with optional downscaling."""
    img = ensure_rgb(img)
    try:
        if MAX_IMAGE_WIDTH and img.size[0] > MAX_IMAGE_WIDTH:
            img = downscale_to_width(img, MAX_IMAGE_WIDTH)
    except Exception:
        pass
    ensure_dirs_exist(os.path.dirname(out_path))
    if not out_path.lower().endswith(".jpg"):
        out_path = os.path.splitext(out_path)[0] + ".jpg"
    img.save(out_path, format="JPEG", quality=quality, optimize=True)
    return out_path


# =============================================================================
# GLOBAL MEDIA PATH API
# =============================================================================

def ensure_media_dirs() -> None:
    """Ensure the global media directory structure exists."""
    ensure_dirs_exist(
        MEDIA_ROOT,
        MEDIA_BASE_IMAGES,
        MEDIA_BASE_VIDEOS,
        MEDIA_OVERLAYS,
        MEDIA_IMAGES_EDITED
    )


# =============================================================================
# MEDIA REGISTRY - SHA256-based deduplication
# =============================================================================

def _load_media_registry() -> Dict[str, Dict[str, str]]:
    """Load the media registry (hash -> filename mapping)."""
    ensure_media_dirs()
    if os.path.exists(MEDIA_REGISTRY_PATH):
        try:
            with open(MEDIA_REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"images": {}, "videos": {}}
    return {"images": {}, "videos": {}}


def _save_media_registry(registry: Dict[str, Dict[str, str]]) -> None:
    """Save the media registry."""
    ensure_media_dirs()
    with open(MEDIA_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def _compute_file_hash(data: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(data).hexdigest()


def _compute_pil_hash(pil_image: Image.Image) -> str:
    """Compute SHA256 hash of PIL image content (normalized)."""
    img = pil_image.convert("RGB")
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=95)
    return _compute_file_hash(bio.getvalue())


def _register_media(content_hash: str, ref: str, media_type: str = "image") -> None:
    """Register a media file in the deduplication registry."""
    registry = _load_media_registry()
    section = "images" if media_type == "image" else "videos"
    if section not in registry:
        registry[section] = {}
    registry[section][content_hash] = ref
    _save_media_registry(registry)


# =============================================================================
# REGISTRY SELF-HEALING (important for migration / missing registry)
# =============================================================================

def _scan_base_images_and_register(registry: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """(Re)build the images section from files on disk."""
    ensure_media_dirs()
    registry = registry or {"images": {}, "videos": {}}
    registry.setdefault("images", {})
    if not os.path.isdir(MEDIA_BASE_IMAGES):
        return registry

    for fn in os.listdir(MEDIA_BASE_IMAGES):
        ext = os.path.splitext(fn.lower())[1]
        if ext not in (".jpg", ".jpeg", ".png"):
            continue
        abs_path = os.path.join(MEDIA_BASE_IMAGES, fn)
        try:
            with Image.open(abs_path) as im:
                h = _compute_pil_hash(im)
            ref = f"base_images/{fn}"
            if h and ref and (h not in registry["images"]):
                registry["images"][h] = ref
        except Exception:
            continue
    return registry


def _scan_base_videos_and_register(registry: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """(Re)build the videos section from files on disk."""
    ensure_media_dirs()
    registry = registry or {"images": {}, "videos": {}}
    registry.setdefault("videos", {})
    if not os.path.isdir(MEDIA_BASE_VIDEOS):
        return registry

    for fn in os.listdir(MEDIA_BASE_VIDEOS):
        ext = os.path.splitext(fn.lower())[1]
        if ext not in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            continue
        abs_path = os.path.join(MEDIA_BASE_VIDEOS, fn)
        try:
            with open(abs_path, "rb") as f:
                data = f.read()
            h = _compute_file_hash(data)
            ref = f"base_videos/{fn}"
            if h and ref and (h not in registry["videos"]):
                registry["videos"][h] = ref
        except Exception:
            continue
    return registry


def _ensure_registry_is_populated(media_type: str) -> Dict[str, Dict[str, str]]:
    """Ensure registry contains at least the on-disk files for the given media type."""
    registry = _load_media_registry()
    section = "images" if media_type == "image" else "videos"
    if section not in registry:
        registry[section] = {}

    if not os.path.exists(MEDIA_REGISTRY_PATH) or not registry.get(section):
        if media_type == "image":
            registry = _scan_base_images_and_register(registry)
        else:
            registry = _scan_base_videos_and_register(registry)
        _save_media_registry(registry)

    return registry


def _find_existing_by_hash_or_scan(content_hash: str, media_type: str) -> Optional[str]:
    """Find an existing ref by hash; if not found, scan disk and try again."""
    if not content_hash:
        return None

    registry = _ensure_registry_is_populated(media_type)
    section = "images" if media_type == "image" else "videos"
    ref = registry.get(section, {}).get(content_hash)
    if ref:
        abs_path = resolve_media_path(ref, {})
        if abs_path and os.path.exists(abs_path):
            return ref

    if media_type == "image":
        registry = _scan_base_images_and_register(registry)
    else:
        registry = _scan_base_videos_and_register(registry)
    _save_media_registry(registry)
    return registry.get(section, {}).get(content_hash)


# =============================================================================
# BASE MEDIA FILENAME GENERATION
# =============================================================================

def generate_base_media_filename(extension: str = ".jpg") -> str:
    """Generate a unique, collision-free filename for base media (immutable)."""
    unique_id = uuid.uuid4().hex[:16]
    ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    return f"MEDIA_IMG__{unique_id}{ext}"


def generate_base_video_filename(extension: str = ".mp4") -> str:
    """Generate a unique, collision-free filename for base video (immutable)."""
    unique_id = uuid.uuid4().hex[:16]
    ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    return f"MEDIA_VID__{unique_id}{ext}"


def generate_canvas_overlay_filename(
    project_id: str, audit_id: str, nr: str, overlay_type: str, 
    index: Optional[int] = None
) -> str:
    """
    Generate a canvas overlay filename based on audit/Fehlerbild numbers.
    This is the ONLY filename type that changes during reindex.
    """
    p = sanitize_filename(project_id or "PROJ")
    a = sanitize_filename(audit_id or "AUDIT")
    n = sanitize_filename(nr or "000")
    t = sanitize_filename(overlay_type or OVERLAY_FEHLERBILD)
    if index is not None:
        return f"CANVAS__PRJ_{p}__AUD_{a}__NR_{n}__TYPE_{t}_{index}.png"
    return f"CANVAS__PRJ_{p}__AUD_{a}__NR_{n}__TYPE_{t}.png"


# =============================================================================
# PATH GETTERS
# =============================================================================

def get_base_image_path(filename: str) -> str:
    """Get full path for a base image in the global store."""
    return os.path.join(MEDIA_BASE_IMAGES, filename)


def get_base_video_path(filename: str) -> str:
    """Get full path for a base video in the global store."""
    return os.path.join(MEDIA_BASE_VIDEOS, filename)


def get_overlay_path(filename: str) -> str:
    """Get full path for a canvas overlay in the global store."""
    return os.path.join(MEDIA_OVERLAYS, filename)


# =============================================================================
# MEDIA REFERENCE DETECTION
# =============================================================================

def is_base_image_ref(ref: str) -> bool:
    """Check if a reference is a base image reference (new format)."""
    if not ref:
        return False
    return (ref.startswith("MEDIA_IMG__") or 
            ref.startswith("base_images/") or ref.startswith("base_images\\") or
            "/base_images/" in ref or "\\base_images\\" in ref)


def is_base_video_ref(ref: str) -> bool:
    """Check if a reference is a base video reference (new format)."""
    if not ref:
        return False
    return (ref.startswith("MEDIA_VID__") or 
            ref.startswith("base_videos/") or ref.startswith("base_videos\\") or
            "/base_videos/" in ref or "\\base_videos\\" in ref)


def is_overlay_ref(ref: str) -> bool:
    """Check if a reference is a canvas overlay reference."""
    if not ref:
        return False
    return (ref.startswith("CANVAS__") or 
            ref.startswith("overlays/") or ref.startswith("overlays\\") or
            "/overlays/" in ref or "\\overlays\\" in ref)


def is_global_media_ref(ref: str) -> bool:
    """Check if a reference is a global media reference (any type)."""
    if not ref or os.path.isabs(ref):
        return False
    return (
        is_base_image_ref(ref) or 
        is_base_video_ref(ref) or 
        is_overlay_ref(ref) or
        ref.startswith(("images_raw/", "images_edited/", "videos/",
                        "images_raw\\", "images_edited\\", "videos\\",
                        "base_images/", "base_videos/", "overlays/",
                        "base_images\\", "base_videos\\", "overlays\\"))
    )


# =============================================================================
# MEDIA REFERENCE RESOLUTION
# =============================================================================

def resolve_media_path(ref: str, project_paths: dict) -> Optional[str]:
    """
    Resolve a media reference to an absolute path.
    Handles new layered format, legacy format, and per-project paths.
    """
    if not ref:
        return None
    
    # Absolute path
    if os.path.isabs(ref):
        if os.path.exists(ref):
            return ref
        return None
    
    # New format: base images
    if is_base_image_ref(ref):
        if ref.startswith("MEDIA_IMG__"):
            path = get_base_image_path(ref)
            if os.path.exists(path):
                return path
        path = os.path.join(MEDIA_ROOT, ref)
        if os.path.exists(path):
            return path
    
    # New format: base videos
    if is_base_video_ref(ref):
        if ref.startswith("MEDIA_VID__"):
            path = get_base_video_path(ref)
            if os.path.exists(path):
                return path
        path = os.path.join(MEDIA_ROOT, ref)
        if os.path.exists(path):
            return path
    
    # New format: overlays
    if is_overlay_ref(ref):
        if ref.startswith("CANVAS__"):
            path = get_overlay_path(ref)
            if os.path.exists(path):
                return path
        path = os.path.join(MEDIA_ROOT, ref)
        if os.path.exists(path):
            return path
    
    # Legacy global media paths
    global_path = os.path.join(MEDIA_ROOT, ref)
    if os.path.exists(global_path):
        return global_path
    
    # Legacy per-project paths
    if project_paths and "root" in project_paths:
        legacy_path = os.path.join(project_paths["root"], ref)
        if os.path.exists(legacy_path):
            return legacy_path
    return None


def media_ref_from_path(abs_path: str, ref_type: str = "base_image") -> str:
    """
    Convert an absolute path to a storage reference.
    ref_type: 'base_image', 'base_video', or 'overlay'
    """
    if not abs_path:
        return ""
    filename = os.path.basename(abs_path)
    if ref_type == "base_image":
        return f"base_images/{filename}"
    elif ref_type == "base_video":
        return f"base_videos/{filename}"
    elif ref_type == "overlay":
        return f"overlays/{filename}"
    return filename


def media_ref_from_global_path(abs_path: str) -> str:
    """Convert an absolute global media path to a storage reference (legacy compatible)."""
    try:
        rel = os.path.relpath(abs_path, start=MEDIA_ROOT)
        if not rel.startswith(".."):
            return rel
    except Exception:
        pass
    return abs_path


# =============================================================================
# UNIFIED ATTACH MEDIA API - STRICT DEDUPLICATION
# =============================================================================

def attach_media(
    uploaded_file: Optional[Any] = None,
    uploaded_bytes: Optional[bytes] = None,
    uploaded_filename: Optional[str] = None,
    pil_image: Optional[Image.Image] = None,
    existing_ref: Optional[str] = None,
    media_type: str = "image",
) -> Optional[str]:
    """
    **CENTRAL MEDIA ATTACHMENT API**
    
    Returns a canonical reference to a base media file.
    ALL upload/attach operations MUST use this function.
    
    This function enforces:
    1. NEVER duplicate base media files
    2. Content-hash (SHA256) based deduplication
    3. If file already exists in base folder → return reference only
    
    Args:
        uploaded_file: Streamlit UploadedFile object (optional)
        uploaded_bytes: Raw bytes of the file (optional, alternative to uploaded_file)
        uploaded_filename: Filename when using uploaded_bytes
        pil_image: PIL Image object (optional, alternative to file)
        existing_ref: Path/ref to an existing file in base folder (optional)
        media_type: "image" or "video"
    
    Returns:
        Canonical reference string (e.g., "base_images/MEDIA_IMG__xxx.jpg")
        or None if operation failed.
    """
    ensure_media_dirs()
    
    # Case 1: Use existing reference (no copy needed)
    if existing_ref:
        abs_path = resolve_media_path(existing_ref, {})
        if not abs_path or not os.path.exists(abs_path):
            return None

        # Normalize to canonical ref format
        if is_base_image_ref(existing_ref) or is_base_video_ref(existing_ref):
            canonical_ref = existing_ref.replace("\\", "/")
        else:
            filename = os.path.basename(abs_path)
            canonical_ref = f"base_videos/{filename}" if media_type == "video" else f"base_images/{filename}"

        # Self-heal registry
        try:
            if media_type == "video":
                with open(abs_path, "rb") as f:
                    h = _compute_file_hash(f.read())
                if h:
                    _register_media(h, canonical_ref, "video")
            else:
                with Image.open(abs_path) as im:
                    h = _compute_pil_hash(im)
                if h:
                    _register_media(h, canonical_ref, "image")
        except Exception:
            pass

        return canonical_ref

    # Case 2: Upload new file
    if media_type == "video":
        return _attach_video(uploaded_file, uploaded_bytes, uploaded_filename)
    else:
        return _attach_image(uploaded_file, uploaded_bytes, uploaded_filename, pil_image)


def _attach_image(
    uploaded_file: Optional[Any],
    uploaded_bytes: Optional[bytes],
    uploaded_filename: Optional[str],
    pil_image: Optional[Image.Image]
) -> Optional[str]:
    """Internal: Attach an image with deduplication."""
    ensure_media_dirs()
    
    # Get PIL image
    if pil_image is not None:
        img = pil_image.convert("RGB")
    elif uploaded_file is not None:
        data = uploaded_file.read()
        filename = getattr(uploaded_file, "name", "upload.jpg")
        img = decode_upload_to_pil(data, filename)
    elif uploaded_bytes is not None:
        filename = uploaded_filename or "upload.jpg"
        img = decode_upload_to_pil(uploaded_bytes, filename)
    else:
        return None
    
    # Compute content hash for deduplication
    content_hash = _compute_pil_hash(img)
    
    # Check if identical content already exists
    existing_ref = _find_existing_by_hash_or_scan(content_hash, "image")
    if existing_ref:
        abs_path = resolve_media_path(existing_ref, {})
        if abs_path and os.path.exists(abs_path):
            return existing_ref
    
    # New file - save it
    new_filename = generate_base_media_filename(".jpg")
    abs_path = get_base_image_path(new_filename)
    pil_to_jpg(img, abs_path, JPEG_QUALITY_FULL)
    
    # Register in deduplication registry
    ref = f"base_images/{new_filename}"
    _register_media(content_hash, ref, "image")
    
    return ref


def _attach_video(
    uploaded_file: Optional[Any],
    uploaded_bytes: Optional[bytes],
    uploaded_filename: Optional[str]
) -> Optional[str]:
    """Internal: Attach a video with deduplication."""
    ensure_media_dirs()
    
    # Get bytes and filename
    if uploaded_file is not None:
        data = uploaded_file.read()
        filename = getattr(uploaded_file, "name", "video.mp4")
    elif uploaded_bytes is not None:
        data = uploaded_bytes
        filename = uploaded_filename or "video.mp4"
    else:
        return None
    
    # Compute content hash for deduplication
    content_hash = _compute_file_hash(data)
    
    # Check if identical content already exists
    existing_ref = _find_existing_by_hash_or_scan(content_hash, "video")
    if existing_ref:
        abs_path = resolve_media_path(existing_ref, {})
        if abs_path and os.path.exists(abs_path):
            return existing_ref
    
    # New file - save it
    _, ext = os.path.splitext(filename)
    ext = ext.lower() if ext else ".mp4"
    vid_filename = generate_base_video_filename(ext)
    abs_path = get_base_video_path(vid_filename)
    
    with open(abs_path, "wb") as f:
        f.write(data)
    
    # Register in deduplication registry
    ref = f"base_videos/{vid_filename}"
    _register_media(content_hash, ref, "video")
    
    return ref


# =============================================================================
# LIST EXISTING MEDIA
# =============================================================================

def list_existing_base_images() -> List[Dict[str, str]]:
    """
    List all existing base images in the global store.
    Returns list of dicts with 'ref' and 'filename' keys.
    """
    ensure_media_dirs()
    results = []
    if os.path.isdir(MEDIA_BASE_IMAGES):
        for fn in sorted(os.listdir(MEDIA_BASE_IMAGES)):
            ext = os.path.splitext(fn.lower())[1]
            if ext in (".jpg", ".jpeg", ".png"):
                results.append({
                    "ref": f"base_images/{fn}",
                    "filename": fn,
                    "abs_path": os.path.join(MEDIA_BASE_IMAGES, fn)
                })
    return results


def list_existing_base_videos() -> List[Dict[str, str]]:
    """
    List all existing base videos in the global store.
    Returns list of dicts with 'ref' and 'filename' keys.
    """
    ensure_media_dirs()
    results = []
    if os.path.isdir(MEDIA_BASE_VIDEOS):
        for fn in sorted(os.listdir(MEDIA_BASE_VIDEOS)):
            ext = os.path.splitext(fn.lower())[1]
            if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
                results.append({
                    "ref": f"base_videos/{fn}",
                    "filename": fn,
                    "abs_path": os.path.join(MEDIA_BASE_VIDEOS, fn)
                })
    return results


# =============================================================================
# SAVE BASE MEDIA
# =============================================================================

def save_base_image(pil_image: Image.Image, extension: str = ".jpg") -> Tuple[str, str]:
    """
    Save a base image to the global store with SHA256-based deduplication.
    Returns (filename, absolute_path).
    """
    ref = attach_media(pil_image=pil_image, media_type="image")
    if ref:
        filename = os.path.basename(ref.split("/")[-1])
        abs_path = resolve_media_path(ref, {})
        if abs_path:
            return filename, abs_path
    # Fallback
    ensure_media_dirs()
    filename = generate_base_media_filename(extension)
    abs_path = get_base_image_path(filename)
    pil_to_jpg(pil_image, abs_path, JPEG_QUALITY_FULL)
    return filename, abs_path


def save_base_video(video_data: bytes, original_filename: str) -> Tuple[str, str]:
    """
    Save a base video to the global store with SHA256-based deduplication.
    Returns (filename, absolute_path).
    """
    ref = attach_media(uploaded_bytes=video_data, uploaded_filename=original_filename, media_type="video")
    if ref:
        filename = os.path.basename(ref.split("/")[-1])
        abs_path = resolve_media_path(ref, {})
        if abs_path:
            return filename, abs_path
    # Fallback
    ensure_media_dirs()
    _, ext = os.path.splitext(original_filename)
    ext = ext.lower() if ext else ".mp4"
    filename = generate_base_video_filename(ext)
    abs_path = get_base_video_path(filename)
    with open(abs_path, "wb") as f:
        f.write(video_data)
    return filename, abs_path


# =============================================================================
# CANVAS OVERLAY OPERATIONS
# =============================================================================

def save_canvas_overlay(
    overlay_rgba: Image.Image,
    project_id: str, audit_id: str, nr: str, overlay_type: str,
    index: Optional[int] = None
) -> Tuple[str, str]:
    """
    Save a canvas overlay (transparent PNG) to the global store.
    Returns (filename, absolute_path).
    """
    ensure_media_dirs()
    filename = generate_canvas_overlay_filename(project_id, audit_id, nr, overlay_type, index)
    abs_path = get_overlay_path(filename)
    if overlay_rgba.mode != "RGBA":
        overlay_rgba = overlay_rgba.convert("RGBA")
    overlay_rgba.save(abs_path, format="PNG")
    return filename, abs_path


def load_canvas_overlay(filename: str) -> Optional[Image.Image]:
    """Load a canvas overlay from the global store."""
    if not filename:
        return None
    abs_path = get_overlay_path(filename)
    if os.path.exists(abs_path):
        return Image.open(abs_path).convert("RGBA")
    return None


def create_empty_overlay(width: int, height: int) -> Image.Image:
    """Create a new transparent overlay matching the base image size."""
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def composite_base_with_overlay(base_path: str, overlay_path: Optional[str]) -> Optional[Image.Image]:
    """
    Composite a base image with its overlay in memory.
    Returns the composited image (RGB).
    Does NOT write any files to disk.
    """
    if not base_path or not os.path.exists(base_path):
        return None
    try:
        with Image.open(base_path) as base_img:
            base_rgba = base_img.convert("RGBA")
            if overlay_path and os.path.exists(overlay_path):
                with Image.open(overlay_path) as overlay_img:
                    overlay_rgba = overlay_img.convert("RGBA")
                    if overlay_rgba.size != base_rgba.size:
                        overlay_rgba = overlay_rgba.resize(base_rgba.size, Image.BILINEAR)
                    composited = Image.alpha_composite(base_rgba, overlay_rgba)
                    return composited.convert("RGB")
            return base_rgba.convert("RGB")
    except Exception:
        return None


# =============================================================================
# DELETE MEDIA
# =============================================================================

def delete_global_media(ref: str) -> bool:
    """Delete a media file from the global store."""
    if not ref:
        return False
    abs_path = resolve_media_path(ref, {})
    if abs_path and os.path.exists(abs_path):
        try:
            os.remove(abs_path)
            return True
        except Exception:
            pass
    return False


# =============================================================================
# SHARED MEDIA DETECTION
# =============================================================================

def is_media_shared(index: dict, media_ref: str, exclude_rec: Optional[dict] = None) -> bool:
    """
    Check if a media reference is used by multiple records in the index.
    In the new architecture, base images can be shared; overlays are unique per record.
    """
    if not media_ref:
        return False
    
    # Overlays are never shared
    if is_overlay_ref(media_ref):
        return False
    
    norm_ref = media_ref.replace("\\", "/")
    use_count = 0
    
    for rec in index.get("images", []):
        if exclude_rec is not None and rec is exclude_rec:
            continue
        
        media_fields = ["base_image", "after_base", "raw", "edited", "after_raw", "after_edited"]
        for field in media_fields:
            if rec.get(field) and rec.get(field).replace("\\", "/") == norm_ref:
                use_count += 1
                if use_count > 0 and exclude_rec is not None:
                    return True
                if use_count > 1:
                    return True
        
        for entry in rec.get("ctx_list", []) or []:
            for field in ["base", "raw", "edited"]:
                if entry.get(field) and entry.get(field).replace("\\", "/") == norm_ref:
                    use_count += 1
                    if use_count > 0 and exclude_rec is not None:
                        return True
                    if use_count > 1:
                        return True
        
        for entry in rec.get("add_fehler_list", []) or []:
            for field in ["base", "raw", "edited"]:
                if entry.get(field) and entry.get(field).replace("\\", "/") == norm_ref:
                    use_count += 1
                    if use_count > 0 and exclude_rec is not None:
                        return True
                    if use_count > 1:
                        return True
        
        for entry in rec.get("add_after_list", []) or []:
            for field in ["base", "raw", "edited"]:
                if entry.get(field) and entry.get(field).replace("\\", "/") == norm_ref:
                    use_count += 1
                    if use_count > 0 and exclude_rec is not None:
                        return True
                    if use_count > 1:
                        return True
        
        for vref in rec.get("videos", []) or []:
            if vref and vref.replace("\\", "/") == norm_ref:
                use_count += 1
                if use_count > 0 and exclude_rec is not None:
                    return True
                if use_count > 1:
                    return True
    
    return False


def safe_delete_global_media(index: dict, ref: str, current_rec: Optional[dict] = None) -> bool:
    """
    Safely delete a media file only if it's not shared with other records.
    Base images should generally NOT be deleted (they may be reused).
    Overlays can be deleted safely as they're unique per record.
    """
    if not ref:
        return False
    
    # Always safe to delete overlays
    if is_overlay_ref(ref):
        return delete_global_media(ref)
    
    # Don't delete base images if shared
    if is_media_shared(index, ref, exclude_rec=current_rec):
        return False
    
    return delete_global_media(ref)


# =============================================================================
# LEGACY COMPATIBILITY FUNCTIONS
# =============================================================================

def canonical_media_filename(
    project_id: str, audit_id: str, nr: str, media_type: str,
    index: Optional[int] = None, extension: str = ".jpg"
) -> str:
    """Legacy: Generate a canonical filename (kept for backward compatibility)."""
    p = sanitize_filename(project_id or "PROJ")
    a = sanitize_filename(audit_id or "AUDIT")
    n = sanitize_filename(nr or "000")
    t = sanitize_filename(media_type or "MEDIA")
    if index is not None:
        return f"{p}__{a}__{n}__{t}_{index}{extension}"
    return f"{p}__{a}__{n}__{t}{extension}"


def media_path_for_type(media_type: str) -> str:
    """Legacy: Get the appropriate global media subdirectory for a given media type."""
    ensure_media_dirs()
    if media_type == MEDIA_TYPE_VIDEO:
        return MEDIA_BASE_VIDEOS
    if media_type in (MEDIA_TYPE_EDITED, MEDIA_TYPE_AFTER_EDITED, 
                        MEDIA_TYPE_CTX_EDITED, MEDIA_TYPE_ADD_EDITED, 
                        MEDIA_TYPE_NADD_EDITED):
        return MEDIA_IMAGES_EDITED
    return MEDIA_BASE_IMAGES


def global_media_path(
    project_id: str, audit_id: str, nr: str, media_type: str,
    index: Optional[int] = None, extension: str = ".jpg"
) -> str:
    """Legacy: Generate the full absolute path for a media file."""
    directory = media_path_for_type(media_type)
    filename = canonical_media_filename(project_id, audit_id, nr, media_type, index, extension)
    return os.path.join(directory, filename)


def to_abs_path(p: Optional[str], paths: dict) -> Optional[str]:
    """Convert a storage reference to an absolute path (backward compatible)."""
    return resolve_media_path(p, paths)


def to_rel_path(p: Optional[str], paths: dict) -> Optional[str]:
    """Convert an absolute path to a storage reference."""
    if not p:
        return p
    if not os.path.isabs(p):
        return p
    try:
        rel_to_media = os.path.relpath(p, start=MEDIA_ROOT)
        if not rel_to_media.startswith(".."):
            return rel_to_media
    except Exception:
        pass
    try:
        rel = os.path.relpath(p, start=paths["root"])
        return rel if not rel.startswith("..") else p
    except Exception:
        return p


# =============================================================================
# BUILD REGISTRY FROM EXISTING FILES
# =============================================================================

def rebuild_media_registry() -> Tuple[int, int]:
    """
    Rebuild the media registry from existing files in base_images and base_videos.
    Useful for initial migration or if registry is corrupted.
    
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