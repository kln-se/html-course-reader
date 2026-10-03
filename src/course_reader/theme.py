"""Единая типографика, палитры и векторные пиктограммы интерфейса читалки."""
from PySide6.QtCore import QByteArray, QEvent, QRect, QSize, Qt, QPointF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QFontMetrics, QPalette, QTextLayout, QTextCharFormat
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QProxyStyle, QRadioButton, QCheckBox, QStyleFactory, QLabel, QStyle, QStyledItemDelegate, QStyleOptionViewItem

PALETTES = {
    'dark': dict(bg='#20242B', panel='#282D36', text='#E6E9EF', muted='#AFB9C9',
                 border='#424B59', hover='#343C49', selected='#354D68', accent='#8AB4F8'),
    'light': dict(bg='#F3F5F8', panel='#FFFFFF', text='#243246', muted='#56657A',
                  border='#CED5DF', hover='#E7EDF5', selected='#DCEAFE', accent='#245FAB'),
}

PATHS = {
    'courses': '<path d="M4 5h6l2 2h8v12H4z"/>',
    'back': '<path d="m14 5-7 7 7 7"/>',
    'next': '<path d="m10 5 7 7-7 7"/>',
    'bookmark': '<path d="M6 4h12v17l-6-4-6 4z"/>',
    'notes': '<path d="M5 4h14v13l-4 4H5zM8 8h8M8 12h8M8 16h4"/>',
    'search': '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    'minus': '<path d="M5 12h14"/>',
    'plus': '<path d="M5 12h14M12 5v14"/>',
    'settings': '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    'collapse': '<path d="m4 6 6 6-6 6M20 6l-6 6 6 6"/>',
    'locate': '<circle cx="12" cy="12" r="7"/><path d="M12 2v20M2 12h20"/>',
    'expand': '<path d="m10 6-6 6 6 6M14 6l6 6-6 6"/>',
    'warning': '<path d="m12 3 10 18H2zM12 9v5M12 17v1"/>',
    'undock': '<path d="M8 4h12v12H8zM4 8v12h12"/>',
    'close': '<path d="m6 6 12 12M18 6 6 18"/>',
}


def style_checkbox(checkbox: QCheckBox | QRadioButton, theme: str) -> None:
    """Оформить индикатор по теме приложения независимо от темы Windows.

    Отдельный стиль Fusion принадлежит чекбоксу и уничтожается вместе с ним.
    Фон и цвет галочки задаются явно для активного и неактивного окна.
    """
    colors = PALETTES.get(theme, PALETTES['dark'])
    style = QStyleFactory.create('Fusion')
    style.setParent(checkbox)
    checkbox.setStyle(style)
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, colors['bg']),
        (QPalette.ColorRole.Base, colors['panel']),
        (QPalette.ColorRole.Button, colors['panel']),
        (QPalette.ColorRole.Text, colors['text']),
        (QPalette.ColorRole.WindowText, colors['text']),
        (QPalette.ColorRole.ButtonText, colors['text']),
        (QPalette.ColorRole.Highlight, colors['accent']),
        (QPalette.ColorRole.HighlightedText, colors['panel']),
    ):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(colors['muted']))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(colors['muted']))
    checkbox.setPalette(palette)


def interface_font(monospace: bool = False) -> QFont:
    """Выбрать установленную гарнитуру с запасными вариантами без загрузки шрифтов."""
    candidates = ('Cascadia Mono', 'Consolas') if monospace else ('Segoe UI Variable Text', 'Segoe UI')
    installed = set(QFontDatabase.families())
    fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont if monospace else QFontDatabase.SystemFont.GeneralFont)
    font = QFont(next((name for name in candidates if name in installed), fallback.family()))
    font.setPointSizeF(9.5 if monospace else 10.5)
    return font


def icon(name: str, theme: str) -> QIcon:
    """Нарисовать пиктограмму в нескольких разрешениях для обычного, выбранного и недоступного состояния."""
    colors = PALETTES.get(theme, PALETTES['dark'])
    result = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Disabled):
        for state in (QIcon.State.Off, QIcon.State.On):
            color = colors['muted'] if mode == QIcon.Mode.Disabled else colors['accent'] if state == QIcon.State.On else colors['text']
            fill = color if name == 'bookmark' and state == QIcon.State.On else 'none'
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
            renderer = QSvgRenderer(QByteArray(svg.encode()))
            for scale in (1, 2, 3):
                pixmap = QPixmap(20 * scale, 20 * scale)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                pixmap.setDevicePixelRatio(scale)
                result.addPixmap(pixmap, mode, state)
    return result


