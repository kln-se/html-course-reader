"""Проверки каталога и наблюдения без окон и запуска Проводника."""
from types import SimpleNamespace as NS
import pytest

from src.course_reader.catalog import scan, explorer_arguments
from src.course_reader.window import Window


def test_catalog_detects_new_nested_files_and_rename(tmp_path):
    """Добавление, фильтрация, переименование и удаление отражаются новым снимком."""
    empty = tmp_path / '01-пустая'
    empty.mkdir()
    directories = []
    assert scan(tmp_path, ['*.html'], directories=directories) == []
    assert directories == [tmp_path, empty]
    page = empty / '2.html'
    page.write_text('page')
    (empty / 'movie.mp4').write_bytes(b'video')
    assert scan(tmp_path, ['*.html']) == [page]
    renamed = empty / '10.html'
    page.rename(renamed)
    assert scan(tmp_path, ['*.html']) == [renamed]
    renamed.unlink()
    assert scan(tmp_path, ['*.html']) == []


def test_explorer_arguments_are_separate_and_preserve_names(tmp_path):
    folder = tmp_path / 'Курс с пробелами, & символами'
    folder.mkdir()
    page = folder / '01 DDD.html'
    page.write_text('page')
    assert explorer_arguments(folder) == ['explorer.exe', '/select,', str(folder)]
    assert explorer_arguments(page) == ['explorer.exe', '/select,', str(page)]
    with pytest.raises(FileNotFoundError):
        explorer_arguments(folder / 'missing.html')


def test_explorer_launch_uses_no_shell_and_missing_path_warns(tmp_path, monkeypatch):
    opened, warned = [], []
    page = tmp_path / '1.html'
    page.write_text('page')
    state = NS(root=tmp_path)
    monkeypatch.setattr('src.course_reader.window.subprocess.Popen',
                        lambda args, **kwargs: opened.append((args, kwargs)))
    monkeypatch.setattr('src.course_reader.window.QMessageBox.warning',
                        lambda *args: warned.append(args))
    Window.show_in_explorer(state, page)
    assert opened == [(['explorer.exe', '/select,', str(page)], {'shell': False})]
    Window.show_in_explorer(state, tmp_path / 'missing.html')
    assert len(opened) == 1 and len(warned) == 1
    Window.show_in_explorer(state, tmp_path.parent / 'outside.html')
    assert len(opened) == 1 and len(warned) == 1


class Timer:
    """Записывать состояние таймера без цикла событий Qt."""
    def __init__(self):
        self.active = False
        self.starts = 0
    def start(self):
        self.active = True
        self.starts += 1
    def stop(self):
        self.active = False
    def isActive(self):
        return self.active


class Watcher:
    """Имитировать исключительно внешнюю регистрацию системного наблюдения."""
    def __init__(self, paths=(), failed=()):
        self.paths = set(paths)
        self.failed = set(failed)
    def directories(self):
        return list(self.paths)
    def removePaths(self, paths):
        self.paths.difference_update(paths)
    def addPaths(self, paths):
        self.paths.update(set(paths) - self.failed)
        return sorted(set(paths) & self.failed)


def test_watch_sync_switches_course_and_recovers_from_failed_watch(tmp_path):
    child = tmp_path / 'empty'
    child.mkdir()
    watcher = Watcher(['old-course'], [str(child)])
    timer = Timer()
    state = NS(root=tmp_path, catalog_watcher=watcher, catalog_fallback=timer)
    Window.sync_catalog_watches(state, [tmp_path, child])
    assert watcher.paths == {str(tmp_path)}
    assert timer.active
    watcher.failed.clear()
    Window.sync_catalog_watches(state, [tmp_path, child])
    assert watcher.paths == {str(tmp_path), str(child)}
    assert not timer.active
    Window.sync_catalog_watches(state, [tmp_path])
    assert watcher.paths == {str(tmp_path)}


def test_missing_root_enables_recovery_polling(tmp_path):
    state = NS(root=tmp_path / 'missing', catalog_watcher=Watcher(),
               catalog_fallback=Timer())
    Window.sync_catalog_watches(state, [])
    assert state.catalog_fallback.active


def test_events_coalesce_without_postponing_forever(tmp_path):
    state = NS(root=tmp_path, closing=False, catalog_timer=Timer())
    for _ in range(10):
        Window.schedule_catalog_refresh(state, str(tmp_path))
    assert state.catalog_timer.starts == 1
    state.catalog_timer.stop()
    state.closing = True
    Window.schedule_catalog_refresh(state, str(tmp_path))
    assert state.catalog_timer.starts == 1


def test_refresh_updates_watches_even_if_visible_files_are_unchanged(tmp_path):
    watches, rebuilds = [], []
    state = NS(root=tmp_path, closing=False, files=[], store=NS(patterns=['*.html']),
               sync_catalog_watches=lambda paths: watches.append(paths),
               rebuild=lambda files: rebuilds.append(files))
    Window.refresh_catalog(state)
    assert watches == [[tmp_path]] and not rebuilds
    empty = tmp_path / 'empty'
    empty.mkdir()
    Window.refresh_catalog(state)
    assert watches[-1] == [tmp_path, empty] and not rebuilds


