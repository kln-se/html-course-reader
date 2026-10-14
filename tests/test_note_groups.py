"""Проверки сворачивания групп заметок без запуска графического интерфейса."""

from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from test_course_notes import reader as _reader_fixture

from src.course_reader.note_presentation import NOTE_GROUP_ROLE
from src.course_reader.window import Window

reader = _reader_fixture


@pytest.fixture
def grouped_reader(reader):
    """Подготовить две страницы курса с тремя заметками."""
    groups = reader.store.course(reader.root)["notes"]
    for relative, entries in {
        "1.html": [("first", "Найти важную мысль"), ("second", "Дополнительная мысль")],
        "2.html": [("third", "Другая страница")],
    }.items():
        groups[relative] = [
            {
                "id": identifier,
                "text": text,
                "created": "2026-10-04T09:00:00+00:00",
                "updated": "2026-10-04T09:00:00+00:00",
            }
            for identifier, text in entries
        ]
    reader.refresh_notes()
    return reader


def test_toggle_hides_only_own_rows_without_changing_course(grouped_reader):
    """Given: две группы. When: одну переключают. Then: данные и другая группа сохранены."""
    reader = grouped_reader
    heading, own_rows = reader.note_groups["1.html"]
    other_rows = reader.note_groups["2.html"][1]
    original_course = deepcopy(reader.store.course(reader.root))
    original_page = reader.current
    theme = reader.store.settings["app"]["theme"]
    assert heading.icon == ("chevron_down", theme)

    reader.toggle_note_group(heading)

    assert reader.collapsed_note_groups == {"1.html"}
    assert heading.icon == ("next", theme)
    assert all(item.isHidden() for item in own_rows)
    assert all(not item.isHidden() for item in other_rows)
    reader.notes_action.setText.assert_called_with("Заметки (3)")

    reader.toggle_note_group(heading)

    assert reader.collapsed_note_groups == set()
    assert heading.icon == ("chevron_down", theme)
    assert all(not item.isHidden() for item in own_rows)
    assert reader.store.course(reader.root) == original_course
    assert reader.current == original_page
    reader.persist.assert_not_called()
    reader.page.open_saved.assert_not_called()


@pytest.mark.parametrize("selected_page", ["1.html", "2.html"])
def test_collapse_clears_only_selection_inside_its_group(grouped_reader, selected_page):
    """Given: выбрана заметка. When: группу скрывают. Then: сбрасывается только скрытый выбор."""
    reader = grouped_reader
    selected = reader.note_groups[selected_page][1][0]
    reader.notes_list.setCurrentItem(selected)
    reader.update_note_actions()

    reader.toggle_note_group(reader.note_groups["1.html"][0])

    retained = selected_page == "2.html"
    assert reader.notes_list.currentItem() is (selected if retained else None)
    for label in ("Открыть страницу", "Изменить", "Удалить"):
        reader.note_buttons[label].setEnabled.assert_called_with(retained)
    reader.note_buttons["Добавить"].setEnabled.assert_called_with(True)


def test_collapsed_state_survives_refresh_and_page_change(grouped_reader):
    reader = grouped_reader
    reader.toggle_note_group(reader.note_groups["1.html"][0])
    reader.current = reader.root / "2.html"

    reader.refresh_notes()

    assert reader.collapsed_note_groups == {"1.html"}
    assert all(item.isHidden() for item in reader.note_groups["1.html"][1])
    assert all(not item.isHidden() for item in reader.note_groups["2.html"][1])


