"""Pure logic for features/texture_relink. No bpy.types classes are defined here,
but collect_missing_images() and relink_missing_textures() directly use bpy.data.images
and bpy.path, so this module itself cannot be imported outside Blender runtime.
"""

import os
import re

import bpy

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tiff', '.tif', '.exr', '.hdr'}

_DUPLICATE_SUFFIX_RE = re.compile(r'\.\d{3}$')

LEVEL_EXACT = 1
LEVEL_NAME = 2
LEVEL_PARTIAL = 3


def collect_missing_images(images):
    """Collect images from the given iterable that are FILE-sourced, unpacked, and have missing source files.
    images: iterable of bpy.data.images or similar."""
    missing = []
    for image in images:
        if image.source != 'FILE':
            continue
        if image.packed_file is not None:
            continue
        if not image.filepath:
            continue
        if not os.path.exists(bpy.path.abspath(image.filepath)):
            missing.append(image)
    return missing


def find_candidate_files(directory):
    """Recursively search directory for image files and return list of file paths."""
    candidates = []
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS:
                candidates.append(os.path.join(root, filename))
    return candidates


def _strip_duplicate_suffix(name):
    """Remove Blender's duplicate suffix like '.001' from name."""
    return _DUPLICATE_SUFFIX_RE.sub('', name)


def match_level(image_name, candidate_path):
    """Determine match level between image_name (bpy.types.Image.name) and candidate_path.
    LEVEL_EXACT: filename+extension are exactly identical (case-sensitive).
    LEVEL_NAME: names match after ignoring extension, case, and Blender duplicate suffix (.001 etc).
    LEVEL_PARTIAL: normalized names have substring containment (either direction).
    Returns None if no match."""
    candidate_filename = os.path.basename(candidate_path)

    if image_name == candidate_filename:
        return LEVEL_EXACT

    # Blender appends serial number after extension on duplicate import (e.g. "TX_Body_A.png.001"),
    # so we need to strip this before extension splitting.
    normalized_image_name = _strip_duplicate_suffix(image_name)
    image_stem = os.path.splitext(normalized_image_name)[0].lower()
    candidate_stem = os.path.splitext(candidate_filename)[0].lower()

    if not image_stem:
        return None

    # LEVEL_NAME: exact name match (no version suffix normalization)
    if image_stem == candidate_stem:
        return LEVEL_NAME

    # LEVEL_PARTIAL: substring containment match (either direction)
    if image_stem in candidate_stem or candidate_stem in image_stem:
        return LEVEL_PARTIAL

    return None


def find_best_matches(image_name, candidates):
    """Find all candidates matching image_name at the best match level.
    Returns (level, [candidate_path, ...]). Returns (None, []) if no match found."""
    best_level = None
    best_matches = []
    for candidate_path in candidates:
        level = match_level(image_name, candidate_path)
        if level is None:
            continue
        if best_level is None or level < best_level:
            best_level = level
            best_matches = [candidate_path]
        elif level == best_level:
            best_matches.append(candidate_path)
    return best_level, best_matches


def relink_missing_textures(images, directory):
    """Search directory for missing texture files and relink them.
    directory must be an existing directory with absolute path (caller should pass bpy.path.abspath'd path).
    Raises ValueError if directory does not exist."""
    if not directory or not os.path.isdir(directory):
        raise ValueError(f"検索フォルダが見つかりません: {directory}")

    candidates = find_candidate_files(directory)

    relinked = []
    ambiguous = []
    not_found = []

    for image in collect_missing_images(images):
        level, matches = find_best_matches(image.name, candidates)
        if level is None:
            not_found.append(image)
        elif level == LEVEL_PARTIAL:
            ambiguous.append((image, matches))
        elif len(matches) == 1:
            new_path = matches[0]
            image.filepath = new_path
            image.reload()
            relinked.append((image, new_path))
        else:
            ambiguous.append((image, matches))

    return {'relinked': relinked, 'ambiguous': ambiguous, 'not_found': not_found}