def test_refresh_filters_and_does_not_touch_current_page(tmp_path):
    page = tmp_path / '1.html'
    page.write_text('page')
    (tmp_path / 'movie.mp4').write_bytes(b'video')
    rebuilt = []
    state = NS(root=tmp_path, closing=False, files=[], current=page,
               store=NS(patterns=['*.html']),
               sync_catalog_watches=lambda paths: None,
               rebuild=lambda files: rebuilt.append(files))
    Window.refresh_catalog(state)
    assert rebuilt == [[page]]
    assert state.current == page
    state.files = [page]
    Window.refresh_catalog(state)
    assert len(rebuilt) == 1
    state.closing = True
    Window.refresh_catalog(state)
    assert len(rebuilt) == 1


class Node:
    """Минимальная модель элемента дерева для проверки сохранения его состояния."""
    def __init__(self, parent=None, labels=None):
        self.path = None
        self.expanded = False
    def data(self, column, role):
        return self.path
    def setData(self, column, role, value):
        self.path = value
    def setToolTip(self, *args):
        pass
    def isExpanded(self):
        return self.expanded
    def setExpanded(self, value):
        self.expanded = value


class Bar:
    """Запоминать позицию полосы прокрутки."""
    def __init__(self, value):
        self.position = value
    def value(self):
        return self.position
    def setValue(self, value):
        self.position = value


class Tree:
    """Имитировать дерево как внешнюю границу обновления виджетов."""
    def __init__(self, selected):
        self.selected = selected
        self.vertical = Bar(73)
        self.horizontal = Bar(12)
        self.updates = True
    def currentItem(self):
        return self.selected
    def verticalScrollBar(self):
        return self.vertical
    def horizontalScrollBar(self):
        return self.horizontal
    def setUpdatesEnabled(self, value):
        self.updates = value
    def clear(self):
        self.selected = None
        self.vertical.setValue(0)
        self.horizontal.setValue(0)
    def invisibleRootItem(self):
        return Node()
    def setCurrentItem(self, item):
        self.selected = item


def test_rebuild_preserves_selection_expansion_scroll_and_current(tmp_path, monkeypatch):
    folder = tmp_path / 'chapter'
    page = folder / '1.html'
    other = folder / '2.html'
    selected = Node()
    selected.path = str(page)
    expanded = Node()
    expanded.expanded = True
    tree = Tree(selected)
    state = NS(root=tmp_path, current=page, tree=tree, items={str(page): selected},
               directory_items={str(folder): expanded}, files=[page])
    monkeypatch.setattr('src.course_reader.window.QTreeWidgetItem', Node)
    Window.rebuild(state, [page, other])
    assert state.files == [page, other]
    assert state.current == page
    assert tree.selected.path == str(page)
    assert state.directory_items[str(folder)].expanded
    assert tree.vertical.position == 73 and tree.horizontal.position == 12
    assert tree.updates


def test_clicking_directory_does_not_open_page(tmp_path):
    folder = Node()
    folder.path = str(tmp_path)
    opened = []
    state = NS(items={}, open_file=opened.append)
    Window.tree_clicked(state, folder, 0)
    assert opened == []


def test_removed_root_reappears_and_returns_from_polling_to_watches(tmp_path):
    """Удалённый корень восстанавливается через fallback с новой подпиской и файлами."""
    root = tmp_path / 'course'
    root.mkdir()
    first = root / '1.html'
    first.write_text('first')
    state = NS(root=root, closing=False, files=[first],
               store=NS(patterns=['*.html']), catalog_watcher=Watcher([str(root)]),
               catalog_fallback=Timer())
    state.sync_catalog_watches = lambda paths: Window.sync_catalog_watches(state, paths)
    state.rebuild = lambda files: setattr(state, 'files', files)
    first.unlink()
    root.rmdir()
    Window.refresh_catalog(state)
    assert state.files == [] and state.catalog_fallback.active
    assert state.catalog_watcher.paths == set()
    root.mkdir()
    replacement = root / '2.html'
    replacement.write_text('replacement')
    Window.refresh_catalog(state)
    assert state.files == [replacement]
    assert state.catalog_watcher.paths == {str(root)}
    assert not state.catalog_fallback.active


def test_delayed_event_uses_new_root_and_does_nothing_after_close(tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.mkdir()
    new.mkdir()
    old_page, new_page = old / '1.html', new / '2.html'
    old_page.write_text('old')
    new_page.write_text('new')
    state = NS(root=old, closing=False, files=[old_page],
               store=NS(patterns=['*.html']), catalog_watcher=Watcher([str(old)]),
               catalog_timer=Timer(), catalog_fallback=Timer())
    state.sync_catalog_watches = lambda paths: Window.sync_catalog_watches(state, paths)
    state.rebuild = lambda files: setattr(state, 'files', files)
    Window.schedule_catalog_refresh(state, str(old))
    state.root = new
    Window.refresh_catalog(state)
    assert state.files == [new_page]
    assert state.catalog_watcher.paths == {str(new)}
    state.closing = True
    state.store = None
    state.catalog_watcher = None
    Window.refresh_catalog(state)
    assert state.files == [new_page]
