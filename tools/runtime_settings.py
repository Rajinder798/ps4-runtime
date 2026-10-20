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
VOLUME_LEVELS = (0, 50, 100)
AV_TITLE = "interactive-av"
LIVE_TITLE = "live-av"
AUDIO_TITLES = (AV_TITLE, LIVE_TITLE)
CROSS_KEYS = ("n", "g")


def defaults(title=None):
    return dict(DEFAULTS, **({"volume_percent": 100} if title in (None, *AUDIO_TITLES) else {}),
                **({"cross_key": "n"} if title in (None, LIVE_TITLE) else {}))


def valid_value(key, value):
    return ((key == "log_level" and isinstance(value, str) and value in LOG_LEVELS) or
            (key == "volume_percent" and type(value) is int and value in VOLUME_LEVELS) or
            (key == "cross_key" and isinstance(value, str) and value in CROSS_KEYS))


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
            type(document["schema_version"]) is not int or document["schema_version"] not in (1, 2, 3, 4) or
            not isinstance(document["titles"], dict) or not set(document["titles"]) <= set(known_titles) or
            (document["schema_version"] < 3 and LIVE_TITLE in document["titles"])):
        raise ValueError("Unsupported settings schema or title")
    for title, scope in [(None, document["global"]), *document["titles"].items()]:
        allowed = dict(DEFAULTS) if document["schema_version"] == 1 else defaults(title)
        if document["schema_version"] < 4:
            allowed.pop("cross_key", None)
        if (not isinstance(scope, dict) or not set(scope) <= set(allowed) or
                any(not valid_value(key, value) for key, value in scope.items())):
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
    values = defaults(title)
    sources = {key: "default" for key in values}
    for name, scope in (("global", document["global"]), ("title", document["titles"].get(title, {}))):
        applicable = {key: value for key, value in scope.items() if key in values}
        values.update(applicable)
        sources.update({key: name for key in applicable})
    return values, sources


def inspect(home, known_titles, title=None):
    if title is not None and title not in known_titles:
        raise SettingsError("unsupported_title", "Preferences support only the reviewed homebrew IDs.")
    document = load(home, known_titles)
    return describe(document, title)


def describe(document, title=None):
    values, sources = effective(document, title)
    return dict(settings=document, defaults=defaults(title), effective_settings=values,
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


def update(home, known_titles, *, title=None, level=None, changes=None, reset=False, reset_all=False, reset_key=None):
    if title is not None and title not in known_titles:
        raise SettingsError("unsupported_title", "Preferences support only the reviewed homebrew IDs.")
    if level is not None:
        if changes is not None:
            raise SettingsError("invalid_settings", "Choose one preference update.")
        changes = {"log_level": level}
    allowed = defaults(title)
    if changes is not None and (not isinstance(changes, dict) or not changes or
            any(key not in allowed or (value is not None and not valid_value(key, value)) for key, value in changes.items())):
        raise SettingsError("invalid_settings", "Use supported log levels, audio volume 0/50/100, or live Cross letter N/G in an applicable scope.")
    if (reset_all and (title is not None or changes is not None or reset_key is not None)) or (reset and changes is not None) or (
            reset_key is not None and (not reset or reset_key not in allowed)) or (not reset and not reset_all and changes is None):
        raise SettingsError("invalid_settings", "Choose one preference update/reset scope.")
    try:
        with writer(home):
            document = load(home, known_titles)
            if reset_all:
                document["global"], document["titles"] = {}, {}
            else:
                scope = document["global"] if title is None else document["titles"].setdefault(title, {})
                if reset:
                    if reset_key is None:
                        scope.clear()
                    else:
                        scope.pop(reset_key, None)
                else:
                    for key, value in changes.items():
                        if value is None:
                            scope.pop(key, None)
                        else:
                            scope[key] = value
                            if key == "volume_percent":
                                document["schema_version"] = max(document["schema_version"], 2)
                            if title == LIVE_TITLE:
                                document["schema_version"] = max(document["schema_version"], 3)
                            if key == "cross_key":
                                document["schema_version"] = 4
                if title is not None and not scope:
                    document["titles"].pop(title, None)
            validate(document, known_titles)
            save(home, document)
            result = describe(document, title)
    except SettingsError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise SettingsError("settings_write_failed", "Could not save preferences; the previous published file was preserved.", 6) from error
    return result
