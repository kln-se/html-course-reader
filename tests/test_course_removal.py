"""Проверки удаления курса из истории без изменения учебных материалов."""

from copy import deepcopy
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtWidgets import QMessageBox

from src.course_reader.storage import Store
from src.course_reader.window import Window


@pytest.fixture
def courses(tmp_path):
    store = Store(tmp_path)
    roots = [tmp_path / "Первый", tmp_path / "Второй"]
    for root in roots:
        root.mkdir()
        (root / "1.html").write_bytes(b"<html>original</html>")
        store.course(root)["last"] = "1.html"
        store.course(root)["scroll"]["1.html"] = 425
        store.toggle_favorite(root, "1.html")
        store.add_note(root, "1.html", "Важная заметка")
    store.activate_course(roots[0])
    store.save()
    return store, roots


@pytest.mark.parametrize("index", [0, 1])
def test_store_removes_only_selected_data_and_readd_starts_fresh(
    courses, tmp_path, index
):
    store, roots = courses
    selected, other = roots[index], roots[1 - index]
    other_data = deepcopy(store.course(other))
    persisted = (tmp_path / "history.json").read_bytes()
    assert store.remove_course(str(selected.resolve())) is True
    assert (tmp_path / "history.json").read_bytes() == persisted
    store.save()
    restored = Store(tmp_path)
    assert restored.data["courses"] == {str(other.resolve()): other_data}
    assert restored.active_course == (None if index == 0 else roots[0].resolve())
    for root in roots:
        assert (root / "1.html").read_bytes() == b"<html>original</html>"
    restored.activate_course(selected)
    assert restored.course(selected) == {
        "last": "",
        "scroll": {},
        "favorites": [],
        "notes": {},
    }
    assert restored.course(other) == other_data


def test_missing_store_key_is_noop(courses):
    store, _ = courses
    before = deepcopy(store.data)
    assert store.remove_course("missing") is False
    assert store.data == before


def test_unavailable_course_can_be_removed_without_accessing_materials(tmp_path):
    store = Store(tmp_path)
    missing = tmp_path / "missing-course"
    store.activate_course(missing)
    assert store.remove_course(str(missing.resolve())) is True
    assert store.data == {"courses": {}}
    assert not missing.exists()


@pytest.fixture
def reader(courses):
    store, roots = courses
    state = SimpleNamespace(
        store=store,
        root=roots[0].resolve(),
        current=roots[0].resolve() / "1.html",
        navigation_generation=7,
        loading=True,
        restore_position=True,
        closing=False,
        page=Mock(pending_restore="old"),
        view=Mock(),
        save_timer=Mock(),
        catalog_timer=Mock(),
        catalog_fallback=Mock(),
        catalog_watcher=Mock(),
        tree=Mock(),
        tree_search=Mock(),
        notes_search=Mock(),
        notes_dock=Mock(),
        favorites=Mock(),
        favorite_action=Mock(),
        notes_list=Mock(),
        notes_hint=Mock(),
        notes_action=Mock(),
        focus_page_button=Mock(),
        note_target=Mock(),
        collapsed_note_groups=set(),
        note_groups={},
        note_buttons={
            name: Mock()
            for name in ("Добавить", "Открыть страницу", "Изменить", "Удалить")
        },
        directory_items={},
        items={"old": object()},
        files=[roots[0] / "1.html"],
        filter_tree=Mock(),
        hide_find=Mock(),
        statusBar=Mock(return_value=Mock()),
        confirm_course_removal=Mock(return_value=True),
        selected_note=Mock(return_value=None),
    )
    state.tree.currentItem.return_value = None
    state.notes_list.currentItem.return_value = None
    state.notes_search.text.return_value = ""
    state.catalog_watcher.directories.return_value = [str(roots[0])]
    state.view.url.return_value = QUrl.fromLocalFile(str(state.current))
    state.view.zoomFactor.return_value = 1.0
    state.persist = lambda: Window.persist(cast(Window, state))
    state.clear_course = lambda: Window.clear_course(cast(Window, state))
    state.rebuild = lambda files: Window.rebuild(cast(Window, state), files)
    state.refresh_metadata = lambda: Window.refresh_metadata(cast(Window, state))
    state.refresh_notes = lambda: Window.refresh_notes(cast(Window, state))
    state.update_note_group_icons = lambda: Window.update_note_group_icons(
        cast(Window, state)
    )
    state.update_note_actions = lambda: Window.update_note_actions(cast(Window, state))
    state.update_focus_button = lambda: Window.update_focus_button(cast(Window, state))
    return state


