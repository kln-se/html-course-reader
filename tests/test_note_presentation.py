"""Проверки данных и команд отрисовки заметок без создания окон Qt."""

from pathlib import Path
from types import SimpleNamespace as NS
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QFont, QIcon, QTextOption
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from test_course_notes import reader as _reader_fixture

from src.course_reader import note_presentation as module
from src.course_reader import theme
from src.course_reader.note_presentation import OpenPageSummary
from src.course_reader.theme import PALETTES

reader = _reader_fixture


@pytest.mark.parametrize(
    "path,expected",
    [
        ("01-basics/Введение.html", "Введение.html"),
        ("<b>&page.html", "<b>&page.html"),
        ("/", "/"),
        ("", ""),
    ],
)
def test_page_name_preserves_plain_text(path, expected):
    assert module.page_name(path) == expected


@pytest.mark.parametrize("relative", [None, "section/<b>&page.html"])
def test_summary_updates_full_tooltip_and_accessibility_without_markup(relative):
    subject = NS(
        setToolTip=Mock(),
        setAccessibleName=Mock(),
        updateGeometry=Mock(),
        update=Mock(),
    )
    module.OpenPageSummary.set_page(cast(OpenPageSummary, subject), relative)
    expected = "Открытая страница: " + relative if relative else "Нет открытой страницы"
    assert subject.relative == relative
    subject.setToolTip.assert_called_once_with(expected)
    subject.setAccessibleName.assert_called_once_with(expected)
    subject.updateGeometry.assert_called_once_with()
    subject.update.assert_called_once_with()


@pytest.mark.parametrize("palette", ["dark", "light"])
def test_summary_changes_theme_and_repaints(palette):
    subject = NS(theme="other", update=Mock())
    module.OpenPageSummary.set_theme(cast(OpenPageSummary, subject), palette)
    assert subject.theme == palette
    subject.update.assert_called_once_with()


@pytest.mark.parametrize("palette", ["dark", "light"])
@pytest.mark.parametrize("width", [0, 15, 600])
def test_page_lines_use_distinct_fonts_colors_and_elision(monkeypatch, palette, width):
    elisions = []

    class Metrics:
        def __init__(self, font):
            pass

        def height(self):
            return 20

        def elidedText(self, text, mode, available):
            elisions.append((text, mode, available))
            return text

    monkeypatch.setattr(module, "QFontMetrics", Metrics)
    monkeypatch.setattr(theme, "interface_font", lambda **kwargs: QFont("Consolas"))
    painter = Mock()
    font = QFont()
    font.setPointSizeF(10.5)
    relative = "section/<b>&page.html"
    module.draw_page_lines(
        painter, QRect(0, 0, width, 70), font, PALETTES[palette], relative
    )
    assert elisions == [
        ("<b>&page.html", Qt.TextElideMode.ElideRight, width),
        (relative, Qt.TextElideMode.ElideMiddle, width),
    ]
    title, path = [entry.args[0] for entry in painter.setFont.call_args_list]
    assert title.weight() == QFont.Weight.DemiBold
    assert path.family() == "Consolas"
    assert path.pointSizeF() < title.pointSizeF()
    assert [entry.args[0].name() for entry in painter.setPen.call_args_list] == [
        PALETTES[palette][key].lower() for key in ("text", "muted")
    ]
    lines = painter.drawText.call_args_list
    assert lines[0].args[0].bottom() < lines[1].args[0].top()
    assert [entry.args[2] for entry in lines] == ["<b>&page.html", relative]


@pytest.mark.parametrize("palette", ["dark", "light"])
@pytest.mark.parametrize("width,expected_width", [(0, 284), (8, 1), (200, 184)])
def test_note_document_keeps_plain_text_and_mutes_only_date(
    monkeypatch, palette, width, expected_width
):
    """Given: текст с HTML. When: создаётся документ. Then: текст вставлен буквально, дата вторична."""
    document, cursor = Mock(), Mock()
    monkeypatch.setattr(module, "QTextDocument", Mock(return_value=document))
    cursor_factory = Mock(return_value=cursor)
    monkeypatch.setattr(module, "QTextCursor", cursor_factory)
    font = QFont()
    font.setPointSizeF(10.5)
    text = "<b>Очень длинная заметка</b>\n" + "word" * 80
    date = "27.09.2026 10:26"
    index = NS(
        data=lambda role: {module.NOTE_TEXT_ROLE: text, module.NOTE_TIME_ROLE: date}[
            role
        ]
    )
    option = NS(
        font=font,
        rect=QRect(0, 0, width, 20),
        widget=NS(property=lambda key: palette, viewport=lambda: NS(width=lambda: 300)),
    )
    result = module.NoteRowDelegate.note_document(
        cast(QStyleOptionViewItem, option), cast(QModelIndex, index)
    )
    assert result is document
    cursor_factory.assert_called_once_with(document)
    document.setTextWidth.assert_called_once_with(expected_width)
    wrap = document.setDefaultTextOption.call_args.args[0].wrapMode()
    assert wrap == QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
    body, metadata = cursor.insertText.call_args_list
    assert body.args[0] == text
    assert metadata.args[0] == "Изменено: " + date
    assert body.args[1].foreground().color().name() == PALETTES[palette]["text"].lower()
    assert (
        metadata.args[1].foreground().color().name()
        == PALETTES[palette]["muted"].lower()
    )
    assert metadata.args[1].fontPointSize() == 9.5
    cursor.insertBlock.assert_called_once_with()
    document.setHtml.assert_not_called()


