"""Проверки групп форматов, миграции и видимости материалов."""

import configparser

import pytest

from src.course_reader.catalog import scan
from src.course_reader.storage import Store

EXPECTED_MASKS = {
    "pages": "*.html, *.htm, *.mhtml, *.mht",
    "video": "*.mp4, *.m4v, *.mpeg, *.mpg, *.avi, *.mkv, *.webm, *.mov",
    "other": "*.pdf, *.txt",
}


@pytest.fixture
def materials(tmp_path):
    root = tmp_path / "course"
    root.mkdir()
    for name in (
        "1.HTML",
        "2.htm",
        "3.mhtml",
        "4.mht",
        "5.MP4",
        "6.mkv",
        "7.pdf",
        "8.txt",
        "lesson-a.bin",
        "README",
        "extra.css",
    ):
        (root / name).write_text("material", encoding="utf-8")
    return root


def test_group_defaults_enable_only_pages_without_writing(tmp_path, materials):
    store = Store(tmp_path)
    for group, masks in EXPECTED_MASKS.items():
        section = store.settings["files." + group]
        assert section["patterns"] == masks
        assert section.getboolean("enabled") is (group == "pages")
    assert [path.name for path in scan(materials, store.patterns)] == [
        "1.HTML",
        "2.htm",
        "3.mhtml",
        "4.mht",
    ]
    assert set(tmp_path.iterdir()) == {materials}


def test_toggle_preserves_custom_masks_after_save_and_reopen(tmp_path, materials):
    store = Store(tmp_path)
    masks = "*.MP4,  lesson-?.bin, ,README"
    store.settings["files.video"].update(enabled="true", patterns=masks)
    expected = scan(materials, store.patterns)
    assert materials / "5.MP4" in expected
    assert materials / "lesson-a.bin" in expected
    store.settings["files.video"]["enabled"] = "false"
    store.save()
    restored = Store(tmp_path)
    assert restored.settings["files.video"]["patterns"] == masks
    assert materials / "5.MP4" not in scan(materials, restored.patterns)
    assert materials / "lesson-a.bin" not in scan(materials, restored.patterns)
    restored.settings["files.video"]["enabled"] = "true"
    restored.save()
    reopened = Store(tmp_path)
    assert reopened.settings["files.video"]["patterns"] == masks
    assert scan(materials, reopened.patterns) == expected


def test_all_groups_disabled_survive_reload_with_empty_catalog(tmp_path, materials):
    store = Store(tmp_path)
    for group in EXPECTED_MASKS:
        store.settings["files." + group]["enabled"] = "false"
    store.save()
    restored = Store(tmp_path)
    assert restored.patterns == []
    assert scan(materials, restored.patterns) == []
    for group, masks in EXPECTED_MASKS.items():
        assert restored.settings["files." + group]["patterns"] == masks


@pytest.mark.parametrize("masks", ["", " , ,  "])
def test_enabled_group_with_empty_masks_stays_empty(tmp_path, materials, masks):
    store = Store(tmp_path)
    store.settings["files.pages"]["patterns"] = masks
    store.save()
    restored = Store(tmp_path)
    assert restored.settings.getboolean("files.pages", "enabled")
    assert restored.settings["files.pages"]["patterns"] == masks.strip()
    assert restored.patterns == []
    assert scan(materials, restored.patterns) == []


def test_legacy_mixed_masks_preserve_visible_files_and_case(tmp_path, materials):
    """Given: старые смешанные маски. When: миграция. Then: видимость и регистр сохранены."""
    legacy = "*.MP4, *.HtMl, lesson-?.bin, README, *.PDF, *.HtMl"
    settings = tmp_path / "settings.ini"
    original = ("[app]\nvisible_patterns = " + legacy + "\n").encode("utf-8")
    settings.write_bytes(original)
    previous = scan(materials, [part.strip() for part in legacy.split(",")])
    store = Store(tmp_path)
    assert scan(materials, store.patterns) == previous
    assert store.settings["files.pages"]["patterns"] == "*.HtMl, *.HtMl"
    assert store.settings["files.video"]["patterns"] == "*.MP4"
    assert store.settings["files.other"]["patterns"] == "lesson-?.bin, README, *.PDF"
    assert all(
        store.settings.getboolean("files." + group, "enabled")
        for group in EXPECTED_MASKS
    )
    assert settings.read_bytes() == original
    assert not (tmp_path / "history.json").exists()


