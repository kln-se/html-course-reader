"""Представление групп заметок, текста записей и сведений об открытой странице."""

from collections.abc import Mapping
from math import ceil
from pathlib import PurePosixPath
from typing import cast

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPaintEvent,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QSizePolicy,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)

from .theme import PALETTES, CourseRowDelegate, RowDelegate

NOTE_GROUP_ROLE = int(Qt.ItemDataRole.UserRole) + 1
NOTE_COUNT_ROLE = NOTE_GROUP_ROLE + 1
NOTE_TEXT_ROLE = NOTE_COUNT_ROLE + 1
NOTE_TIME_ROLE = NOTE_TEXT_ROLE + 1


def page_name(relative: str) -> str:
    """Получить имя файла из относительного пути, хранящегося с разделителем /."""
    return PurePosixPath(relative).name or relative


def draw_page_lines(
    painter: QPainter,
    rect: QRect,
    font: QFont,
    colors: Mapping[str, str],
    relative: str,
) -> None:
    """Нарисовать имя и путь обычным текстом, сокращая их по доступной ширине."""
    title_font, path_font = CourseRowDelegate.row_fonts(font)
    top = rect.top()
    for text, line_font, color, mode in (
        (page_name(relative), title_font, colors["text"], Qt.TextElideMode.ElideRight),
        (relative, path_font, colors["muted"], Qt.TextElideMode.ElideMiddle),
    ):
        metrics = QFontMetrics(line_font)
        line = QRect(rect.left(), top, max(0, rect.width()), metrics.height())
        painter.setFont(line_font)
        painter.setPen(QColor(color))
        painter.drawText(
            line,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(text, mode, line.width()),
        )
        top += metrics.height() + 4


