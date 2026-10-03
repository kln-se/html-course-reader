"""Интерфейс чтения, выбора курсов и работы с заметками."""
from datetime import datetime, timezone
from copy import deepcopy
from pathlib import Path
import subprocess
from shiboken6 import delete
from PySide6.QtCore import Qt, QUrl, QTimer, QSize, Slot, QFileSystemWatcher, QDateTime, QLocale, QEvent
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QTreeWidget, QTreeWidgetItem, QListWidget,
    QTabWidget, QSplitter, QToolBar, QMessageBox, QFileDialog, QDialog, QVBoxLayout,
    QPushButton, QInputDialog, QDockWidget, QWidget, QLineEdit, QCheckBox, QComboBox,
    QDialogButtonBox, QFormLayout, QLabel, QMenu, QListWidgetItem, QHBoxLayout, QToolButton, QApplication)
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from .catalog import scan, PAGE_SUFFIXES, adjacent, explorer_arguments, natural_key
from .viewer import Page, OfflineInterceptor
from .storage import Store
from .remote_settings import RemoteResourcesSettings
from .theme import DockTitleStyle, style_checkbox, TreeRowDelegate, TREE_PREFIX_ROLE, TREE_FOLDER_ROLE, EmptyHint, PALETTES, RowDelegate, icon, interface_font, stylesheet


def format_note_time(value: str) -> str:
    """Показать ISO-дату в локальном часовом поясе и кратком формате системы.

    Значение без смещения трактуется как UTC. Некорректная дата отображается
    как «неизвестно»; сохранённая строка истории не изменяется.
    """
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        local = QDateTime.fromMSecsSinceEpoch(int(moment.timestamp() * 1000))
        if local.isValid():
            return QLocale.system().toString(local, QLocale.FormatType.ShortFormat)
    except (ValueError, OverflowError, OSError):
        pass
    return 'неизвестно'