def test_current_removal_clears_ui_and_stale_events_cannot_recreate_history(
    reader, tmp_path
):
    """Given: callback старой страницы. When: курс удалён. Then: история не воскресает."""
    root, current = reader.root, reader.current
    reader.collapsed_note_groups.add("1.html")
    reader.note_groups["1.html"] = (Mock(), [Mock()])
    Window.loaded(reader, True)
    callback = reader.page.runJavaScript.call_args.args[1]
    assert Window.remove_course(reader, str(root)) is True
    callback(None)
    Window.local_link(reader, str(current), True)
    Window.loaded(reader, True)
    Window.scroll_changed(reader, cast(QPointF, SimpleNamespace(y=lambda: 99)))
    reader.persist()
    assert str(root) not in Store(tmp_path).data["courses"]
    assert reader.root is reader.current is None
    assert reader.collapsed_note_groups == set()
    assert reader.note_groups == {}
    assert reader.navigation_generation == 8
    assert reader.loading is True
    assert reader.restore_position is False
    assert reader.page.pending_restore is None
    assert reader.files == [] and reader.items == {} and reader.directory_items == {}
    for timer in (reader.save_timer, reader.catalog_timer, reader.catalog_fallback):
        timer.stop.assert_called_once_with()
    reader.save_timer.start.assert_not_called()
    reader.catalog_watcher.removePaths.assert_called_once_with([str(root)])
    reader.view.stop.assert_called_once_with()
    reader.view.setUrl.assert_called_once_with(QUrl("about:blank"))
    reader.tree.clear.assert_called_once_with()
    reader.tree_search.clear.assert_called_once_with()
    reader.tree_search.hide.assert_called_once_with()
    reader.notes_search.clear.assert_called_once_with()
    reader.hide_find.assert_called_once_with()
    reader.notes_dock.hide.assert_called_once_with()
    reader.favorites.clear.assert_called_once_with()
    reader.notes_list.clear.assert_called_once_with()
    reader.notes_action.setText.assert_called_once_with("Заметки (0)")
    reader.favorite_action.setEnabled.assert_called_once_with(False)
    for button in reader.note_buttons.values():
        button.setEnabled.assert_called_once_with(False)
    reader.statusBar().clearMessage.assert_called_once_with()
    assert current.read_bytes() == b"<html>original</html>"


def test_other_course_removal_preserves_current_ui(reader, courses):
    _, roots = courses
    current, generation = reader.current, reader.navigation_generation
    before = deepcopy(reader.store.course(reader.root))
    assert Window.remove_course(reader, str(roots[1].resolve())) is True
    assert reader.current == current and reader.navigation_generation == generation
    assert reader.store.course(reader.root) == before
    reader.view.stop.assert_not_called()
    reader.tree.clear.assert_not_called()
    reader.save_timer.stop.assert_not_called()


@pytest.mark.parametrize("missing", [False, True])
def test_cancel_or_unknown_key_never_changes_history_or_ui(reader, tmp_path, missing):
    reader.confirm_course_removal.return_value = False
    before = deepcopy(reader.store.data)
    persisted = (tmp_path / "history.json").read_bytes()
    assert (
        Window.remove_course(reader, "missing" if missing else str(reader.root))
        is False
    )
    assert reader.store.data == before
    assert (tmp_path / "history.json").read_bytes() == persisted
    reader.view.stop.assert_not_called()
    if missing:
        reader.confirm_course_removal.assert_not_called()