def test_legacy_video_only_does_not_enable_default_pages(tmp_path, materials):
    (tmp_path / "settings.ini").write_text(
        "[app]\nvisible_patterns = *.MP4\n", encoding="utf-8"
    )
    store = Store(tmp_path)
    assert store.patterns == ["*.MP4"]
    assert scan(materials, store.patterns) == [materials / "5.MP4"]
    assert not store.settings.getboolean("files.pages", "enabled")
    assert not store.settings.getboolean("files.other", "enabled")
    assert store.settings["files.pages"]["patterns"] == EXPECTED_MASKS["pages"]


@pytest.mark.parametrize("legacy", ["", " , , "])
def test_explicit_empty_legacy_list_disables_every_group(tmp_path, legacy):
    (tmp_path / "settings.ini").write_text(
        "[app]\nvisible_patterns = " + legacy + "\n", encoding="utf-8"
    )
    store = Store(tmp_path)
    assert store.patterns == []
    assert not any(
        store.settings.getboolean("files." + group, "enabled")
        for group in EXPECTED_MASKS
    )
    store.save()
    assert Store(tmp_path).patterns == []


def test_migration_saves_new_sections_and_removes_legacy_key(tmp_path):
    (tmp_path / "settings.ini").write_text(
        "[app]\nvisible_patterns = *.MP4, custom*.bin\n", encoding="utf-8"
    )
    store = Store(tmp_path)
    store.save()
    saved = configparser.ConfigParser(interpolation=None)
    saved.read(tmp_path / "settings.ini", encoding="utf-8")
    assert set(saved.sections()) == {
        "app",
        "files.pages",
        "files.video",
        "files.other",
        "remote_resources",
    }
    assert not saved.has_option("app", "visible_patterns")
    assert Store(tmp_path).patterns == ["*.MP4", "custom*.bin"]


def test_partial_new_sections_take_priority_over_legacy(tmp_path):
    (tmp_path / "settings.ini").write_text(
        "[app]\nvisible_patterns = legacy*.bin\n[files.video]\nenabled = true\n",
        encoding="utf-8",
    )
    store = Store(tmp_path)
    assert store.patterns == (
        EXPECTED_MASKS["pages"].split(", ") + EXPECTED_MASKS["video"].split(", ")
    )
    assert store.settings["files.other"]["patterns"] == EXPECTED_MASKS["other"]
    assert not store.settings.getboolean("files.other", "enabled")
    assert "legacy*.bin" not in store.patterns


def test_missing_enabled_keeps_explicit_empty_masks(tmp_path):
    (tmp_path / "settings.ini").write_text(
        "[files.pages]\npatterns =\n[files.other]\npatterns = custom*.bin\n",
        encoding="utf-8",
    )
    store = Store(tmp_path)
    assert store.settings.getboolean("files.pages", "enabled")
    assert not store.settings.getboolean("files.other", "enabled")
    assert store.settings["files.pages"]["patterns"] == ""
    assert store.settings["files.other"]["patterns"] == "custom*.bin"
    assert store.patterns == []


@pytest.mark.parametrize("group", ["pages", "video", "other"])
def test_invalid_group_boolean_rejected_without_overwriting(tmp_path, group):
    settings = tmp_path / "settings.ini"
    original = f"[files.{group}]\nenabled = perhaps\n".encode("utf-8")
    settings.write_bytes(original)
    with pytest.raises(ValueError, match=r"Некорректный settings\.ini:"):
        Store(tmp_path)
    assert settings.read_bytes() == original
    assert set(tmp_path.iterdir()) == {settings}


def test_new_group_initialization_does_not_rewrite_existing_file(tmp_path):
    settings = tmp_path / "settings.ini"
    original = b"[files.pages]\nenabled = no\npatterns = *.HTML\n"
    settings.write_bytes(original)
    assert Store(tmp_path).patterns == []
    assert settings.read_bytes() == original
    assert set(tmp_path.iterdir()) == {settings}
