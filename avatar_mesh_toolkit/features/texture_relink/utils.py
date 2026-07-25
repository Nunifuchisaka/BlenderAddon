"""features/texture_relink 用の純ロジック。bpy.types クラスは定義しないが、
collect_missing_images() と relink_missing_textures() は bpy.data.images / bpy.path を
直接扱うため、このモジュール自体は Blender 実機以外では import できない。
"""

import os
import re

import bpy

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tiff', '.tif', '.exr', '.hdr'}

_DUPLICATE_SUFFIX_RE = re.compile(r'\.\d{3}$')
_VERSION_SUFFIX_RE = re.compile(r'_v\d+$', re.IGNORECASE)

LEVEL_EXACT = 1
LEVEL_NAME = 2
LEVEL_PARTIAL = 3


def collect_missing_images(images):
    """images: bpy.data.images 等の Image イテラブル。
    source == 'FILE' かつパッキングされておらず、実ファイルが存在しない画像を返す。"""
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
    """directory 配下を再帰的に探索し、画像拡張子のファイルパス一覧を返す。"""
    candidates = []
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS:
                candidates.append(os.path.join(root, filename))
    return candidates


def _strip_duplicate_suffix(name):
    """Blenderが重複時に付与する '.001' 等の末尾サフィックスを除去する。"""
    return _DUPLICATE_SUFFIX_RE.sub('', name)


def match_level(image_name, candidate_path):
    """image_name (bpy.types.Image.name) と candidate_path の一致レベルを判定する。
    LEVEL_EXACT: ファイル名+拡張子が完全一致(大文字小文字区別)。
    LEVEL_NAME: 拡張子違い/大文字小文字/Blenderの重複サフィックス/バージョン番号を無視して名前が一致。
    LEVEL_PARTIAL: 正規化した名前の一方がもう一方を含む(前方一致・含含一致)。
    一致しない場合は None。"""
    candidate_filename = os.path.basename(candidate_path)

    if image_name == candidate_filename:
        return LEVEL_EXACT

    # Blenderは重複インポート時 "TX_Body_A.png.001" のように元の拡張子の後ろに
    # 連番を付与するため、拡張子分離の前にこのサフィックスを剥がす必要がある。
    normalized_image_name = _strip_duplicate_suffix(image_name)
    image_stem = os.path.splitext(normalized_image_name)[0].lower()
    candidate_stem = os.path.splitext(candidate_filename)[0].lower()

    if not image_stem:
        return None

    # バージョン番号サフィックス (_v1, _v2等) も除去
    image_stem_normalized = _VERSION_SUFFIX_RE.sub('', image_stem)
    candidate_stem_normalized = _VERSION_SUFFIX_RE.sub('', candidate_stem)

    if image_stem_normalized == candidate_stem_normalized:
        return LEVEL_NAME

    if image_stem_normalized in candidate_stem_normalized or candidate_stem_normalized in image_stem_normalized:
        return LEVEL_PARTIAL

    return None


def find_best_matches(image_name, candidates):
    """candidates の中から image_name に対する最良レベルの一致を全て集めて返す。
    戻り値: (level, [candidate_path, ...])。一致が無ければ (None, [])。"""
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
    """images 内の欠落画像を directory 配下から検索して再リンクする。
    directory は絶対パスの既存ディレクトリであること(呼び出し側で bpy.path.abspath 済みを渡す)。"""
    if not directory or not os.path.isdir(directory):
        raise ValueError(f"検索フォルダが存在しません: {directory}")

    candidates = find_candidate_files(directory)

    relinked = []
    ambiguous = []
    not_found = []

    for image in collect_missing_images(images):
        level, matches = find_best_matches(image.name, candidates)
        if level is None:
            not_found.append(image)
        elif len(matches) == 1:
            new_path = matches[0]
            image.filepath = new_path
            image.reload()
            relinked.append((image, new_path))
        else:
            ambiguous.append((image, matches))

    return {'relinked': relinked, 'ambiguous': ambiguous, 'not_found': not_found}
