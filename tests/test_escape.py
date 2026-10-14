"""Проверить приоритет Esc и закрытие панелей без создания GUI."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QWidget

from src.course_reader.window import Window


@pytest.fixture
def escape_state(monkeypatch):
    notes_child, page_child, foreign = object(), object(), object()
    state = SimpleNamespace(
        closing=False,
        notes_dock=Mock(),
        find_bar=Mock(),
        view=Mock(),
        hide_find=Mock(),
        tree_search=Mock(),
        tree=Mock(),
    )
    state.isAncestorOf = lambda widget: any(
        widget is own for own in (state.notes_dock, notes_child, page_child)
    )
    state.tree_search.isVisible.return_value = False
    state.tree_search.isAncestorOf.return_value = False
    state.tree.isAncestorOf.return_value = False
    state.notes_dock.isAncestorOf.side_effect = lambda widget: widget is notes_child
    state.notes_dock.isVisible.return_value = True
    state.find_bar.isVisible.return_value = True
    app = Mock()
    app.activeModalWidget.return_value = None
    app.activePopupWidget.return_value = None
    app.focusWidget.return_value = page_child
    monkeypatch.setattr("src.course_reader.window.QApplication", app)
    return state, app, notes_child, page_child, foreign


@pytest.mark.parametrize(
    "focus_name,find_visible,notes_visible,expected",
    [
        ("notes_child", True, True, "notes"),
        ("notes_dock", True, True, "notes"),
        ("page_child", True, True, "find"),
        ("self", True, True, "find"),
        ("page_child", False, True, "notes"),
        ("page_child", True, False, "find"),
        ("page_child", False, False, None),
        ("foreign", True, True, None),
        ("none", True, True, None),
    ],
)
def test_escape_target_respects_focus_and_visible_panels(
    escape_state, focus_name, find_visible, notes_visible, expected
):
    """Given: видимость панелей и фокус. When: нажат Esc. Then: выбрана одна доступная панель."""
    state, app, notes_child, page_child, foreign = escape_state
    app.focusWidget.return_value = {
        "notes_child": notes_child,
        "notes_dock": state.notes_dock,
        "page_child": page_child,
        "self": state,
        "foreign": foreign,
        "none": None,
    }[focus_name]
    state.find_bar.isVisible.return_value = find_visible
    state.notes_dock.isVisible.return_value = notes_visible
    assert Window.escape_target(state) == expected


@pytest.mark.parametrize("blocker", ["modal", "popup", "closing"])
def test_escape_leaves_modal_popup_and_closing_windows_untouched(escape_state, blocker):
    """Given: диалог, меню или закрытие окна. When: нажат Esc. Then: панели не выбираются."""
    state, app, *_ = escape_state
    if blocker == "closing":
        state.closing = True
    else:
        getattr(
            app, "activeModalWidget" if blocker == "modal" else "activePopupWidget"
        ).return_value = object()
    assert Window.escape_target(state) is None


@pytest.fixture
def filtered_event():
    child = Mock(spec=QWidget)
    state = SimpleNamespace(
        isAncestorOf=lambda widget: widget is child,
        escape_target=Mock(return_value="find"),
        hide_find=Mock(),
        notes_dock=Mock(),
        view=Mock(),
        hide_tree_search=Mock(),
    )
    event = Mock()
    event.type.return_value = QEvent.Type.KeyPress
    event.key.return_value = Qt.Key.Key_Escape
    event.modifiers.return_value = Qt.KeyboardModifier.NoModifier
    event.isAutoRepeat.return_value = False
    return state, child, event


@pytest.mark.parametrize("target", ["find", "notes", "tree_search"])
@pytest.mark.parametrize(
    "event_type,repeat,closes",
    [
        (QEvent.Type.ShortcutOverride, False, False),
        (QEvent.Type.KeyPress, False, True),
        (QEvent.Type.KeyPress, True, False),
    ],
)
def test_escape_claims_shortcut_but_closes_one_panel_only_on_initial_press(
    filtered_event, target, event_type, repeat, closes
):
    """Given: выбранная панель. When: приходит событие Esc. Then: закрытие лишь при первом KeyPress."""
    state, child, event = filtered_event
    state.escape_target.return_value = target
    event.type.return_value = event_type
    event.isAutoRepeat.return_value = repeat

    assert Window.eventFilter(state, child, event) is True

    event.accept.assert_called_once_with()
    assert state.hide_tree_search.call_count == int(closes and target == "tree_search")
    assert state.hide_find.call_count == int(closes and target == "find")
    assert state.notes_dock.hide.call_count == int(closes and target == "notes")
    assert state.view.setFocus.call_count == int(closes and target == "notes")


@pytest.mark.parametrize(
    "reason", ["event_type", "key", "modifier", "foreign", "non_widget", "no_target"]
)
def test_unhandled_events_are_not_accepted_or_used_to_close_panels(
    filtered_event, reason
):
    """Given: неподходящее событие или получатель. When: фильтрация. Then: событие не поглощается."""
    state, child, event = filtered_event
    watched = child
    if reason == "event_type":
        event.type.return_value = QEvent.Type.KeyRelease
    elif reason == "key":
        event.key.return_value = Qt.Key.Key_Return
    elif reason == "modifier":
        event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
    elif reason == "foreign":
        watched = Mock(spec=QWidget)
    elif reason == "non_widget":
        watched = object()
    else:
        state.escape_target.return_value = None

    assert Window.eventFilter(state, watched, event) is False

    event.accept.assert_not_called()
    state.hide_tree_search.assert_not_called()
    state.hide_find.assert_not_called()
    state.notes_dock.hide.assert_not_called()
    state.view.setFocus.assert_not_called()


def test_hide_find_clears_highlight_and_restores_page_focus():
    """Given: панель поиска. When: её закрывают. Then: подсветка снята, фокус возвращён странице."""
    state = SimpleNamespace(view=Mock(), find_bar=Mock(), notes_dock=Mock())

    Window.hide_find(cast(Window, state))

    state.view.findText.assert_called_once_with("")
    state.find_bar.hide.assert_called_once_with()
    state.view.setFocus.assert_called_once_with()
    state.notes_dock.hide.assert_not_called()
