# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Persistent per-title save store, copied into and out of a fresh research session.

The engine only ever sees a session copy. `stage` copies one title's saves into a
fresh session; `commit` copies them back after the caller has verified a
qualifying end. Other titles are never staged, and a session holding anything but
the title's own save folders is refused. See docs/title-save-store.md.
"""
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

TITLE_ID = re.compile(r"[A-Z]{4}[0-9]{5}")
USER_IDS = ("1000", "1001", "1002", "1003")
MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 4096
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class StoreError(ValueError):
    pass


def _title(title):
    if not isinstance(title, str) or not TITLE_ID.fullmatch(title):
        raise StoreError("Title ID must be four capital letters and five digits")
    return title


def _is_link(path):
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)


def _inventory(root):
    """Count files and bytes under root without following links; links are refused."""
    files = size = 0
    pending = [Path(root)]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                path = Path(entry.path)
                if _is_link(path):
                    raise StoreError(f"Link or reparse point in save data: {path.name}")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files += 1
                    size += entry.stat(follow_symlinks=False).st_size
                else:
                    raise StoreError(f"Unsupported entry in save data: {path.name}")
                if files > MAX_FILES or size > MAX_BYTES:
                    raise StoreError("Save data exceeds the per-title size or file limit")
    return files, size


def _user_folders(root):
    """The store's per-user folders; anything else directly under a title is refused."""
    folders = {}
    for entry in sorted(Path(root).iterdir()):
        if _is_link(entry) or not entry.is_dir() or entry.name not in USER_IDS:
            raise StoreError(f"Unexpected entry in the title store: {entry.name}")
        folders[entry.name] = entry
    return folders


def stage(state, title, session):
    """Copy one title's stored saves into a fresh session before engine launch."""
    source = Path(state) / "titles" / _title(title)
    staged = {"title_id": title, "users": [], "files": 0, "bytes": 0}
    if not source.exists():
        return staged
    if _is_link(source):
        raise StoreError("The title store must not be a link")
    staged["files"], staged["bytes"] = _inventory(source)
    for user, folder in _user_folders(source).items():
        savedata = Path(session) / "user/home" / user / "savedata"
        if not savedata.is_dir() or _is_link(savedata):
            raise StoreError("Session has no prepared save home; call prepare_session first")
        target = savedata / title
        if target.exists():
            raise StoreError("Session already holds save data for this title; stage needs a fresh session")
        shutil.copytree(folder, target, symlinks=True)
        staged["users"].append(user)
    return staged


def commit(state, title, session):
    """Replace a title's stored saves with the session copy after a verified end.

    The previous store is left unchanged if the session holds anything except
    this title's save folders, or if building or swapping the new copy fails.
    """
    _title(title)
    found, files, size = {}, 0, 0
    for user in USER_IDS:
        savedata = Path(session) / "user/home" / user / "savedata"
        if not savedata.exists():
            continue
        if _is_link(savedata) or not savedata.is_dir():
            raise StoreError("Session save home must be a plain directory")
        for entry in savedata.iterdir():
            if entry.name != title or _is_link(entry) or not entry.is_dir():
                raise StoreError(f"Session holds save data outside title {title}: {entry.name}")
            count, total = _inventory(entry)
            files, size = files + count, size + total
            if files > MAX_FILES or size > MAX_BYTES:
                raise StoreError("Save data exceeds the per-title size or file limit")
            found[user] = entry
    titles = Path(state) / "titles"
    titles.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    fresh, target, previous = titles / f".{title}.new-{token}", titles / title, titles / f".{title}.old-{token}"
    try:
        fresh.mkdir()
        for user, folder in found.items():
            shutil.copytree(folder, fresh / user, symlinks=True)
        moved = False
        if target.exists():
            os.replace(target, previous)
            moved = True
        try:
            os.replace(fresh, target)
        except OSError:
            if moved:
                os.replace(previous, target)
            raise
    finally:
        if fresh.exists():
            shutil.rmtree(fresh)
    if previous.exists():
        shutil.rmtree(previous)
    return {"title_id": title, "users": sorted(found), "files": files, "bytes": size}
