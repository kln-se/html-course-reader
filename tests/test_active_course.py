"""Проверки восстановления активного курса без запуска окон и WebEngine."""

from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.course_reader import __main__ as entrypoint
from src.course_reader.storage import Store
from src.course_reader.window import Window


def test_active_course_roundtrip_switches_without_losing_page_data(tmp_path):
    store = Store(tmp_path)
    first, second = tmp_path / 'Первый', tmp_path / 'Второй'
    store.course(first)['last'] = 'chapter/1.html'
    store.activate_course(first)
    store.activate_course(second)
    store.save()
    restored = Store(tmp_path)
    assert restored.active_course == second.resolve()
    assert restored.course(first)['last'] == 'chapter/1.html'
    restored.activate_course(first)
    restored.save()
    assert Store(tmp_path).active_course == first.resolve()


def test_old_history_has_no_implicitly_selected_course(tmp_path):
    store = Store(tmp_path)
    store.course(tmp_path / 'old')['last'] = '1.html'
    store.save()
    restored = Store(tmp_path)
    assert restored.active_course is None
    assert restored.course(tmp_path / 'old')['last'] == '1.html'


@pytest.mark.parametrize('active', [None, 1, [], {}])
def test_invalid_active_course_is_rejected_without_overwriting(tmp_path, active):
    history = tmp_path / 'history.json'
    original = json.dumps({'courses': {}, 'active_course': active})
    history.write_text(original, encoding='utf-8')
    with pytest.raises(ValueError, match='активный курс'):
        Store(tmp_path)
    assert history.read_text(encoding='utf-8') == original


@pytest.mark.parametrize('move_active', [False, True])
def test_relocate_updates_only_selected_course_and_survives_reload(tmp_path, move_active):
    store = Store(tmp_path)
    active, other, target = (tmp_path / name for name in ('active', 'other', 'target'))
    store.activate_course(active)
    store.course(other)['last'] = '2.html'
    source = active if move_active else other
    before = deepcopy(store.course(source))
    store.relocate(str(source.resolve()), target)
    store.save()
    restored = Store(tmp_path)
    assert restored.active_course == (target if move_active else active).resolve()
    assert restored.course(target) == before
    assert str(source.resolve()) not in restored.data['courses']


def test_relocate_collision_preserves_active_course_and_history(tmp_path):
    store = Store(tmp_path)
    active, target = tmp_path / 'active', tmp_path / 'target'
    store.activate_course(active)
    store.course(target)['last'] = '2.html'
    before = deepcopy(store.data)
    with pytest.raises(ValueError):
        store.relocate(str(active.resolve()), target)
    store.save()
    assert Store(tmp_path).data == before


@pytest.fixture
def course_window(tmp_path):
    """Оставить реальную логику курса и заменить границы отображения Qt."""
    opened, messages, chooser = [], [], []
    state = SimpleNamespace(
        store=Store(tmp_path), root=None, current=None, tree_search=Mock(),
        notes_search=Mock(),
        catalog_timer=SimpleNamespace(stop=lambda: None),
        catalog_fallback=SimpleNamespace(stop=lambda: None),
        view=SimpleNamespace(setUrl=lambda url: None),
        page=SimpleNamespace(open_saved=lambda url: opened.append(url.toLocalFile())),
        rebuild=lambda: None, refresh_metadata=lambda: None,
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
        choose_course=lambda: chooser.append(True),
        opened=opened, messages=messages, chooser=chooser,
    )
    state.persist = lambda: Window.persist(state)
    state.set_course = lambda root: Window.set_course(state, root)
    state.open_file = lambda path: Window.open_file(state, path)
    return state


@pytest.mark.parametrize('reason', ['old-history', 'unknown', 'missing', 'file'])
def test_restore_unavailable_course_shows_chooser_without_changing_history(
    course_window, tmp_path, reason,
):
    store = course_window.store
    available = tmp_path / 'available'
    available.mkdir()
    store.course(available)
    candidate = tmp_path / 'candidate'
    if reason == 'unknown':
        candidate.mkdir()
        store.data['active_course'] = str(candidate.resolve())
    elif reason in ('missing', 'file'):
        if reason == 'file':
            candidate.write_text('not a directory', encoding='utf-8')
        store.activate_course(candidate)
    store.save()
    course_window.store = Store(tmp_path)
    before = deepcopy(course_window.store.data)
    Window.restore_course(course_window)
    assert course_window.chooser == [True]
    assert course_window.opened == []
    assert course_window.root is None
    assert course_window.store.data == before


def test_restore_opens_saved_page_of_active_course_not_another_course(course_window, tmp_path):
    """Given: два курса. When: новый запуск. Then: открыта последняя страница активного."""
    first, active = tmp_path / 'first', tmp_path / 'active'
    first.mkdir()
    active.mkdir()
    (first / '1.html').write_text('first', encoding='utf-8')
    page = active / '2.html'
    page.write_text('active', encoding='utf-8')
    course_window.store.course(first)['last'] = '1.html'
    course_window.store.course(active)['last'] = page.name
    course_window.store.activate_course(active)
    course_window.store.save()
    course_window.store = Store(tmp_path)
    Window.restore_course(course_window)
    assert course_window.root == active.resolve()
    assert [Path(path) for path in course_window.opened] == [page.resolve()]
    assert course_window.chooser == []


@pytest.mark.parametrize('last', ['', 'deleted.html'])
def test_select_course_without_available_page_still_persists_active(course_window, tmp_path, last):
    root = tmp_path / 'empty'
    root.mkdir()
    course_window.store.course(root)['last'] = last
    Window.set_course(course_window, root)
    restored = Store(tmp_path)
    assert restored.active_course == root.resolve()
    assert restored.course(root)['last'] == last
    assert course_window.opened == []
    assert course_window.messages == [str(root.resolve())]
    assert course_window.current is None


def test_main_restores_course_after_showing_window(monkeypatch, tmp_path):
    calls = []
    app = SimpleNamespace(setApplicationName=lambda name: None, exec=lambda: 17)
    window = SimpleNamespace(show=lambda: calls.append('show'),
                             restore_course=lambda: calls.append('restore'))
    monkeypatch.setattr(entrypoint, 'QApplication', lambda args: app)
    # Изолированная папка исключает чтение пользовательской истории рядом с приложением.
    monkeypatch.setattr(entrypoint, 'Store', lambda directory: Store(tmp_path))
    monkeypatch.setattr(entrypoint, 'Window', lambda store: window)
    assert entrypoint.main() == 17
    assert calls == ['show', 'restore']
