"""Tests for the i18n module: catalog lookup, formatting, fallback."""

from __future__ import annotations

import pytest

from stocker import i18n


@pytest.fixture(autouse=True)
def _reset_lang():
    """Restore active language after each test."""
    saved = i18n.get_language()
    yield
    i18n.set_language(saved)


def test_set_language_ja_returns_japanese():
    i18n.set_language("ja")
    assert i18n.tr("dialog.error") == "エラー"
    assert i18n.tr("toolbar.workspace") == "ワークスペース..."


def test_set_language_en_returns_english():
    i18n.set_language("en")
    assert i18n.tr("dialog.error") == "Error"
    assert i18n.tr("toolbar.workspace") == "Workspace..."


def test_set_language_unknown_falls_back_to_default():
    i18n.set_language("zz")
    assert i18n.get_language() == i18n.DEFAULT_LANG


def test_tr_format_kwargs_expand():
    i18n.set_language("en")
    msg = i18n.tr("fm.invalid_name", name="bad/name")
    assert msg == "Invalid folder name: bad/name"
    i18n.set_language("ja")
    msg = i18n.tr("fm.invalid_name", name="bad/name")
    assert msg == "無効なフォルダ名です: bad/name"


def test_tr_unknown_key_returns_key_as_is():
    i18n.set_language("en")
    assert i18n.tr("nonexistent.key") == "nonexistent.key"
    assert i18n.tr("nonexistent.key", x=1) == "nonexistent.key"


def test_tr_falls_back_to_default_when_lang_missing():
    """If a translation entry lacks an active-lang key, fall back to DEFAULT_LANG."""
    i18n._CATALOG["test.partial"] = {"ja": "日本語のみ"}
    try:
        i18n.set_language("en")
        # No "en" entry; falls back to DEFAULT_LANG ("en") which is also missing,
        # so falls through to "ja" before returning the key.
        assert i18n.tr("test.partial") == "日本語のみ"
    finally:
        del i18n._CATALOG["test.partial"]


def test_detect_language_returns_ja_or_en():
    """Detection must produce a valid LangCode regardless of host OS."""
    lang = i18n.detect_language()
    assert lang in ("ja", "en")


def test_status_queue_formatting():
    i18n.set_language("en")
    assert i18n.tr("status.queue", n=5) == "Queued: 5"
    assert i18n.tr("status.queue_warning", n=250) == "Queued: 250 ⚠"
    i18n.set_language("ja")
    assert i18n.tr("status.queue", n=5) == "保存待ち: 5"
