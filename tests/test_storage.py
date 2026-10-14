"""Проверки переносимых настроек, истории, избранного и заметок."""

import json
from datetime import datetime

import pytest

from src.course_reader.storage import Store


def test_defaults_and_read_only_initialization(tmp_path):
    store = Store(tmp_path)
    assert store.patterns == ["*.html", "*.htm", "*.mhtml", "*.mht"]
    assert store.settings.getboolean("app", "internet_links") is False
    assert store.settings["app"]["theme"] == "dark"
    assert store.data == {"courses": {}}
    assert list(tmp_path.iterdir()) == []


def test_manual_ini_settings_are_loaded_on_start(tmp_path):
    (tmp_path / "settings.ini").write_text(
        "[app]\nvisible_patterns = *.html, , *.MP4, *.txt,\n"
        "internet_links = true\ntheme = light\nzoom = 1.25\n",
        encoding="utf-8",
    )
    store = Store(tmp_path)
    assert store.patterns == ["*.html", "*.MP4", "*.txt"]
    assert store.settings.getboolean("app", "internet_links") is True
    assert store.settings["app"]["theme"] == "light"
    assert store.settings.getfloat("app", "zoom") == 1.25


def test_history_and_settings_survive_reopening(tmp_path):
    store = Store(tmp_path)
    root = tmp_path / "Курс"
    relative = "01-глава/02-страница.html"
    course = store.course(root)
    course["last"] = relative
    course["scroll"][relative] = 425
    store.toggle_favorite(root, relative)
    note = store.add_note(root, relative, "Важное объяснение\nВторая строка")
    store.settings["app"]["theme"] = "light"
    store.settings["app"]["zoom"] = "1.5"
    store.save()
    restored = Store(tmp_path)
    assert restored.course(root) == {
        "last": relative,
        "scroll": {relative: 425},
        "favorites": [relative],
        "notes": {relative: [note]},
    }
    assert restored.settings["app"]["theme"] == "light"
    assert restored.settings.getfloat("app", "zoom") == 1.5
    assert not list(tmp_path.glob("*.tmp"))


def test_favorites_toggle_and_are_isolated_per_course(tmp_path):
    store = Store(tmp_path)
    first, second = tmp_path / "A", tmp_path / "B"
    assert store.toggle_favorite(first, "1.html") is True
    assert store.toggle_favorite(second, "1.html") is True
    assert store.toggle_favorite(first, "1.html") is False
    assert store.course(first)["favorites"] == []
    assert store.course(second)["favorites"] == ["1.html"]


def test_notes_are_independent_per_page_and_course(tmp_path):
    store = Store(tmp_path)
    root = tmp_path / "course"
    root.mkdir()
    page = root / "1.html"
    page.write_bytes(b"<html>original</html>")
    first = store.add_note(root, "1.html", "Первая")
    second = store.add_note(root, "1.html", "Вторая")
    other_page = store.add_note(root, "2.html", "Другая страница")
    other_course = store.add_note(tmp_path / "other", "1.html", "Другой курс")
    assert store.course(root)["notes"] == {
        "1.html": [first, second],
        "2.html": [other_page],
    }
    assert store.course(tmp_path / "other")["notes"] == {"1.html": [other_course]}
    assert len({n["id"] for n in [first, second, other_page, other_course]}) == 4
    for note in [first, second, other_page, other_course]:
        assert note["created"] == note["updated"]
        assert datetime.fromisoformat(note["created"]).tzinfo is not None
    store.save()
    assert page.read_bytes() == b"<html>original</html>"


def test_relocate_preserves_relative_page_data_after_reload(tmp_path):
    store = Store(tmp_path)
    old, new = tmp_path / "old", tmp_path / "new"
    store.course(old)["last"] = "chapter/1.html"
    store.course(old)["scroll"]["chapter/1.html"] = 42
    store.toggle_favorite(old, "chapter/1.html")
    store.add_note(old, "chapter/1.html", "Сохранить")
    expected = json.loads(json.dumps(store.course(old)))
    store.relocate(str(old.resolve()), new)
    store.save()
    assert Store(tmp_path).data["courses"] == {str(new.resolve()): expected}


def test_relocate_to_existing_course_fails_without_data_loss(tmp_path):
    store = Store(tmp_path)
    old, new = tmp_path / "old", tmp_path / "new"
    store.course(old)["last"] = "1.html"
    store.course(new)["last"] = "2.html"
    expected = json.loads(json.dumps(store.data))
    with pytest.raises(ValueError):
        store.relocate(str(old.resolve()), new)
    assert store.data == expected


