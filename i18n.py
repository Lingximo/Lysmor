"""Shared, dependency-free translations for command-line and browser interfaces."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
LOCALES = ("zh-CN", "zh-TW", "en")
DEFAULT_LOCALE = "zh-CN"
_locale = ContextVar("lysmor_locale", default=None)
_VARIABLE = re.compile(r"\{(\w+)\}")


def normalize_locale(value):
    value = str(value or "").replace("_", "-").lower()
    if re.match(r"^zh-(tw|hk|mo|hant)(-|$)", value):
        return "zh-TW"
    if value == "zh" or value.startswith("zh-"):
        return "zh-CN"
    if value == "en" or value.startswith("en-"):
        return "en"
    return None


def language_from_header(value):
    """Select a supported language from an Accept-Language header."""
    candidates = []
    for position, entry in enumerate(str(value or "").split(",")):
        parts = entry.strip().split(";")
        language = normalize_locale(parts[0])
        quality = 1.0
        for parameter in parts[1:]:
            name, separator, raw = parameter.strip().partition("=")
            if name.lower() == "q" and separator:
                try:
                    quality = float(raw)
                except ValueError:
                    quality = 0
        if language and 0 < quality <= 1:
            candidates.append((quality, -position, language))
    return max(candidates)[2] if candidates else None


def language(locale=None):
    for candidate in (locale, _locale.get(), os.environ.get("LYSMOR_LANGUAGE")):
        normalized = normalize_locale(candidate)
        if normalized:
            return normalized
    try:
        with (ROOT / "config.json").open(encoding="utf-8-sig") as stream:
            normalized = normalize_locale(json.load(stream).get("language"))
        if normalized:
            return normalized
    except (OSError, ValueError, AttributeError):
        pass
    return DEFAULT_LOCALE


@contextmanager
def locale_context(locale):
    token = _locale.set(normalize_locale(locale))
    try:
        yield
    finally:
        _locale.reset(token)


def load_catalog(locale):
    normalized = normalize_locale(locale) or DEFAULT_LOCALE
    directory = ROOT / "locales"
    paths = [directory / (normalized + ".json")]
    paths.extend(sorted(directory.glob("*." + normalized + ".json")))
    snapshot = []
    for path in paths:
        if not path.exists():
            continue
        metadata = path.stat()
        snapshot.append((str(path), metadata.st_mtime_ns, metadata.st_size))
    return dict(_read_catalog(tuple(snapshot)))


@lru_cache(maxsize=32)
def _read_catalog(snapshot):
    catalog = {}
    for filename, _, _ in snapshot:
        path = Path(filename)
        with path.open(encoding="utf-8-sig") as stream:
            fragment = json.load(stream)
        if not isinstance(fragment, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                 for k, v in fragment.items()):
            raise ValueError("Translation catalogs must contain string keys and values")
        for key, value in fragment.items():
            if key in catalog and catalog[key] != value:
                raise ValueError("Conflicting translation key: " + key)
            catalog[key] = value
    return catalog


def t(key, locale=None, **variables):
    selected = language(locale)
    catalog = load_catalog(selected)
    value = catalog.get(key)
    if value is None and selected != DEFAULT_LOCALE:
        value = load_catalog(DEFAULT_LOCALE).get(key)
    if value is None:
        value = key
    return _VARIABLE.sub(lambda match: str(variables[match[1]]) if match[1] in variables else match[0], value)


def build_browser_asset():
    """Embed current catalogs so browser translation never races a catalog fetch."""
    source = (ROOT / "i18n.js").read_text(encoding="utf-8")
    catalogs = {locale: load_catalog(locale) for locale in LOCALES}
    serialized = json.dumps(catalogs, ensure_ascii=False, separators=(",", ":"))
    start, end = "/* catalogs:start */", "/* catalogs:end */"
    before, separator, remainder = source.partition(start)
    if not separator or end not in remainder:
        raise ValueError("Browser translation catalog markers are missing")
    _, _, after = remainder.partition(end)
    source = before + start + " " + serialized + " " + end + after
    start, end = "/* language:start */", "/* language:end */"
    before, separator, remainder = source.partition(start)
    if not separator or end not in remainder:
        raise ValueError("Browser translation language markers are missing")
    _, _, after = remainder.partition(end)
    return (before + start + " " + json.dumps(language()) + " " + end + after).encode("utf-8")


def browser_asset(path):
    """Resolve only the public translation assets; unrelated paths return None."""
    if path == "/i18n.js":
        return build_browser_asset(), "application/javascript; charset=utf-8"
    for locale in LOCALES:
        if path == "/locales/" + locale + ".json":
            return json.dumps(load_catalog(locale), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
    return None


def send_browser_asset(handler, path):
    asset = browser_asset(path)
    if asset is None:
        return False
    body, mime = asset
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build browser translations from locale catalogs")
    parser.add_argument("--build-js", action="store_true")
    args = parser.parse_args()
    if args.build_js:
        asset = build_browser_asset()
        (ROOT / "i18n.js").write_bytes(asset)