class DockTitleStyle(QProxyStyle):
    """Подставлять тематические значки штатных кнопок заголовка панели."""

    def __init__(self, theme: str, parent):
        """Создать отдельный базовый стиль, принадлежащий панели."""
        super().__init__('Fusion')
        self.theme = theme
        self.setParent(parent)

    def standardIcon(self, standard_icon, option=None, widget=None):
        """Заменить значки закрытия и отделения, сохранив остальные значки Qt."""
        if standard_icon in (QStyle.StandardPixmap.SP_TitleBarCloseButton,
                             QStyle.StandardPixmap.SP_DockWidgetCloseButton):
            return icon('close', self.theme)
        if standard_icon == QStyle.StandardPixmap.SP_TitleBarNormalButton:
            return icon('undock', self.theme)
        return super().standardIcon(standard_icon, option, widget)


class RowDelegate(QStyledItemDelegate):
    """Рисовать строки без системной рамки, сохраняя отдельный индикатор фокуса."""
    def paint(self, painter, option, index):
        """Заменить рамку фокуса тонкой полосой у края выбранной строки."""
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)
        if focused:
            painter.save()
            painter.fillRect(QRect(option.rect.left(), option.rect.top() + 5, 3, option.rect.height() - 10),
                             QColor(self.parent().property('focusColor') or '#8AB4F8'))
            painter.restore()

    def sizeHint(self, option, index):
        """Сохранить ширину содержимого и обеспечить удобную высоту строки."""
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 32))


TREE_PREFIX_ROLE = int(Qt.ItemDataRole.UserRole) + 1
TREE_FOLDER_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class TreeRowDelegate(RowDelegate):
    """Выделять папки Bold, префиксы Semibold, сохраняя обычное начертание имён файлов."""

    def initStyleOption(self, option, index):
        """Применить начертание строки; служебные роли не меняют путь и доступное имя."""
        super().initStyleOption(option, index)
        option.font.setWeight(QFont.Weight.Bold if index.data(TREE_FOLDER_ROLE) else QFont.Weight.Normal)
        option.fontMetrics = QFontMetrics(option.font)

    def sizeHint(self, option, index):
        """Учесть дополнительную ширину полужирного префикса при расчёте строки."""
        size = super().sizeHint(option, index)
        prefix = index.data(TREE_PREFIX_ROLE)
        if prefix:
            styled = QStyleOptionViewItem(option)
            self.initStyleOption(styled, index)
            prefix_font = QFont(styled.font)
            prefix_font.setWeight(QFont.Weight.DemiBold)
            extra = QFontMetrics(prefix_font).horizontalAdvance(prefix) - styled.fontMetrics.horizontalAdvance(prefix)
            size.setWidth(size.width() + max(0, extra))
        return size

    def paint(self, painter, option, index):
        """Рисовать фон штатным стилем, а префикс и сокращённое имя — разными начертаниями."""
        prefix = index.data(TREE_PREFIX_ROLE)
        if not prefix:
            super().paint(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        style = styled.widget.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, styled, styled.widget)
        focused = bool(styled.state & QStyle.StateFlag.State_HasFocus)
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        prefix_font = QFont(styled.font)
        prefix_font.setWeight(QFont.Weight.DemiBold)
        prefix_width = QFontMetrics(prefix_font).horizontalAdvance(prefix + ' ')
        name = styled.text[len(prefix) + 1:]
        name = styled.fontMetrics.elidedText(name, Qt.TextElideMode.ElideMiddle,
                                           max(0, text_rect.width() - prefix_width))
        text = prefix + ' ' + name
        styled.text = ''
        painter.save()
        try:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
            painter.setClipRect(text_rect)
            group = QPalette.ColorGroup.Normal if styled.state & QStyle.StateFlag.State_Enabled else QPalette.ColorGroup.Disabled
            role = QPalette.ColorRole.HighlightedText if styled.state & QStyle.StateFlag.State_Selected else QPalette.ColorRole.Text
            painter.setPen(styled.palette.color(group, role))
            layout = QTextLayout(text, styled.font)
            emphasis = QTextLayout.FormatRange()
            emphasis.start = 0
            emphasis.length = len(prefix)
            emphasis.format = QTextCharFormat()
            emphasis.format.setFontWeight(QFont.Weight.DemiBold)
            layout.setFormats([emphasis])
            layout.beginLayout()
            line = layout.createLine()
            line.setLineWidth(max(1, text_rect.width()))
            layout.endLayout()
            layout.draw(painter, QPointF(text_rect.left(), text_rect.top() + (text_rect.height() - line.height()) / 2))
        finally:
            painter.restore()
        if focused:
            painter.fillRect(QRect(option.rect.left(), option.rect.top() + 5, 3, option.rect.height() - 10),
                             QColor(self.parent().property('focusColor') or '#8AB4F8'))