def test_relocate_to_same_root_keeps_history(tmp_path):
    store = Store(tmp_path)
    root = tmp_path / "course"
    store.course(root)["last"] = "1.html"
    store.relocate(str(root.resolve()), root)
    assert store.course(root)["last"] == "1.html"


@pytest.mark.parametrize("content", ["{broken", "[]", "{}", '{"courses": []}'])
def test_invalid_history_is_reported_without_overwriting(tmp_path, content):
    history = tmp_path / "history.json"
    history.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        Store(tmp_path)
    assert history.read_text(encoding="utf-8") == content


def test_failed_history_replace_preserves_previous_history(tmp_path, monkeypatch):
    """Given: сохранённая история. When: отказ диска при замене. Then: история цела."""
    import os

    store = Store(tmp_path)
    store.course(tmp_path / "course")["last"] = "1.html"
    store.save()
    history = tmp_path / "history.json"
    original = history.read_bytes()
    real_replace = os.replace

    def fail_history_replace(source, destination):
        if destination == history:
            raise OSError("simulated disk error")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_history_replace)
    store.course(tmp_path / "course")["last"] = "2.html"
    with pytest.raises(OSError, match="simulated disk error"):
        store.save()
    assert history.read_bytes() == original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("internet_links", "maybe"),
        ("theme", "unknown"),
        ("zoom", "large"),
        ("zoom", "nan"),
        ("zoom", "inf"),
        ("zoom", "-inf"),
        ("zoom", "0.249"),
        ("zoom", "3.001"),
    ],
)
def test_invalid_ini_value_is_reported_without_overwriting(tmp_path, field, value):
    settings = tmp_path / "settings.ini"
    original = f"[app]\n{field} = {value}\n".encode("utf-8")
    settings.write_bytes(original)
    with pytest.raises(ValueError, match=r"Некорректный settings\.ini: .+"):
        Store(tmp_path)
    assert settings.read_bytes() == original


@pytest.mark.parametrize("zoom", ["0.25", "3.0"])
def test_ini_accepts_zoom_boundaries(tmp_path, zoom):
    (tmp_path / "settings.ini").write_text(f"[app]\nzoom = {zoom}\n", encoding="utf-8")
    assert Store(tmp_path).settings.getfloat("app", "zoom") == float(zoom)


@pytest.mark.parametrize(
    "course",
    [
        None,
        {},
        {"last": "", "scroll": {}, "favorites": None, "notes": {}},
        {"last": "", "scroll": [], "favorites": [], "notes": {}},
        {"last": "", "scroll": {}, "favorites": [], "notes": []},
        {"last": 12, "scroll": {}, "favorites": [], "notes": {}},
    ],
)
def test_malformed_course_fields_are_reported_without_overwriting(tmp_path, course):
    history = tmp_path / "history.json"
    original = json.dumps({"courses": {str(tmp_path / "course"): course}}).encode()
    history.write_bytes(original)
    with pytest.raises(ValueError, match=r"history\.json"):
        Store(tmp_path)
    assert history.read_bytes() == original


@pytest.mark.parametrize("scroll", [-1, "20", None, True, float("nan"), float("inf")])
def test_invalid_scroll_is_reported_without_overwriting(tmp_path, scroll):
    history = tmp_path / "history.json"
    data = {
        "courses": {
            "course": {
                "last": "",
                "scroll": {"1.html": scroll},
                "favorites": [],
                "notes": {},
            }
        }
    }
    original = json.dumps(data).encode()
    history.write_bytes(original)
    with pytest.raises(ValueError, match=r"прокрутка.*history\.json"):
        Store(tmp_path)
    assert history.read_bytes() == original


@pytest.mark.parametrize("field", ["last", "favorites", "scroll", "notes"])
@pytest.mark.parametrize(
    "path", ["../outside.html", "chapter/../../outside.html", "C:/outside.html"]
)
def test_unsafe_relative_paths_are_rejected_in_every_history_field(
    tmp_path, field, path
):
    course = {"last": "", "scroll": {}, "favorites": [], "notes": {}}
    course[field] = {
        "last": path,
        "favorites": [path],
        "scroll": {path: 0},
        "notes": {path: []},
    }[field]
    history = tmp_path / "history.json"
    original = json.dumps({"courses": {"course": course}}).encode()
    history.write_bytes(original)
    with pytest.raises(ValueError, match=r"относительный путь.*history\.json"):
        Store(tmp_path)
    assert history.read_bytes() == original