class Window(QMainWindow):
    """Связывать каталог, просмотрщик и состояние выбранного курса в главном окне."""
    def __init__(self, store: Store):
        """Создать панели, обработчики и профиль WebEngine, применить настройки переданного Store."""
        # Задать шрифт до создания окна: иначе оно наследует прежний шрифт Qt.
        # При повторном применении QSS используется шрифт приложения.
        QApplication.setFont(interface_font())
        super().__init__()
        self.icon_actions = []
        self.store = store
        self.root = None
        self.current = None
        self.loading = False
        self.navigation_generation = 0
        self.restore_position = False
        self.closing = False
        self.files = []
        self.items = {}
        self.directory_items = {}
        self.tree_search_expanded = None
        self.setWindowTitle('Course Reader')
        self.resize(1200, 800)
        self.setMinimumSize(760, 520)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setAccessibleName('Файлы курса')
        self.tree.itemClicked.connect(self.tree_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_context_menu)
        self.catalog_watcher = QFileSystemWatcher(self)
        self.catalog_watcher.directoryChanged.connect(self.schedule_catalog_refresh)
        self.catalog_timer = QTimer(self)
        self.catalog_timer.setSingleShot(True)
        self.catalog_timer.setInterval(250)
        self.catalog_timer.timeout.connect(self.refresh_catalog)
        self.catalog_fallback = QTimer(self)
        self.catalog_fallback.setInterval(3000)
        self.catalog_fallback.timeout.connect(self.refresh_catalog)
        self.favorites = QListWidget()
        self.favorites.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.favorites.setAccessibleName('Избранные страницы курса')
        self.favorites.itemClicked.connect(lambda item: self.open_file(self.root / item.data(Qt.ItemDataRole.UserRole)))
        files_panel = QWidget()
        files_layout = QVBoxLayout(files_panel)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.setSpacing(0)
        tree_controls = QHBoxLayout()
        tree_controls.setContentsMargins(4, 4, 4, 4)
        tree_controls.setSpacing(4)
        for label, icon_name, callback in [('Свернуть всё', 'collapse', self.tree.collapseAll),
                                           ('Развернуть всё', 'expand', self.tree.expandAll),
                                           ('Показать текущую страницу в дереве', 'locate', self.focus_current_page),
                                           ('Найти файл', 'search', self.show_tree_search)]:
            button = QToolButton()
            button.setObjectName('treeControl')
            button.setFixedSize(30, 30)
            button.setIconSize(QSize(20, 20))
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(callback)
            self.icon_actions.append((button, icon_name))
            if icon_name == 'locate':
                self.focus_page_button = button
                button.setEnabled(False)
            tree_controls.addWidget(button)
        tree_controls.addStretch()
        files_layout.addLayout(tree_controls)
        self.tree_search = QLineEdit()
        self.tree_search.setPlaceholderText('Найти файл…')
        self.tree_search.setAccessibleName('Поиск по имени и пути файла')
        self.tree_search.setClearButtonEnabled(True)
        self.tree_search.textChanged.connect(self.filter_tree)
        self.tree_search.hide()
        files_layout.addWidget(self.tree_search)
        self.tree_search_empty = QLabel('Ничего не найдено')
        self.tree_search_empty.setObjectName('caption')
        self.tree_search_empty.setContentsMargins(8, 8, 8, 8)
        self.tree_search_empty.hide()
        files_layout.addWidget(self.tree_search_empty)
        files_layout.addWidget(self.tree)
        tabs = QTabWidget()
        tabs.addTab(files_panel, 'Файлы')
        tabs.addTab(self.favorites, 'Избранное')
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        heading = QLabel('Course Reader')
        heading.setObjectName('brand')
        heading.setContentsMargins(16, 18, 16, 4)
        caption = QLabel('Локальная библиотека курсов')
        caption.setObjectName('caption')
        caption.setContentsMargins(16, 0, 16, 18)
        sidebar_layout.addWidget(heading)
        sidebar_layout.addWidget(caption)
        sidebar_layout.addWidget(tabs)
        sidebar.setMinimumWidth(220)
        self.view = QWebEngineView()
        self.profile = QWebEngineProfile(self)
        self.interceptor = OfflineInterceptor(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.page = Page(self.profile, self.view)
        self.view.setPage(self.page)
        self.apply_remote_resources()
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.page_context_menu)
        self.page.allow_local = self.allow_local
        self.view.loadStarted.connect(self.load_started)
        self.page.internet_requested.connect(self.internet_link)
        self.page.local_requested.connect(self.local_link)
        self.view.loadFinished.connect(self.loaded)
        self.page.loadingChanged.connect(self.report_loading)
        self.page.scrollPositionChanged.connect(self.scroll_changed)
        splitter = QSplitter()
        splitter.addWidget(sidebar)
        splitter.addWidget(self.view)
        splitter.setSizes([280, 920])
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(4)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        toolbar = QToolBar('Чтение')
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        self.action(toolbar, 'Курсы', self.choose_course, icon_name='courses')
        toolbar.addSeparator()
        self.action(toolbar, 'Назад', lambda: self.move(-1), icon_name='back')
        self.action(toolbar, 'Вперёд', lambda: self.move(1), icon_name='next')
        toolbar.addSeparator()
        self.favorite_action = self.action(toolbar, 'Избранное', self.toggle_favorite, icon_name='bookmark')
        self.favorite_action.setCheckable(True)
        self.favorite_action.setEnabled(False)
        self.notes_action = self.action(toolbar, 'Заметки (0)', self.show_notes, icon_name='notes')
        toolbar.addSeparator()
        self.action(toolbar, 'Найти', self.show_find, 'Ctrl+F', icon_name='search')
        self.action(toolbar, 'Уменьшить масштаб', lambda: self.zoom(-0.1), 'Ctrl+-', icon_name='minus', icon_only=True)
        self.zoom_label = QLabel('100%')
        self.zoom_label.setObjectName('caption')
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(48)
        toolbar.addWidget(self.zoom_label)
        self.action(toolbar, 'Увеличить масштаб', lambda: self.zoom(0.1), 'Ctrl+=', icon_name='plus', icon_only=True)
        toolbar.addSeparator()
        self.action(toolbar, 'Настройки', self.settings_dialog, icon_name='settings', icon_only=True)
        self.find_bar = QToolBar('Поиск')
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.find_bar)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText('Поиск по странице')
        self.find_bar.addWidget(self.find_input)
        self.find_input.textChanged.connect(self.view.findText)
        self.find_input.returnPressed.connect(lambda: self.view.findText(self.find_input.text()))
        self.find_bar.setIconSize(QSize(20, 20))
        self.action(self.find_bar, 'Закрыть поиск', self.hide_find, icon_name='close', icon_only=True)
        self.find_bar.hide()
        self.notes_dock = QDockWidget('Заметки курса', self)
        panel = QWidget()
        panel.setObjectName('sidebar')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.notes_search = QLineEdit()
        self.notes_search.setPlaceholderText('Найти заметку…')
        self.notes_search.setAccessibleName('Поиск по тексту заметок курса')
        self.notes_search.setClearButtonEnabled(True)
        self.notes_search.textChanged.connect(lambda _text: self.refresh_notes())
        layout.addWidget(self.notes_search)
        self.notes_list = QListWidget()
        self.notes_list.setWordWrap(True)
        self.notes_list.setAccessibleName('Заметки всего курса')
        self.notes_list.currentItemChanged.connect(lambda current, previous: self.update_note_actions())
        self.notes_list.itemDoubleClicked.connect(
            lambda item: self.open_note_page() if item.data(Qt.ItemDataRole.UserRole) else None)
        self.note_buttons = {}
        layout.addWidget(self.notes_list)
        self.note_target = QLabel('Нет открытой страницы')
        self.note_target.setTextFormat(Qt.TextFormat.PlainText)
        self.note_target.setWordWrap(True)
        layout.addWidget(self.note_target)
        for label, callback in [('Добавить', self.add_note), ('Открыть страницу', self.open_note_page), ('Изменить', self.edit_note), ('Удалить', self.delete_note)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button.setEnabled(False)
            self.note_buttons[label] = button
            if label == 'Добавить':
                button.setText('Добавить к открытой странице')
            layout.addWidget(button)
        self.notes_dock.setWidget(panel)
        self.notes_dock.setMinimumWidth(240)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.notes_dock)
        self.notes_dock.hide()
        try:
            zoom = self.store.settings.getfloat('app', 'zoom')
        except ValueError:
            zoom = 1.0
        self.view.setZoomFactor(max(0.25, min(3.0, zoom)))
        self.zoom_label.setText(f'{self.view.zoomFactor():.0%}')
        self.notes_hint = EmptyHint(self.notes_list, 'Заметок пока нет. Добавьте первую заметку к открытой странице.')
        self.hints = [
            EmptyHint(self.tree, 'Выберите курс кнопкой «Курсы». Если файлы скрыты, проверьте маски в настройках.'),
            EmptyHint(self.favorites, 'Важные страницы будут здесь. Нажмите «Избранное» при чтении.'),
            self.notes_hint,
        ]
        for listing in (self.tree, self.favorites, self.notes_list):
            listing.setItemDelegate(TreeRowDelegate(listing) if listing is self.tree else RowDelegate(listing))
            listing.setMouseTracking(True)
        self.status_bar = self.statusBar()
        self.status_bar.setFont(interface_font(monospace=True))
        self.status_bar.messageChanged.connect(self.update_status_tooltip)
        self.apply_theme()
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.persist)
        QApplication.instance().installEventFilter(self)

    def escape_target(self) -> str | None:
        """Выбрать одну панель для Esc; диалоги, меню и чужие окна имеют приоритет."""
        if self.closing or QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return None
        focus = QApplication.focusWidget()
        if focus is None or not (focus is self or self.isAncestorOf(focus)):
            return None
        if self.notes_dock.isVisible() and (focus is self.notes_dock or self.notes_dock.isAncestorOf(focus)):
            return 'notes'
        if self.tree_search.isVisible() and (focus is self.tree_search or self.tree_search.isAncestorOf(focus)
                                              or focus is self.tree or self.tree.isAncestorOf(focus)):
            return 'tree_search'
        if self.find_bar.isVisible():
            return 'find'
        if self.notes_dock.isVisible():
            return 'notes'
        if self.tree_search.isVisible():
            return 'tree_search'
        return None

    def eventFilter(self, watched, event):
        """Обработать одиночный Esc в окне чтения, не перехватывая отмену диалогов."""
        if event.type() not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        if event.key() != Qt.Key.Key_Escape or event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if not isinstance(watched, QWidget) or not (watched is self or self.isAncestorOf(watched)):
            return False
        target = self.escape_target()
        if target is None:
            return False
        event.accept()
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            if target == 'tree_search':
                self.hide_tree_search()
            elif target == 'find':
                self.hide_find()
            else:
                self.notes_dock.hide()
                self.view.setFocus()
        return True

    @Slot(str)
    def update_status_tooltip(self, message: str) -> None:
        """Обновить полный путь в подсказке строки состояния через зарегистрированный слот Qt."""
        self.status_bar.setToolTip(message)

    def action(self, toolbar, text, callback, shortcut=None, *, icon_name=None, icon_only=False):
        """Создать действие панели с обработчиком и необязательным сочетанием клавиш; вернуть QAction."""
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setToolTip(text + (f' ({shortcut})' if shortcut else ''))
        if icon_name:
            self.icon_actions.append((action, icon_name))
        toolbar.addAction(action)
        if icon_only:
            toolbar.widgetForAction(action).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        return action

    def persist(self):
        """Сохранить состояние; показать предупреждение при ошибке файловой системы."""
        try:
            self.store.save()
        except OSError as error:
            QMessageBox.warning(self, 'Не удалось сохранить данные', str(error))

    def restore_course(self) -> None:
        """Восстановить активный курс и его существующую последнюю страницу.

        Если активная запись отсутствует или корень не является доступной
        директорией, показать выбор курса. История без active_course совместима
        и требует однократного выбора курса.
        """
        root = self.store.active_course
        if root is not None and root.is_dir():
            self.set_course(root)
        else:
            self.choose_course()

    def choose_course(self):
        """Показать выбор курса с добавлением, заменой пути и удалением из истории."""
        dialog = QDialog(self)
        dialog.setWindowTitle('Выберите курс')
        dialog.resize(600, 350)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        listing = QListWidget()
        listing.setFont(interface_font(monospace=True))
        listing.setItemDelegate(RowDelegate(listing))
        listing.addItems(list(self.store.data['courses']))
        if self.root is not None:
            matches = listing.findItems(str(self.root), Qt.MatchFlag.MatchExactly)
            if matches:
                listing.setCurrentItem(matches[0])
                listing.scrollToItem(matches[0])
        listing.setFocus()
        layout.addWidget(listing)
        def select():
            """Открыть выбранный доступный курс; для отсутствующей папки показать пояснение."""
            item = listing.currentItem()
            if item:
                path = Path(item.text())
                if path.is_dir():
                    self.set_course(path)
                    dialog.accept()
                else:
                    QMessageBox.information(dialog, 'Папка недоступна', 'Укажите новое расположение курса.')
        def add():
            """Запросить папку курса и открыть её после подтверждения выбора."""
            selected = QFileDialog.getExistingDirectory(dialog, 'Папка курса')
            if selected:
                self.set_course(Path(selected))
                dialog.accept()
        def relocate():
            """Заменить корень выбранного курса, сохранить историю и открыть новое расположение."""
            item = listing.currentItem()
            if not item:
                return
            selected = QFileDialog.getExistingDirectory(dialog, 'Новое расположение курса')
            if selected:
                try:
                    self.store.relocate(item.text(), Path(selected))
                except ValueError as error:
                    QMessageBox.warning(dialog, 'Перенос курса', str(error))
                    return
                self.persist()
                self.set_course(Path(selected))
                dialog.accept()
        def remove():
            """Удалить выбранную строку только после подтверждения и сохранения истории."""
            item = listing.currentItem()
            if item is not None and self.remove_course(item.text()):
                listing.takeItem(listing.row(item))
                remove_button.setEnabled(listing.currentItem() is not None)

        listing.itemDoubleClicked.connect(select)
        for label, callback in [('Открыть', select), ('Добавить папку', add), ('Указать новое расположение', relocate)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            layout.addWidget(button)
        remove_button = QPushButton('Удалить из списка')
        remove_button.setEnabled(listing.currentItem() is not None)
        remove_button.clicked.connect(remove)
        listing.currentItemChanged.connect(
            lambda current, previous: remove_button.setEnabled(current is not None))
        layout.addWidget(remove_button)
        dialog.exec()

    def confirm_course_removal(self, key: str) -> bool:
        """Запросить удаление данных курса с отменой по умолчанию и по Escape."""
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Удаление курса из списка')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(
            f'Удалить курс «{Path(key).name or key}» из списка?\n{key}\n\n'
            'История чтения, избранное и заметки этого курса будут удалены.\n'
            'Папка и файлы курса останутся на диске.')
        dialog.setIcon(QMessageBox.Icon.Warning)
        remove = dialog.addButton('Удалить', QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        try:
            dialog.exec()
            return dialog.clickedButton() is remove
        finally:
            dialog.deleteLater()

    def remove_course(self, key: str) -> bool:
        """Подтвердить и сохранить удаление записи; при ошибке вернуть состояние.

        Чтение другого курса продолжается. При удалении открытого курса
        очистить просмотрщик и панели, остановив отложенное обновление.
        Файлы материалов не удаляются и не изменяются.
        """
        if key not in self.store.data['courses'] or not self.confirm_course_removal(key):
            return False
        previous = deepcopy(self.store.data)
        if not self.store.remove_course(key):
            return False
        try:
            self.store.save()
        except OSError as error:
            self.store.data = previous
            QMessageBox.warning(self, 'Не удалось удалить курс из списка', str(error))
            return False
        if self.root is not None and str(self.root) == key:
            self.clear_course()
        return True

    def clear_course(self) -> None:
        """Очистить текущий курс и обезвредить callbacks, не создавая запись истории."""
        self.navigation_generation += 1
        self.loading = True
        self.restore_position = False
        self.root = None
        self.current = None
        self.page.pending_restore = None
        self.save_timer.stop()
        self.catalog_timer.stop()
        self.catalog_fallback.stop()
        watched = self.catalog_watcher.directories()
        if watched:
            self.catalog_watcher.removePaths(watched)
        self.view.stop()
        self.rebuild([])
        self.tree_search.clear()
        self.tree_search.hide()
        self.notes_search.clear()
        self.hide_find()
        self.notes_dock.hide()
        self.refresh_metadata()
        self.statusBar().clearMessage()
        self.view.setUrl(QUrl('about:blank'))

    def set_course(self, root):
        """Сделать курс активным, сохранить выбор и открыть существующий последний файл.

        Дерево перестраивается для нового корня. Если последнего файла нет,
        область чтения остаётся пустой; первая страница автоматически не выбирается.
        """
        self.persist()
        self.catalog_timer.stop()
        self.catalog_fallback.stop()
        self.current = None
        self.tree_search.clear()
        self.tree_search.hide()
        self.root = root.resolve()
        self.notes_search.clear()
        self.view.setUrl(QUrl('about:blank'))
        self.store.activate_course(self.root)
        self.persist()
        state = self.store.course(self.root)
        self.rebuild()
        last = self.root / state['last'] if state['last'] else None
        if last and last.is_file():
            self.open_file(last)
        else:
            self.refresh_metadata()
            self.statusBar().showMessage(str(self.root))

    def rebuild(self, files=None):
        """Перестроить дерево, сохранив раскрытие папок, выделение и прокрутку дерева.

        Саму страницу и панель заметок не перезагружать. Если список файлов
        уже получен наблюдателем, повторный обход не выполнять.
        """
        selected = self.tree.currentItem()
        selected_path = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
        expanded = {path for path, item in self.directory_items.items() if item.isExpanded()}
        vertical = self.tree.verticalScrollBar().value()
        horizontal = self.tree.horizontalScrollBar().value()
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            self.items = {}
            self.directory_items = {}
            if not self.root:
                self.files = []
                return
            if files is None:
                directories = []
                files = scan(self.root, self.store.patterns, directories=directories)
                self.sync_catalog_watches(directories)
            self.files = files
            folders = {'.': self.tree.invisibleRootItem()}
            for path in self.files:
                relative = path.relative_to(self.root)
                parent = folders['.']
                for index, name in enumerate(relative.parts[:-1]):
                    key = '/'.join(relative.parts[:index + 1])
                    if key not in folders:
                        folder = self.root.joinpath(*relative.parts[:index + 1])
                        node = QTreeWidgetItem(parent, [name])
                        node.setData(0, Qt.ItemDataRole.UserRole, str(folder))
                        node.setData(0, TREE_FOLDER_ROLE, True)
                        node.setToolTip(0, key)
                        folders[key] = node
                        self.directory_items[str(folder)] = node
                    parent = folders[key]
                label = f'[{path.suffix.lower()}] {path.name}' if path.suffix else path.name
                item = QTreeWidgetItem(parent, [label])
                item.setData(0, Qt.ItemDataRole.UserRole, str(path))
                if path.suffix:
                    item.setData(0, TREE_PREFIX_ROLE, f'[{path.suffix.lower()}]')
                item.setToolTip(0, relative.as_posix())
                self.items[str(path)] = item
            target = self.items.get(selected_path) or self.directory_items.get(selected_path)
            if target is None and self.current:
                target = self.items.get(str(self.current))
            if target is not None:
                self.tree.setCurrentItem(target)
            for path, item in self.directory_items.items():
                item.setExpanded(path in expanded)
            self.tree.verticalScrollBar().setValue(vertical)
            self.tree.horizontalScrollBar().setValue(horizontal)
        finally:
            self.filter_tree()
            self.tree.setUpdatesEnabled(True)
            self.update_focus_button()

    def update_focus_button(self) -> None:
        """Разрешить поиск текущей страницы только при наличии её строки в дереве."""
        self.focus_page_button.setEnabled(
            self.current is not None and str(self.current) in self.items)

    def focus_current_page(self) -> None:
        """Раскрыть путь к открытой странице и сфокусировать её строку без загрузки HTML."""
        item = self.items.get(str(self.current)) if self.current is not None else None
        if item is None:
            return
        self.tree_search.clear()
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self.tree.setFocus()

    def show_tree_search(self) -> None:
        """Показать строку поиска над деревом и передать ей фокус."""
        self.tree_search.show()
        self.tree_search.setFocus()

    def hide_tree_search(self) -> None:
        """Снять поисковый фильтр, закрыть строку и вернуть фокус дереву."""
        self.tree_search.clear()
        self.tree_search.hide()
        self.tree.setFocus()

    def filter_tree(self, _text: str = '') -> None:
        """Отфильтровать строки по относительному пути без изменения навигации.

        Раскрыть родителей совпадений. При очистке вернуть прежнее раскрытие
        папок и показать открытую страницу; HTML повторно не загружается.
        Повторное применение после обновления каталога сохраняет запрос.
        """
        query = self.tree_search.text().strip().replace('\\', '/').casefold()
        if query and self.tree_search_expanded is None:
            self.tree_search_expanded = {
                path for path, item in self.directory_items.items() if item.isExpanded()}
        visible_folders = set()
        matches = 0
        for path, item in self.items.items():
            relative = Path(path).relative_to(self.root).as_posix()
            matches_query = query in relative.casefold()
            item.setHidden(not matches_query)
            if matches_query:
                matches += 1
                parent = item.parent()
                while parent is not None:
                    visible_folders.add(parent.data(0, Qt.ItemDataRole.UserRole))
                    parent = parent.parent()
        for path, item in self.directory_items.items():
            item.setHidden(bool(query) and path not in visible_folders)
            if query and path in visible_folders:
                item.setExpanded(True)
        self.tree_search_empty.setVisible(bool(query) and matches == 0)
        if not query and self.tree_search_expanded is not None:
            for path, item in self.directory_items.items():
                item.setExpanded(path in self.tree_search_expanded)
            self.tree_search_expanded = None
            current = self.items.get(str(self.current))
            if current is not None:
                parent = current.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.setCurrentItem(current)
                self.tree.scrollToItem(current)

    def sync_catalog_watches(self, directories: list[Path]) -> None:
        """Обновить наблюдение, включая пустые папки; при отказах включить резервный опрос."""
        desired = {str(path) for path in directories}
        watched = set(self.catalog_watcher.directories())
        obsolete = sorted(watched - desired)
        if obsolete:
            self.catalog_watcher.removePaths(obsolete)
        missing = sorted(desired - watched)
        failed = self.catalog_watcher.addPaths(missing) if missing else []
        if failed or (self.root is not None and not self.root.is_dir()):
            self.catalog_fallback.start()
        else:
            self.catalog_fallback.stop()

    def schedule_catalog_refresh(self, changed_path: str) -> None:
        """Объединить близкие файловые события без бесконечного откладывания при копировании."""
        if not self.closing and self.root and not self.catalog_timer.isActive():
            self.catalog_timer.start()

    def refresh_catalog(self) -> None:
        """Обновить файлы и наблюдателей, не меняя открытый материал и заметки."""
        if self.closing or not self.root:
            return
        directories = []
        files = scan(self.root, self.store.patterns, directories=directories)
        self.sync_catalog_watches(directories)
        if files != self.files:
            self.rebuild(files)

    def tree_context_menu(self, position) -> None:
        """Показать действие для элемента под указателем без открытия страницы."""
        item = self.tree.itemAt(position)
        if item is None:
            return
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if not value:
            return
        path = Path(value)
        menu = QMenu(self)
        show = menu.addAction('Показать в проводнике')
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen == show:
            self.show_in_explorer(path)

    def show_in_explorer(self, path: Path) -> None:
        """Открыть Проводник для объекта курса; сообщить об исчезновении файла или ошибке запуска."""
        if not self.root or not path.resolve().is_relative_to(self.root):
            return
        try:
            subprocess.Popen(explorer_arguments(path), shell=False)
        except OSError as error:
            QMessageBox.warning(self, 'Проводник', str(error))

    def tree_clicked(self, item, column):
        """Открыть файл выбранного элемента; щелчок по папке не загружает страницу."""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and str(path) in self.items:
            self.open_file(Path(path))

    def open_file(self, path):
        """Открыть существующий файл внутри корня курса либо предложить внешнее приложение.

        Расширения PAGE_SUFFIXES передаются WebEngine; недоступный путь вызывает диалог."""
        path = path.resolve()
        if not self.root or not path.is_relative_to(self.root) or not path.is_file():
            QMessageBox.warning(self, 'Файл недоступен', str(path))
            return
        if path.suffix.lower() not in PAGE_SUFFIXES:
            self.external_file(path)
            return
        self.page.open_saved(QUrl.fromLocalFile(str(path)))

    def local_link(self, filename, restore_position=False):
        """Учесть принятый локальный переход: сохранить страницу, обновить панели и состояние загрузки."""
        path = Path(filename).resolve()
        if self.root and path.is_relative_to(self.root) and path.is_file():
            if path.suffix.lower() in PAGE_SUFFIXES:
                self.navigation_generation += 1
                self.restore_position = restore_position
                self.loading = True
                self.current = path
                self.store.course(self.root)['last'] = path.relative_to(self.root).as_posix()
                self.refresh_metadata()
                self.persist()

    def allow_local(self, filename):
        """Проверить существование файла внутри курса и пригодность для WebEngine.

        Для прочих расширений предложить внешнее открытие и вернуть False."""
        path = Path(filename).resolve()
        if not self.root or not path.is_relative_to(self.root) or not path.is_file():
            return False
        if path.suffix.lower() not in PAGE_SUFFIXES:
            self.external_file(path)
            return False
        return True

    def load_started(self):
        """Приостановить запись прокрутки на время загрузки страницы."""
        self.loading = True

    def loaded(self, success):
        """Восстановить место HTML/HTM только при открытии из интерфейса, не при переходе по ссылке.

        В MHTML/MHT JavaScript восстановления не выполняется из-за ограничений
        движка; якорь и прокрутку переходов по ссылкам обрабатывает WebEngine."""
        if self.closing or not self.current:
            return
        if not success:
            self.statusBar().showMessage('Не удалось отобразить: ' + str(self.current))
            return
        if Path(self.view.url().toLocalFile()).resolve() != self.current:
            return
        generation = self.navigation_generation
        def restored(result):
            """Разрешить запись прокрутки, только если за время callback не началась другая навигация."""
            if not self.closing and generation == self.navigation_generation:
                self.loading = False
        relative = self.current.relative_to(self.root).as_posix()
        position = self.store.course(self.root)['scroll'].get(relative, 0)
        if (self.restore_position and not self.view.url().hasFragment()
                and self.current.suffix.lower() not in ('.mhtml', '.mht')):
            self.page.runJavaScript(f'window.scrollTo(0, {float(position)});', restored)
        else:
            restored(None)

    def report_loading(self, information):
        """Вывести адрес, статус и ошибку конкретной загрузки для диагностики отменённых переходов."""
        if not self.closing:
            print(f'WEB {information.status().name}: {information.url().toString()} '
                  f'[{information.errorDomain().name}:{information.errorCode()}] '
                  f'{information.errorString()}', flush=True)

    def scroll_changed(self, position):
        """Запомнить вертикальную прокрутку загруженной страницы и отложить сохранение на 700 мс."""
        if self.current and self.root and not self.loading:
            relative = self.current.relative_to(self.root).as_posix()
            self.store.course(self.root)['scroll'][relative] = position.y()
            self.save_timer.start(700)

    def external_file(self, path):
        """После подтверждения передать файл приложению Windows по умолчанию; сообщить об ошибке."""
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Внешний файл')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText('Открыть файл в приложении по умолчанию Windows?\n' + str(path))
        dialog.setIcon(QMessageBox.Icon.Question)
        open_button = dialog.addButton('Открыть', QMessageBox.ButtonRole.AcceptRole)
        cancel_button = dialog.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                QMessageBox.warning(self, 'Ошибка открытия', 'Windows не удалось открыть файл.')

    def internet_link(self, address):
        """При разрешающей настройке запросить подтверждение открытия адреса во внешнем браузере."""
        if self.store.settings.getboolean('app', 'internet_links', fallback=False):
            if QMessageBox.question(self, 'Ссылка в интернет', 'Открыть в браузере?\n' + address) == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(address))

    def move(self, step):
        """Открыть соседнюю видимую страницу с шагом -1 или 1; на границе показать сообщение."""
        pages = [p for p in self.files if p.suffix.lower() in PAGE_SUFFIXES]
        target = adjacent(pages, self.current, step)
        if target:
            self.open_file(target)
        else:
            QMessageBox.information(self, 'Навигация', 'Больше страниц в этом направлении нет.')

    def refresh_metadata(self):
        """Обновить избранное, заметки, строку пути и выделение текущего файла в дереве."""
        self.update_focus_button()
        self.favorites.clear()
        self.refresh_notes()
        self.favorite_action.setChecked(False)
        self.favorite_action.setEnabled(self.current is not None)
        if not self.root:
            return
        state = self.store.course(self.root)
        for relative in state['favorites']:
            self.favorites.addItem(relative)
            self.favorites.item(self.favorites.count() - 1).setData(Qt.ItemDataRole.UserRole, relative)
            self.favorites.item(self.favorites.count() - 1).setToolTip(relative)
        if not self.current:
            return
        relative = self.current.relative_to(self.root).as_posix()
        self.statusBar().showMessage(self.root.name + '/' + relative)
        item = self.items.get(str(self.current))
        if item:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        self.favorite_action.setChecked(relative in state['favorites'])

    def toggle_favorite(self):
        """Переключить избранное текущей страницы и сохранить обновлённые данные."""
        if self.current:
            self.store.toggle_favorite(self.root, self.current.relative_to(self.root).as_posix())
            self.persist()
            self.refresh_metadata()

    def refresh_notes(self) -> None:
        """Показать совпавшие по тексту заметки, сохранив группировку и общий счётчик.

        Выбор сохраняется только для заметки, оставшейся в результатах.
        Фильтрация не изменяет записи и их привязки к страницам курса.
        """
        selected = self.notes_list.currentItem()
        selected_key = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        selected_key = tuple(selected_key) if selected_key else None
        self.notes_list.clear()
        query = self.notes_search.text().strip().casefold()
        self.notes_hint.setText('Ничего не найдено' if query else
                                'Заметок пока нет. Добавьте первую заметку к открытой странице.')
        count = 0
        if self.root:
            groups = self.store.course(self.root)['notes']
            for relative in sorted(groups, key=natural_key):
                count += len(groups[relative])
                notes = [note for note in groups[relative] if query in note['text'].casefold()]
                if not notes:
                    continue
                heading = QListWidgetItem(f'{relative} ({len(notes)})')
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                font = heading.font()
                font.setBold(True)
                heading.setFont(font)
                heading.setToolTip(relative)
                self.notes_list.addItem(heading)
                for note in notes:
                    item = QListWidgetItem(note['text'] + '\nИзменено: ' + format_note_time(note['updated']))
                    key = (str(self.root), relative, note['id'])
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    item.setToolTip(relative)
                    self.notes_list.addItem(item)
                    if key == selected_key:
                        self.notes_list.setCurrentItem(item)
        self.notes_action.setText(f'Заметки ({count})')
        self.update_note_actions()

    def update_note_actions(self) -> None:
        """Разрешить добавление к открытой странице и действия с выбранной заметкой."""
        can_add = self.root is not None and self.current is not None
        self.note_buttons['Добавить'].setEnabled(can_add)
        target = ('Открытая страница: ' + self.current.relative_to(self.root).as_posix()
                  if can_add else 'Нет открытой страницы')
        self.note_target.setText(target)
        self.note_target.setToolTip(target)
        selected = self.selected_note() is not None
        for label in ('Открыть страницу', 'Изменить', 'Удалить'):
            self.note_buttons[label].setEnabled(selected)

    def show_notes(self):
        """Открыть панель без выбранной заметки либо скрыть уже открытую панель."""
        opening = not self.notes_dock.isVisible()
        self.notes_dock.setVisible(opening)
        if opening:
            self.notes_list.clearSelection()
            self.notes_list.setCurrentRow(-1)
            self.notes_list.clearFocus()
            self.update_note_actions()
            if self.current is not None:
                self.note_buttons['Добавить'].setFocus()

    def note_text_dialog(self, relative: str, text: str = '', *, editing: bool = False) -> tuple[str, bool]:
        """Запросить многострочную заметку с русскими кнопками и штатной отменой по Esc."""
        dialog = QInputDialog(self)
        dialog.setWindowTitle('Изменить заметку' if editing else 'Заметка')
        dialog.setInputMode(QInputDialog.InputMode.TextInput)
        dialog.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput, True)
        dialog.setLabelText(f'Страница: {relative}\nТекст:')
        dialog.setTextValue(text)
        dialog.setOkButtonText('Сохранить' if editing else 'Добавить')
        dialog.setCancelButtonText('Отмена')
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.textValue(), accepted

    def add_note(self):
        """Добавить заметку к открытой странице независимо от выделения в дереве."""
        if not self.root or not self.current:
            return
        root = self.root
        relative = self.current.relative_to(root).as_posix()
        text, ok = self.note_text_dialog(relative)
        if ok and text.strip():
            self.store.add_note(root, relative, text)
            self.persist()
            self.refresh_notes()

    def selected_note(self) -> tuple[str, dict] | None:
        """Вернуть путь и запись выбранной заметки; заголовок или устаревший выбор дают None."""
        item = self.notes_list.currentItem()
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not self.root or not key or key[0] != str(self.root):
            return None
        _, relative, identifier = key
        for note in self.store.course(self.root)['notes'].get(relative, []):
            if note['id'] == identifier:
                return relative, note
        return None

    def open_note_page(self) -> None:
        """Открыть страницу выбранной заметки через обычную проверку доступности файла."""
        selected = self.selected_note()
        if selected:
            relative, _ = selected
            self.open_file(self.root / relative)

    def edit_note(self):
        """Изменить выбранную заметку на её странице, даже если отображается другой файл."""
        selected = self.selected_note()
        if selected:
            root = self.root
            relative, note = selected
            text, ok = self.note_text_dialog(relative, note['text'], editing=True)
            if ok and text.strip():
                self.store.edit_note(root, relative, note['id'], text)
                self.persist()
                self.refresh_notes()

    def confirm_note_deletion(self, relative: str) -> bool:
        """Запросить удаление русскими кнопками; закрытие окна и Escape отменяют действие."""
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Удаление заметки')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f'Удалить выбранную заметку?\n{relative}')
        dialog.setIcon(QMessageBox.Icon.Question)
        remove = dialog.addButton('Удалить', QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        return dialog.clickedButton() is remove

    def delete_note(self):
        """Удалить выбранную заметку после подтверждения, сохранив остальные страницы."""
        selected = self.selected_note()
        if selected:
            root = self.root
            relative, note = selected
            if self.confirm_note_deletion(relative):
                self.store.delete_note(root, relative, note['id'])
                self.persist()
                self.refresh_notes()

    def page_context_menu(self, position) -> None:
        """Показать русское меню чтения с навигацией по файлам курса.

        Копирование и выделение выполняет WebEngine; переходы используют
        те же правила и сообщения о границах, что и кнопки панели.
        """
        menu = QMenu(self)
        try:
            previous = menu.addAction('Предыдущая страница')
            following = menu.addAction('Следующая страница')
            previous.setEnabled(self.root is not None)
            following.setEnabled(self.root is not None)
            menu.addSeparator()
            copy = menu.addAction('Копировать')
            copy.setEnabled(self.page.hasSelection())
            select_all = menu.addAction('Выделить всё')
            select_all.setEnabled(self.current is not None)
            menu.addSeparator()
            find = menu.addAction('Найти на странице')
            find.setEnabled(self.current is not None)
            selected = menu.exec(self.view.mapToGlobal(position))
            if selected is previous:
                self.move(-1)
            elif selected is following:
                self.move(1)
            elif selected is copy:
                self.page.triggerAction(QWebEnginePage.WebAction.Copy)
            elif selected is select_all:
                self.page.triggerAction(QWebEnginePage.WebAction.SelectAll)
            elif selected is find:
                self.show_find()
        finally:
            menu.deleteLater()

    def show_find(self):
        """Показать поиск по странице и передать фокус строке запроса."""
        self.find_bar.show()
        self.find_input.setFocus()

    def hide_find(self):
        """Снять подсветку поиска, скрыть строку запроса и вернуть фокус на страницу."""
        self.view.findText('')
        self.find_bar.hide()
        self.view.setFocus()

    def zoom(self, delta):
        """Изменить масштаб страницы на delta в пределах 0.25–3.0 и сохранить значение."""
        factor = round(max(0.25, min(3.0, self.view.zoomFactor() + delta)), 2)
        self.view.setZoomFactor(factor)
        self.zoom_label.setText(f'{factor:.0%}')
        self.store.settings['app']['zoom'] = str(factor)
        self.persist()

    def apply_remote_resources(self) -> None:
        """Применить выбор ресурсов одновременно к фильтру запросов и WebEngine.

        Действует для последующих запросов; уже загруженное содержимое остаётся.
        Открытие интернет-ссылок в браузере управляется отдельной настройкой.
        """
        values = self.store.settings['remote_resources']
        flags = {key: values.getboolean(key) for key in ('enabled', 'images', 'styles', 'fonts')}
        self.interceptor.configure(**flags)
        self.page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            flags['enabled'] and any(flags[key] for key in ('images', 'styles', 'fonts')))

    def settings_dialog(self):
        """Показать настройки; после подтверждения сохранить маски, интернет-переходы и тему."""
        dialog = QDialog(self)
        dialog.setWindowTitle('Настройки')
        dialog.setMinimumWidth(520)
        layout = QFormLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        group_fields = {}
        for group, label in [('pages', 'Страницы'), ('video', 'Видео'), ('other', 'Другие файлы')]:
            values = self.store.settings['files.' + group]
            enabled = QCheckBox('Показывать')
            style_checkbox(enabled, self.store.settings['app']['theme'])
            enabled.setChecked(values.getboolean('enabled'))
            masks = QLineEdit(values['patterns'])
            masks.setAccessibleName('Маски: ' + label)
            enabled.setAccessibleName('Показывать: ' + label)
            masks.setToolTip('Маски через запятую. Отключение группы сохраняет этот список.')
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(enabled)
            row_layout.addWidget(masks, 1)
            layout.addRow(label, row)
            group_fields[group] = (enabled, masks)
        internet = QCheckBox('Разрешать после подтверждения')
        style_checkbox(internet, self.store.settings['app']['theme'])
        internet.setChecked(self.store.settings.getboolean('app', 'internet_links', fallback=False))
        theme = QComboBox()
        theme.addItem('Графитовая', 'dark')
        theme.addItem('Светлая', 'light')
        theme.setCurrentIndex(1 if self.store.settings['app']['theme'] == 'light' else 0)
        layout.addRow('Переход по интернет-ссылкам', internet)
        layout.addRow('Тема интерфейса', theme)
        resources = RemoteResourcesSettings(self.store.settings['remote_resources'],
                                             self.store.settings['app']['theme'], dialog)
        layout.addRow(resources)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Применить')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            for group, (enabled, masks) in group_fields.items():
                self.store.settings['files.' + group].update(
                    {'enabled': str(enabled.isChecked()).lower(), 'patterns': masks.text()})
            self.store.settings['app'].update({'internet_links': str(internet.isChecked()).lower(), 'theme': theme.currentData()})
            self.store.settings['remote_resources'].update(resources.values())
            self.apply_remote_resources()
            self.persist()
            self.apply_theme()
            self.rebuild()

    def apply_theme(self):
        """Применить светлую или графитовую палитру к виджетам, не меняя HTML страницы."""
        name = self.store.settings['app']['theme']
        self.setStyleSheet(stylesheet(name))
        previous_style = getattr(self, '_notes_title_style', None)
        self._notes_title_style = DockTitleStyle(name, self.notes_dock)
        self.notes_dock.setStyle(self._notes_title_style)
        if previous_style is not None:
            previous_style.deleteLater()
        for action, icon_name in self.icon_actions:
            action.setIcon(icon(icon_name, name))
        for listing in (self.tree, self.favorites, self.notes_list):
            listing.setProperty('focusColor', PALETTES[name]['accent'])
            listing.viewport().update()

    def closeEvent(self, event):
        """Сохранить данные и уничтожить просмотрщик со страницей раньше профиля."""
        if self.closing:
            event.accept()
            return
        self.closing = True
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self.navigation_generation += 1
        self.loading = True
        self.save_timer.stop()
        self.catalog_timer.stop()
        self.catalog_fallback.stop()
        self.catalog_watcher.blockSignals(True)
        self.persist()
        self.view.stop()
        delete(self.view)
        delete(self.profile)
        event.accept()