def test_search_opens_results_then_restores_collapsed_groups(grouped_reader):
    """Given: группы свёрнуты. When: поиск затем очищают. Then: сворачивание восстанавливается."""
    reader = grouped_reader
    for relative in ("1.html", "2.html"):
        reader.toggle_note_group(reader.note_groups[relative][0])
    reader.notes_search.text.return_value = "найти"
    reader.refresh_notes()

    assert set(reader.note_groups) == {"1.html"}
    heading, rows = reader.note_groups["1.html"]
    assert heading.icon == ("chevron_down", reader.store.settings["app"]["theme"])
    assert len(rows) == 1
    assert rows[0].data(Qt.ItemDataRole.UserRole)[2] == "first"
    assert not rows[0].isHidden()
    assert reader.collapsed_note_groups == {"1.html", "2.html"}
    reader.notes_action.setText.assert_called_with("Заметки (3)")

    reader.toggle_note_group(heading)

    assert not rows[0].isHidden()
    assert reader.collapsed_note_groups == {"1.html", "2.html"}
    reader.notes_search.text.return_value = ""
    reader.notes_list.setCurrentItem(rows[0])
    reader.update_note_actions()
    reader.note_buttons["Изменить"].setEnabled.assert_called_with(True)
    reader.refresh_notes()
    assert set(reader.note_groups) == {"1.html", "2.html"}
    assert all(
        item.isHidden() for _, rows in reader.note_groups.values() for item in rows
    )
    assert reader.notes_list.currentItem() is None
    assert reader.selected_note() is None
    for label in ("Открыть страницу", "Изменить", "Удалить"):
        reader.note_buttons[label].setEnabled.assert_called_with(False)


def test_adding_note_expands_only_target_page(grouped_reader):
    reader = grouped_reader
    for relative in ("1.html", "2.html"):
        reader.toggle_note_group(reader.note_groups[relative][0])
    reader.dialog.return_value = ("Новая заметка", True)

    Window.add_note(reader)

    assert reader.collapsed_note_groups == {"2.html"}
    own_rows = reader.note_groups["1.html"][1]
    assert len(own_rows) == 3
    assert all(not item.isHidden() for item in own_rows)
    assert all(item.isHidden() for item in reader.note_groups["2.html"][1])
    assert (
        reader.store.course(reader.root)["notes"]["1.html"][-1]["text"]
        == "Новая заметка"
    )
    reader.dialog.assert_called_once_with("1.html")
    reader.persist.assert_called_once_with()
    reader.notes_action.setText.assert_called_with("Заметки (4)")


@pytest.mark.parametrize(
    "text,accepted", [("Отменённая заметка", False), ("", True), (" \n\t ", True)]
)
def test_cancelled_or_empty_note_preserves_collapsed_state(
    grouped_reader, text, accepted
):
    reader = grouped_reader
    reader.toggle_note_group(reader.note_groups["1.html"][0])
    original_course = deepcopy(reader.store.course(reader.root))
    reader.dialog.return_value = (text, accepted)

    Window.add_note(reader)

    assert reader.collapsed_note_groups == {"1.html"}
    assert all(item.isHidden() for item in reader.note_groups["1.html"][1])
    assert reader.store.course(reader.root) == original_course
    reader.persist.assert_not_called()


@pytest.mark.parametrize("target_kind", ["note", "foreign", "stale", "missing"])
def test_toggle_ignores_noncurrent_group_targets(grouped_reader, target_kind):
    reader = grouped_reader
    heading, rows = reader.note_groups["1.html"]
    if target_kind == "note":
        target = rows[0]
    else:
        target = type(heading)("Заголовок")
        course = str(reader.root)
        relative = "1.html"
        if target_kind == "foreign":
            course = str(reader.root.parent / "another-course")
        elif target_kind == "missing":
            relative = "missing.html"
        target.setData(NOTE_GROUP_ROLE, (course, relative))
    original_course = deepcopy(reader.store.course(reader.root))

    reader.toggle_note_group(target)

    assert reader.collapsed_note_groups == set()
    assert all(
        not item.isHidden() for _, rows in reader.note_groups.values() for item in rows
    )
    assert reader.store.course(reader.root) == original_course
    reader.persist.assert_not_called()
    reader.page.open_saved.assert_not_called()