@pytest.mark.parametrize(
    "notes",
    [
        None,
        {},
        [None],
        [{}],
        [{"id": "a", "text": 42, "created": "2026-01-01", "updated": "2026-01-01"}],
        [{"id": "", "text": "note", "created": "2026-01-01", "updated": "2026-01-01"}],
        [
            {
                "id": "a",
                "text": "first",
                "created": "2026-01-01",
                "updated": "2026-01-01",
            },
            {
                "id": "a",
                "text": "second",
                "created": "2026-01-01",
                "updated": "2026-01-01",
            },
        ],
    ],
)
def test_malformed_notes_and_duplicate_ids_are_reported_without_overwriting(
    tmp_path, notes
):
    course = {"last": "", "scroll": {}, "favorites": [], "notes": {"1.html": notes}}
    history = tmp_path / "history.json"
    original = json.dumps({"courses": {"course": course}}).encode()
    history.write_bytes(original)
    with pytest.raises(ValueError, match=r"history\.json"):
        Store(tmp_path)
    assert history.read_bytes() == original


def test_edit_and_delete_notes_by_id_preserve_other_notes_after_reload(tmp_path):
    """Given: одинаковый текст заметок. When: изменение по ID. Then: меняется только выбранная."""
    store = Store(tmp_path)
    root, other_root = tmp_path / "course", tmp_path / "other"
    first = store.add_note(root, "1.html", "Одинаковый текст")
    second = store.add_note(root, "1.html", "Одинаковый текст")
    store.add_note(root, "2.html", "Одинаковый текст")
    store.add_note(other_root, "1.html", "Одинаковый текст")
    second["created"] = second["updated"] = "2000-01-01T00:00:00+00:00"
    before = json.loads(json.dumps(store.data))
    store.edit_note(root, "1.html", second["id"], "Обновлено\nС деталями")
    assert first == before["courses"][str(root.resolve())]["notes"]["1.html"][0]
    assert second["created"] == "2000-01-01T00:00:00+00:00"
    assert second["updated"] != second["created"]
    assert datetime.fromisoformat(second["updated"]).tzinfo is not None
    store.save()
    restored = Store(tmp_path)
    expected_second = dict(second)
    assert expected_second["text"] == "Обновлено\nС деталями"
    assert restored.course(root)["notes"]["1.html"] == [first, expected_second]
    restored.delete_note(root, "1.html", first["id"])
    restored.save()
    after_delete = Store(tmp_path)
    assert after_delete.course(root)["notes"]["1.html"] == [expected_second]
    assert (
        after_delete.course(root)["notes"]["2.html"]
        == before["courses"][str(root.resolve())]["notes"]["2.html"]
    )
    assert (
        after_delete.course(other_root) == before["courses"][str(other_root.resolve())]
    )
    after_delete.delete_note(root, "1.html", second["id"])
    after_delete.save()
    assert Store(tmp_path).course(root)["notes"].get("1.html", []) == []


@pytest.mark.parametrize("operation", ["edit", "delete"])
@pytest.mark.parametrize("target", ["unknown-id", "other-page", "other-course"])
def test_unknown_note_id_or_wrong_scope_does_not_change_data(
    tmp_path, operation, target
):
    store = Store(tmp_path)
    root, other_root = tmp_path / "course", tmp_path / "other"
    note = store.add_note(root, "1.html", "Исходный текст")
    store.add_note(root, "2.html", "Другая страница")
    store.add_note(other_root, "1.html", "Другой курс")
    before = json.loads(json.dumps(store.data))
    selected_root = other_root if target == "other-course" else root
    selected_page = "2.html" if target == "other-page" else "1.html"
    identifier = "missing-id" if target == "unknown-id" else note["id"]
    with pytest.raises(KeyError) as error:
        if operation == "edit":
            store.edit_note(selected_root, selected_page, identifier, "Нельзя заменить")
        else:
            store.delete_note(selected_root, selected_page, identifier)
    assert error.value.args == (identifier,)
    assert store.data == before


@pytest.mark.parametrize("text", ["", " ", "\n\t"])
@pytest.mark.parametrize("operation", ["add", "edit"])
def test_empty_note_text_is_rejected_without_data_changes(tmp_path, text, operation):
    store = Store(tmp_path)
    root = tmp_path / "course"
    note = store.add_note(root, "1.html", "Исходный текст")
    before = json.loads(json.dumps(store.data))
    with pytest.raises(ValueError, match="Заметка не может быть пустой"):
        if operation == "add":
            store.add_note(root, "1.html", text)
        else:
            store.edit_note(root, "1.html", note["id"], text)
    assert store.data == before