class EmptyHint(QLabel):
    """Показывать пояснение над пустым списком, не создавая фиктивных элементов."""
    def __init__(self, view, text: str):
        """Связать подсказку с размером области просмотра и изменениями модели."""
        super().__init__(text, view.viewport())
        self.setObjectName('emptyHint')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.view = view
        view.viewport().installEventFilter(self)
        for signal in (view.model().rowsInserted, view.model().rowsRemoved, view.model().modelReset):
            signal.connect(self.update_hint)
        self.update_hint()

    def update_hint(self, *args):
        """Согласовать положение и видимость подсказки с текущим содержимым."""
        self.setGeometry(self.view.viewport().rect().adjusted(20, 12, -20, -12))
        self.setVisible(self.view.model().rowCount() == 0)

    def eventFilter(self, watched, event):
        """Обновить геометрию при изменении размера области просмотра."""
        if event.type() == QEvent.Type.Resize:
            self.update_hint()
        return super().eventFilter(watched, event)


def stylesheet(theme: str) -> str:
    """Вернуть общие правила размеров, состояний и цветов для выбранной темы."""
    c = PALETTES.get(theme, PALETTES['dark'])
    return f'''
    QWidget {{ color: {c['text']}; }}
    QMainWindow, QDialog, QDockWidget, QWidget#sidebar {{ background: {c['bg']}; }}
    QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
    QMenu {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
    QMenu::item {{ background: transparent; color: {c['text']}; padding: 8px 24px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    QMenu::item:disabled {{ color: {c['muted']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
    QLabel#brand {{ font-size: 17pt; font-weight: 600; }}
    QLabel#caption, QLabel#emptyHint {{ color: {c['muted']}; }}
    QLabel#emptyHint {{ background: transparent; }}
    QToolBar {{ background: {c['bg']}; border: none; border-bottom: 1px solid {c['border']}; spacing: 4px; padding: 8px; }}
    QToolBar::separator {{ background: {c['border']}; width: 1px; margin: 8px 6px; }}
    QPushButton, QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 6px 10px; min-height: 22px; }}
    QPushButton {{ background: {c['panel']}; border-color: {c['border']}; }}
    QPushButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
    QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{ background: {c['selected']}; }}
    QPushButton:focus, QToolButton:focus {{ border-color: {c['accent']}; }}
    QToolButton#treeControl {{ min-height: 0; padding: 0; border-radius: 5px; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {c['muted']}; }}
    QTreeWidget, QListWidget {{ background: {c['panel']}; border: none; outline: none; padding: 4px; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
    QTreeWidget::item, QListWidget::item {{ padding: 4px 6px; border: none; border-radius: 0; }}
    QTreeWidget::item:hover, QListWidget::item:hover {{ background: {c['hover']}; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 5px; padding: 7px; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
    QLineEdit QToolButton {{ padding: 0; min-height: 0; min-width: 0; border: none; border-radius: 0; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
    QCheckBox, QRadioButton {{ spacing: 8px; padding: 4px; }}
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 6px; margin-top: 12px; padding: 12px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: {c['bg']}; color: {c['muted']}; padding: 10px 14px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['text']}; font-weight: 600; border-bottom-color: {c['accent']}; }}
    QTabBar::tab:hover {{ background: {c['hover']}; }}
    QSplitter::handle {{ background: {c['border']}; width: 1px; }}
    QSplitter::handle:hover {{ background: {c['accent']}; }}
    QDockWidget::title {{ padding: 12px; font-weight: 600; background: {c['bg']}; }}
    QStatusBar {{ background: {c['bg']}; border-top: 1px solid {c['border']}; color: {c['muted']}; padding: 5px 10px; }}
    QStatusBar::item {{ border: none; }}
    QScrollBar:vertical {{ background: {c['panel']}; width: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 32px; border: 3px solid {c['panel']}; border-radius: 6px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    '''