def test_group_metadata_retains_full_paths_and_filtered_counts(reader):
    """Given: одинаковые имена файлов. When: поиск. Then: группы различимы, счётчики отражают совпадения."""
    for path, text in [
        ("a/page.html", "match <b>one</b>"),
        ("a/page.html", "hidden"),
        ("b/page.html", "match two"),
    ]:
        reader.store.add_note(reader.root, path, text)
    reader.notes_search.text.return_value = "match"
    reader.refresh_notes()
    assert set(reader.note_groups) == {"a/page.html", "b/page.html"}
    for path, (heading, rows) in reader.note_groups.items():
        assert heading.data(module.NOTE_GROUP_ROLE) == (str(reader.root), path)
        assert heading.data(module.NOTE_COUNT_ROLE) == 1
        assert heading.tooltip.startswith(path)
        assert not heading.flags() & Qt.ItemFlag.ItemIsSelectable
        note = rows[0]
        assert note.data(Qt.ItemDataRole.UserRole)[1] == path
        assert (
            note.data(module.NOTE_TEXT_ROLE)
            == reader.store.course(reader.root)["notes"][path][0]["text"]
        )
        assert note.data(module.NOTE_TIME_ROLE)
    reader.notes_action.setText.assert_called_with("Заметки (3)")


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_delegate_paints_group_or_note_and_restores_painter(monkeypatch, group, fails):
    """Given: выделенная строка. When: отрисовка или её сбой. Then: нужная ветвь и восстановление painter."""
    qt_option_type = QStyleOptionViewItem

    class StyledOption:
        def __init__(self, option):
            self.qt_option = qt_option_type()
            for key, value in vars(option).items():
                setattr(self, key, value)

        @property
        def icon(self):
            return self.qt_option.icon

        @icon.setter
        def icon(self, value):
            self.qt_option.icon = value

    monkeypatch.setattr(module, "QStyleOptionViewItem", StyledOption)
    monkeypatch.setattr(module.NoteRowDelegate, "initStyleOption", lambda *args: None)
    monkeypatch.setattr(
        module,
        "QFontMetrics",
        lambda font: NS(horizontalAdvance=lambda text: 8, height=lambda: 20),
    )
    monkeypatch.setattr(theme, "interface_font", lambda **kwargs: QFont("Consolas"))
    page_lines = Mock(
        side_effect=RuntimeError("paint failed") if fails and group else None
    )
    monkeypatch.setattr(module, "draw_page_lines", page_lines)
    document = Mock()
    if fails and not group:
        document.drawContents.side_effect = RuntimeError("paint failed")
    monkeypatch.setattr(
        module.NoteRowDelegate, "note_document", Mock(return_value=document)
    )
    painter, style = Mock(), Mock()
    chevron = QIcon(
        str(Path(__file__).resolve().parents[1] / "src/course_reader/assets/app.svg")
    )
    assert not chevron.isNull()
    painted_icons = []

    def paint_icon(icon, painter, rect):
        assert not icon.isNull(), "Очистка стандартной иконки не должна обнулять шеврон"
        painted_icons.append(QIcon(icon))

    monkeypatch.setattr(QIcon, "paint", paint_icon)
    flags = QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus
    option = NS(
        text="original",
        font=QFont(),
        icon=chevron,
        state=flags,
        rect=QRect(0, 0, 400, 70),
        widget=NS(property=lambda key: "dark", style=lambda: style),
    )
    roles = {
        module.NOTE_GROUP_ROLE: ("root", "a/page.html") if group else None,
        module.NOTE_COUNT_ROLE: 7,
        module.NOTE_TEXT_ROLE: "body",
    }
    index = NS(data=lambda role: roles.get(role))
    delegate = module.NoteRowDelegate()
    if fails:
        with pytest.raises(RuntimeError, match="paint failed"):
            delegate.paint(
                painter, cast(QStyleOptionViewItem, option), cast(QModelIndex, index)
            )
    else:
        delegate.paint(
            painter, cast(QStyleOptionViewItem, option), cast(QModelIndex, index)
        )
    styled = style.drawControl.call_args.args[1]
    assert styled.text == ""
    assert styled.state & QStyle.StateFlag.State_Selected
    assert not styled.state & QStyle.StateFlag.State_HasFocus
    assert option.text == "original" and option.state == flags
    painter.save.assert_called_once_with()
    painter.restore.assert_called_once_with()
    if group:
        assert page_lines.call_args.args[-1] == "a/page.html"
        assert len(painted_icons) == 1
        assert styled.icon.isNull()
        document.drawContents.assert_not_called()
        if not fails:
            assert painter.drawText.call_args.args[-1] == "7"
    else:
        page_lines.assert_not_called()
        document.drawContents.assert_called_once_with(painter)


def test_note_height_rounds_up_fractional_layout(monkeypatch):
    document = NS(size=lambda: NS(height=lambda: 40.2))
    monkeypatch.setattr(
        module.NoteRowDelegate, "note_document", Mock(return_value=document)
    )
    index = NS(data=lambda role: "body" if role == module.NOTE_TEXT_ROLE else None)
    hint = module.NoteRowDelegate().sizeHint(
        cast(QStyleOptionViewItem, NS()), cast(QModelIndex, index)
    )
    assert hint.height() == 57
    assert hint.width() == 0