def test_failed_save_restores_history_and_active_ui(reader, tmp_path, monkeypatch):
    import os

    before = deepcopy(reader.store.data)
    current, root = reader.current, reader.root
    persisted = (tmp_path / "history.json").read_bytes()
    real_replace = os.replace

    def fail_history_replace(source, destination):
        if destination == tmp_path / "history.json":
            raise OSError("simulated disk failure")
        real_replace(source, destination)

    warning = Mock()
    monkeypatch.setattr(os, "replace", fail_history_replace)
    monkeypatch.setattr("src.course_reader.window.QMessageBox.warning", warning)
    assert Window.remove_course(reader, str(root)) is False
    assert reader.store.data == before
    assert (tmp_path / "history.json").read_bytes() == persisted
    assert reader.current == current and reader.root == root
    assert reader.navigation_generation == 7
    reader.view.stop.assert_not_called()
    reader.tree.clear.assert_not_called()
    reader.save_timer.stop.assert_not_called()
    warning.assert_called_once()
    assert "simulated disk failure" in warning.call_args.args[2]


@pytest.mark.parametrize("answer", ["remove", "cancel", "close"])
def test_confirmation_requires_explicit_remove_and_defaults_to_cancel(
    monkeypatch, answer
):
    remove, cancel = object(), object()
    dialog = Mock()
    dialog.addButton.side_effect = [remove, cancel]
    dialog.clickedButton.return_value = {
        "remove": remove,
        "cancel": cancel,
        "close": None,
    }[answer]
    factory = Mock(
        return_value=dialog, Icon=QMessageBox.Icon, ButtonRole=QMessageBox.ButtonRole
    )
    monkeypatch.setattr("src.course_reader.window.QMessageBox", factory)
    assert Window.confirm_course_removal(
        cast(Window, SimpleNamespace()), "C:/Курс"
    ) is (answer == "remove")
    dialog.setDefaultButton.assert_called_once_with(cancel)
    dialog.setEscapeButton.assert_called_once_with(cancel)
    text = dialog.setText.call_args.args[0]
    assert "История чтения, избранное и заметки" in text
    assert "Папка и файлы курса останутся на диске" in text
    dialog.deleteLater.assert_called_once_with()


@pytest.mark.parametrize("success", [False, True])
def test_chooser_removes_selected_row_only_after_success(monkeypatch, success):
    from src.course_reader import window as module

    listing, layout, dialog = Mock(), Mock(), Mock()
    selected = Mock()
    selected.text.return_value = "selected-course"
    listing.currentItem.return_value = None
    listing.row.return_value = 0
    buttons = {}

    def button(label):
        buttons[label] = Mock()
        return buttons[label]

    monkeypatch.setattr(module, "QDialog", Mock(return_value=dialog))
    monkeypatch.setattr(module, "QVBoxLayout", Mock(return_value=layout))
    monkeypatch.setattr(module, "QListWidget", Mock(return_value=listing))
    monkeypatch.setattr(module, "QPushButton", button)
    monkeypatch.setattr(module, "CourseRowDelegate", Mock())
    monkeypatch.setattr(module, "interface_font", Mock())
    state = SimpleNamespace(
        root=None,
        store=SimpleNamespace(
            data={"courses": {"selected-course": {}}},
            settings={"app": {"theme": "dark"}},
        ),
        remove_course=Mock(return_value=success),
    )
    Window.choose_course(cast(Window, state))
    remove = buttons["Удалить из списка"]
    remove.setEnabled.assert_called_once_with(False)
    changed = listing.currentItemChanged.connect.call_args.args[0]
    changed(selected, None)
    assert remove.setEnabled.call_args.args == (True,)
    listing.currentItem.return_value = selected
    remove.clicked.connect.call_args.args[0]()
    state.remove_course.assert_called_once_with("selected-course")
    if success:
        listing.takeItem.assert_called_once_with(0)
    else:
        listing.takeItem.assert_not_called()
    changed(None, selected)
    assert remove.setEnabled.call_args.args == (False,)
    dialog.accept.assert_not_called()
