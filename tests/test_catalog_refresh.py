"""Проверки каталога и наблюдения без окон и запуска Проводника."""
from types import SimpleNamespace as NS
import pytest
from PySide6.QtCore import Qt

from src.course_reader.catalog import scan, explorer_arguments
from src.course_reader.window import Window
from src.course_reader.theme import TREE_FOLDER_ROLE, TREE_PREFIX_ROLE


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
        self.labels = labels or []
        self.tooltips = {}
        self.values = {}
        self.children = []
        if parent is not None:
            parent.children.append(self)
    def data(self, column, role):
        return self.values.get((column, role), self.path if role == Qt.ItemDataRole.UserRole else None)
    def setData(self, column, role, value):
        self.values[column, role] = value
        if role == Qt.ItemDataRole.UserRole:
            self.path = value
    def setToolTip(self, column, value):
        self.tooltips[column] = value
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


@pytest.fixture
def rebuild_state(tmp_path, monkeypatch):
    monkeypatch.setattr('src.course_reader.window.QTreeWidgetItem', Node)
    return NS(root=tmp_path, current=None, tree=Tree(None), items={},
              directory_items={}, files=[])


def test_rebuild_labels_suffixes_without_changing_paths_or_folders(rebuild_state):
    state = rebuild_state
    folder = state.root / 'Chapter.HTML' / 'nested'
    expected = {
        '01.HTML': '[.html] 01.HTML',
        '02.HtM': '[.htm] 02.HtM',
        '03.MP4': '[.mp4] 03.MP4',
        '04.tar.GZ': '[.gz] 04.tar.GZ',
        'README': 'README',
        '.hidden': '.hidden',
    }
    files = [folder / name for name in expected]
    Window.rebuild(state, files)
    for path in files:
        item = state.items[str(path)]
        assert item.labels == [expected[path.name]]
        assert item.values[0, Qt.ItemDataRole.UserRole] == str(path)
        assert item.tooltips[0] == path.relative_to(state.root).as_posix()
    for path in (folder.parent, folder):
        item = state.directory_items[str(path)]
        assert item.labels == [path.name]
        assert item.values[0, Qt.ItemDataRole.UserRole] == str(path)
        assert item.tooltips[0] == path.relative_to(state.root).as_posix()


def test_rebuild_keeps_natural_file_order_with_mixed_suffixes(rebuild_state):
    state = rebuild_state
    folder = state.root / 'chapter'
    folder.mkdir()
    for name in ['10.html', '2.mp4', '1.txt']:
        (folder / name).write_text('material', encoding='utf-8')
    files = scan(state.root, ['*'])
    Window.rebuild(state, files)
    expected = [folder / name for name in ['1.txt', '2.mp4', '10.html']]
    assert state.files == expected
    assert list(state.items) == [str(path) for path in expected]
    assert [item.path for item in state.directory_items[str(folder)].children] == [
        str(path) for path in expected
    ]


def test_clicking_prefixed_file_opens_original_path(rebuild_state):
    state = rebuild_state
    page = state.root / 'chapter' / '01.HTML'
    Window.rebuild(state, [page])
    opened = []
    state.open_file = opened.append
    item = state.items[str(page)]
    assert item.labels == ['[.html] 01.HTML']
    Window.tree_clicked(state, item, 0)
    assert opened == [page]


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


def test_rebuild_style_roles_do_not_replace_paths_or_full_labels(rebuild_state):
    """Given: папка и разные суффиксы. When: перестройка. Then: стиль отделён от пути."""
    state = rebuild_state
    folder = state.root / 'Chapter.HTML'
    files = [folder / name for name in ('01.HTML', '02.tar.GZ', 'README', '.hidden')]
    Window.rebuild(state, files)
    directory = state.directory_items[str(folder)]
    assert directory.data(0, TREE_FOLDER_ROLE) is True
    assert directory.data(0, TREE_PREFIX_ROLE) is None
    assert directory.data(0, Qt.ItemDataRole.UserRole) == str(folder)
    assert directory.labels == ['Chapter.HTML']
    for path in files:
        item = state.items[str(path)]
        prefix = f'[{path.suffix.lower()}]' if path.suffix else None
        assert item.data(0, TREE_PREFIX_ROLE) == prefix
        assert item.data(0, TREE_FOLDER_ROLE) is None
        assert item.data(0, Qt.ItemDataRole.UserRole) == str(path)
        assert item.labels == [f'{prefix} {path.name}' if prefix else path.name]