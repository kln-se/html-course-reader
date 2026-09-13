"""Интерфейс чтения, выбора курсов и работы с заметками."""
from pathlib import Path
from shiboken6 import delete
from PySide6.QtCore import Qt, QUrl, QTimer, QSize, Slot
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QTreeWidget, QTreeWidgetItem, QListWidget,
    QTabWidget, QSplitter, QToolBar, QMessageBox, QFileDialog, QDialog, QVBoxLayout,
    QPushButton, QInputDialog, QDockWidget, QWidget, QLineEdit, QCheckBox, QComboBox,
    QDialogButtonBox, QFormLayout, QLabel)
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from .catalog import scan, PAGE_SUFFIXES, adjacent
from .viewer import Page, OfflineInterceptor
from .storage import Store
from .theme import EmptyHint, PALETTES, RowDelegate, icon, interface_font, stylesheet


class Window(QMainWindow):
    """Связывать каталог, просмотрщик и состояние выбранного курса в главном окне."""
    def __init__(self, store: Store):
        """Создать панели, обработчики и профиль WebEngine, применить настройки переданного Store."""
        super().__init__()
        self.setFont(interface_font())
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
        self.favorites = QListWidget()
        self.favorites.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.favorites.setAccessibleName('Избранные страницы курса')
        self.favorites.itemClicked.connect(lambda item: self.open_file(self.root / item.data(Qt.ItemDataRole.UserRole)))
        tabs = QTabWidget()
        tabs.addTab(self.tree, 'Файлы')
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
        self.notes_dock = QDockWidget('Заметки к странице', self)
        panel = QWidget()
        panel.setObjectName('sidebar')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.notes_list = QListWidget()
        self.notes_list.setWordWrap(True)
        self.notes_list.setAccessibleName('Заметки текущей страницы')
        layout.addWidget(self.notes_list)
        for label, callback in [('Добавить', self.add_note), ('Изменить', self.edit_note), ('Удалить', self.delete_note)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
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
        self.hints = [
            EmptyHint(self.tree, 'Выберите курс кнопкой «Курсы». Если файлы скрыты, проверьте маски в настройках.'),
            EmptyHint(self.favorites, 'Важные страницы будут здесь. Нажмите «Избранное» при чтении.'),
            EmptyHint(self.notes_list, 'Заметок пока нет. Добавьте первую заметку к открытой странице.'),
        ]
        for listing in (self.tree, self.favorites, self.notes_list):
            listing.setItemDelegate(RowDelegate(listing))
            listing.setMouseTracking(True)
        self.status_bar = self.statusBar()
        self.status_bar.setFont(interface_font(monospace=True))
        self.status_bar.messageChanged.connect(self.update_status_tooltip)
        self.apply_theme()
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.persist)

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

    def choose_course(self):
        """Показать модальный выбор курса с добавлением папки и заменой корневого пути."""
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
        listing.itemDoubleClicked.connect(select)
        for label, callback in [('Открыть', select), ('Добавить папку', add), ('Указать новое расположение', relocate)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            layout.addWidget(button)
        dialog.exec()

    def set_course(self, root):
        """Сменить корень курса, перестроить дерево и открыть существующий последний файл."""
        self.persist()
        self.current = None
        self.root = root.resolve()
        self.view.setUrl(QUrl('about:blank'))
        state = self.store.course(self.root)
        self.rebuild()
        last = self.root / state['last'] if state['last'] else None
        if last and last.is_file():
            self.open_file(last)
        else:
            self.refresh_metadata()
            self.statusBar().showMessage(str(self.root))

    def rebuild(self):
        """Пересканировать курс по маскам и построить дерево только для найденных файлов."""
        self.tree.clear()
        self.items = {}
        if not self.root:
            return
        self.files = scan(self.root, self.store.patterns)
        folders = {'.': self.tree.invisibleRootItem()}
        for path in self.files:
            relative = path.relative_to(self.root)
            parent = folders['.']
            for index, name in enumerate(relative.parts[:-1]):
                key = '/'.join(relative.parts[:index + 1])
                if key not in folders:
                    folders[key] = QTreeWidgetItem(parent, [name])
                parent = folders[key]
            item = QTreeWidgetItem(parent, [path.name])
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(0, relative.as_posix())
            self.items[str(path)] = item
        self.refresh_metadata()

    def tree_clicked(self, item, column):
        """Открыть файл выбранного элемента; щелчок по папке не загружает страницу."""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
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
        if QMessageBox.question(self, 'Внешний файл', 'Открыть файл в приложении по умолчанию Windows?\n' + str(path)) == QMessageBox.StandardButton.Yes:
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
        self.favorites.clear()
        self.notes_list.clear()
        self.favorite_action.setChecked(False)
        self.favorite_action.setEnabled(self.current is not None)
        self.notes_action.setText('Заметки (0)')
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
        notes = state['notes'].get(relative, [])
        self.notes_action.setText(f'Заметки ({len(notes)})')
        for note in notes:
            self.notes_list.addItem(note['text'] + '\n' + note['updated'])

    def toggle_favorite(self):
        """Переключить избранное текущей страницы и сохранить обновлённые данные."""
        if self.current:
            self.store.toggle_favorite(self.root, self.current.relative_to(self.root).as_posix())
            self.persist()
            self.refresh_metadata()

    def show_notes(self):
        """Переключить видимость панели заметок текущей страницы."""
        self.notes_dock.setVisible(not self.notes_dock.isVisible())

    def add_note(self):
        """Запросить непустой текст новой заметки текущей страницы и сохранить её."""
        if not self.current:
            return
        text, ok = QInputDialog.getMultiLineText(self, 'Заметка', 'Текст:')
        if ok and text.strip():
            self.store.add_note(self.root, self.current.relative_to(self.root).as_posix(), text)
            self.persist()
            self.refresh_metadata()

    def selected_note(self):
        """Вернуть выбранную запись заметки текущей страницы либо None при отсутствии выбора."""
        index = self.notes_list.currentRow()
        if not self.current or index < 0:
            return None
        return self.store.course(self.root)['notes'][self.current.relative_to(self.root).as_posix()][index]

    def edit_note(self):
        """Запросить новый непустой текст выбранной заметки и сохранить изменение."""
        note = self.selected_note()
        if note:
            text, ok = QInputDialog.getMultiLineText(self, 'Изменить заметку', 'Текст:', note['text'])
            if ok and text.strip():
                self.store.edit_note(self.root, self.current.relative_to(self.root).as_posix(), note['id'], text)
                self.persist()
                self.refresh_metadata()

    def delete_note(self):
        """После подтверждения удалить выбранную заметку и обновить панели."""
        note = self.selected_note()
        if note and QMessageBox.question(self, 'Удаление', 'Удалить выбранную заметку?') == QMessageBox.StandardButton.Yes:
            self.store.delete_note(self.root, self.current.relative_to(self.root).as_posix(), note['id'])
            self.persist()
            self.refresh_metadata()

    def show_find(self):
        """Показать поиск по странице и передать фокус строке запроса."""
        self.find_bar.show()
        self.find_input.setFocus()

    def hide_find(self):
        """Снять выделение результатов поиска и скрыть строку запроса."""
        self.view.findText('')
        self.find_bar.hide()

    def zoom(self, delta):
        """Изменить масштаб страницы на delta в пределах 0.25–3.0 и сохранить значение."""
        factor = round(max(0.25, min(3.0, self.view.zoomFactor() + delta)), 2)
        self.view.setZoomFactor(factor)
        self.zoom_label.setText(f'{factor:.0%}')
        self.store.settings['app']['zoom'] = str(factor)
        self.persist()

    def settings_dialog(self):
        """Показать настройки; после подтверждения сохранить маски, интернет-переходы и тему."""
        dialog = QDialog(self)
        dialog.setWindowTitle('Настройки')
        dialog.setMinimumWidth(520)
        layout = QFormLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        patterns = QLineEdit(self.store.settings['app']['visible_patterns'])
        internet = QCheckBox('Разрешать после подтверждения')
        internet.setChecked(self.store.settings.getboolean('app', 'internet_links', fallback=False))
        theme = QComboBox()
        theme.addItem('Графитовая', 'dark')
        theme.addItem('Светлая', 'light')
        theme.setCurrentIndex(1 if self.store.settings['app']['theme'] == 'light' else 0)
        layout.addRow('Маски через запятую', patterns)
        layout.addRow('Интернет-ссылки', internet)
        layout.addRow('Тема интерфейса', theme)
        layout.addRow(QLabel('Сетевые запросы самих страниц заблокированы.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.store.settings['app'].update({'visible_patterns': patterns.text(), 'internet_links': str(internet.isChecked()).lower(), 'theme': theme.currentData()})
            self.persist()
            self.apply_theme()
            self.rebuild()

    def apply_theme(self):
        """Применить светлую или графитовую палитру к виджетам, не меняя HTML страницы."""
        name = self.store.settings['app']['theme']
        self.setStyleSheet(stylesheet(name))
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
        self.navigation_generation += 1
        self.loading = True
        self.save_timer.stop()
        self.persist()
        self.view.stop()
        delete(self.view)
        delete(self.profile)
        event.accept()