class NoteRowDelegate(RowDelegate):
    """Отображать заголовки групп и заметки с переносом текста и второстепенной датой."""

    @staticmethod
    def note_document(
        option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QTextDocument:
        """Сформировать переносимый текст заметки с отдельным приглушённым временем."""
        colors = PALETTES.get(option.widget.property("theme"), PALETTES["dark"])
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setDocumentMargin(0)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(text_option)
        width = option.rect.width()
        if width <= 0:
            width = cast(QAbstractItemView, option.widget).viewport().width()
        document.setTextWidth(max(1, width - 16))
        cursor = QTextCursor(document)
        body = QTextCharFormat()
        body.setForeground(QColor(colors["text"]))
        cursor.insertText(index.data(NOTE_TEXT_ROLE), body)
        cursor.insertBlock()
        metadata = QTextCharFormat()
        metadata.setForeground(QColor(colors["muted"]))
        if option.font.pointSizeF() > 0:
            metadata.setFontPointSize(max(8.0, option.font.pointSizeF() - 1))
        cursor.insertText("Изменено: " + index.data(NOTE_TIME_ROLE), metadata)
        return document

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """Рассчитать высоту строки с учётом переноса текста заметки и внутренних отступов."""
        if not index.data(NOTE_GROUP_ROLE):
            if index.data(NOTE_TEXT_ROLE) is not None:
                return QSize(
                    0, ceil(self.note_document(option, index).size().height()) + 16
                )
            return super().sizeHint(option, index)
        title, path = CourseRowDelegate.row_fonts(option.font)
        return QSize(
            0, max(56, QFontMetrics(title).height() + QFontMetrics(path).height() + 20)
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Нарисовать заголовок группы или текст заметки с приглушённой датой изменения."""
        group = index.data(NOTE_GROUP_ROLE)
        if not group:
            if index.data(NOTE_TEXT_ROLE) is not None:
                styled = QStyleOptionViewItem(option)
                self.initStyleOption(styled, index)
                document = self.note_document(styled, index)
                styled.text = ""
                styled.state &= ~QStyle.StateFlag.State_HasFocus
                painter.save()
                try:
                    styled.widget.style().drawControl(
                        QStyle.ControlElement.CE_ItemViewItem,
                        styled,
                        painter,
                        styled.widget,
                    )
                    painter.setClipRect(styled.rect, Qt.ClipOperation.IntersectClip)
                    painter.translate(styled.rect.left() + 8, styled.rect.top() + 8)
                    document.drawContents(painter)
                finally:
                    painter.restore()
                return
            return super().paint(painter, option, index)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        colors = PALETTES.get(styled.widget.property("theme"), PALETTES["dark"])
        # Getter возвращает ссылку: очистка styled.icon обнулит её без копии.
        chevron = QIcon(styled.icon)
        styled.icon = QIcon()
        styled.text = ""
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        _, count_font = CourseRowDelegate.row_fonts(styled.font)
        metrics = QFontMetrics(count_font)
        count = str(index.data(NOTE_COUNT_ROLE) or 0)
        area = styled.rect.adjusted(8, 8, -8, -8)
        badge_width = min(max(0, area.width()), metrics.horizontalAdvance(count) + 16)
        badge = QRect(
            area.right() - badge_width + 1,
            area.top(),
            badge_width,
            metrics.height() + 4,
        )
        text_rect = QRect(
            area.left() + 24,
            area.top(),
            max(0, area.width() - badge_width - 32),
            area.height(),
        )
        painter.save()
        try:
            styled.widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget
            )
            painter.setClipRect(styled.rect, Qt.ClipOperation.IntersectClip)
            chevron.paint(painter, QRect(area.left(), area.top() + 2, 16, 16))
            draw_page_lines(painter, text_rect, styled.font, colors, group[1])
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["hover"]))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QColor(colors["muted"]))
            painter.setFont(count_font)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, count)
        finally:
            painter.restore()


class OpenPageSummary(QWidget):
    """Показывать текущую страницу без фокуса, горизонтальной прокрутки и HTML-разметки."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Создать информационный блок, пока страница не открыта."""
        super().__init__(parent)
        self.relative: str | None = None
        self.theme = "dark"
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_page(None)

    def set_page(self, relative: str | None) -> None:
        """Обновить имя, полный относительный путь и текст для средств доступности."""
        self.relative = relative
        text = "Открытая страница: " + relative if relative else "Нет открытой страницы"
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.updateGeometry()
        self.update()

    def set_theme(self, name: str) -> None:
        """Перерисовать блок цветами выбранной темы."""
        self.theme = name
        self.update()

    def sizeHint(self) -> QSize:
        """Отвести место подписи, двум строкам страницы и разделителю."""
        title, path = CourseRowDelegate.row_fonts(self.font())
        height = QFontMetrics(path).height() + 18
        if self.relative:
            height += QFontMetrics(title).height() + QFontMetrics(path).height() + 8
        return QSize(0, height)

    def changeEvent(self, event: QEvent) -> None:
        """Пересчитать высоту при смене шрифта приложения."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.updateGeometry()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Нарисовать разделитель, подпись и страницу в пределах ширины панели."""
        colors = PALETTES.get(self.theme, PALETTES["dark"])
        painter = QPainter(self)
        try:
            painter.setPen(QColor(colors["border"]))
            painter.drawLine(0, 0, self.width(), 0)
            _, caption_font = CourseRowDelegate.row_fonts(self.font())
            metrics = QFontMetrics(caption_font)
            painter.setFont(caption_font)
            painter.setPen(QColor(colors["muted"]))
            caption = "Открытая страница:" if self.relative else "Нет открытой страницы"
            painter.drawText(
                QRect(0, 10, self.width(), metrics.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(caption, Qt.TextElideMode.ElideRight, self.width()),
            )
            if self.relative:
                top = 10 + metrics.height() + 6
                draw_page_lines(
                    painter,
                    QRect(0, top, self.width(), max(0, self.height() - top)),
                    self.font(),
                    colors,
                    self.relative,
                )
        finally:
            painter.end()
