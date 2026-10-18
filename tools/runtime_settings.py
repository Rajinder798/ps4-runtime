# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Validated preferences for implemented runtime capabilities only."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

FILE_NAME = "settings.json"
MAX_BYTES = 65536
LOG_LEVELS = ("debug", "info", "warning")
DEFAULTS = {"log_level": "info"}


class SettingsError(ValueError):
    def __init__(self, code, message, exit_code=3):
        super().__init__(message)
        self.code, self.exit_code = code, exit_code


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate preference key")
        result[key] = value
    return result


def validate(document, known_titles):
    if (not isinstance(document, dict) or set(document) != {"schema_version", "global", "titles"} or
            type(document["schema_version"]) is not int or document["schema_version"] != 1 or
            not isinstance(document["titles"], dict) or not set(document["titles"]) <= set(known_titles)):
        raise ValueError("Unsupported settings schema or title")
    for scope in [document["global"], *document["titles"].values()]:
        if (not isinstance(scope, dict) or not set(scope) <= set(DEFAULTS) or
                any(not isinstance(value, str) or value not in LOG_LEVELS for value in scope.values())):
            raise ValueError("Unsupported preference or value")


def load(home, known_titles):
    path = home / FILE_NAME
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("Settings exceed size limit")
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        validate(document, known_titles)
        return document
    except FileNotFoundError:
        return dict(schema_version=1, **{"global": {}, "titles": {}})
    except (OSError, ValueError, TypeError) as error:
        raise SettingsError("invalid_settings", "Preferences are invalid or use an unsupported version; the saved file was not changed.") from error


def effective(document, title=None):
    values, sources = dict(DEFAULTS), {key: "default" for key in DEFAULTS}
    for name, scope in (("global", document["global"]), ("title", document["titles"].get(title, {}))):
        values.update(scope)
        sources.update({key: name for key in scope})
    return values, sources


def inspect(home, known_titles, title=None):
    if title is not None and title not in known_titles:
        raise SettingsError("unsupported_title", "Preferences support only the reviewed homebrew IDs.")
    document = load(home, known_titles)
    return describe(document, title)


def describe(document, title=None):
    values, sources = effective(document, title)
    return dict(settings=document, defaults=dict(DEFAULTS), effective_settings=values,
                settings_sources=sources, takes_effect="next_launch")


@contextmanager
def writer(home):
    home.mkdir(parents=True, exist_ok=True)
    # OS locks release when the handle closes, including process termination.
    # The small persistent lock file is not a stale ownership marker.
    with (home / ".settings.lock").open("a+b") as lock:
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SettingsError("settings_busy", "Another process is updating preferences; retry after it completes.") from error
        yield


def save(home, document):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=home, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, home / FILE_NAME)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def update(home, known_titles, *, title=None, level=None, reset=False, reset_all=False):
    if title is not None and title not in known_titles:
        raise SettingsError("unsupported_title", "Preferences support only the reviewed homebrew IDs.")
    if level is not None and (not isinstance(level, str) or level not in LOG_LEVELS):
        raise SettingsError("invalid_settings", "Log level must be debug, info or warning.")
    if (reset_all and (title is not None or level is not None)) or (reset and level is not None):
        raise SettingsError("invalid_settings", "Choose one preference update/reset scope.")
    try:
        with writer(home):
            document = load(home, known_titles)
            if reset_all:
                document = dict(schema_version=1, **{"global": {}, "titles": {}})
            elif title is None:
                document["global"] = {} if reset else {"log_level": level}
            elif reset:
                document["titles"].pop(title, None)
            else:
                document["titles"][title] = {"log_level": level}
            validate(document, known_titles)
            save(home, document)
            result = describe(document, title)
    except SettingsError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise SettingsError("settings_write_failed", "Could not save preferences; the previous published file was preserved.", 6) from error
    return result
