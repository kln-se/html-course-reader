"""Проверки двухстрочного списка курсов без создания окон Qt."""

from types import SimpleNamespace as NS
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from src.course_reader import theme
from src.course_reader import window as module


@pytest.mark.parametrize(
    "path,expected",
    [
        (r"C:\Courses\Python", "Python"),
        ("C:/Курсы/Микросервисы/", "Микросервисы"),
        ("C:\\Courses\\Python\\", "Python"),
        (r"\\server\share\Python", "Python"),
        ("C:\\", "C:\\"),
        ("\\\\server\\share\\", "\\\\server\\share\\"),
        ("Python", "Python"),
        ("", ""),
    ],
)
def test_course_title_preserves_windows_path_boundaries(path, expected):
    assert theme.course_title(path) == expected


@pytest.mark.parametrize(
    "title_size,path_size", [(8.0, 8.0), (10.5, 9.5), (18.0, 17.0)]
)
def test_fonts_distinguish_title_and_path_without_changing_original(
    monkeypatch, title_size, path_size
):
    original = QFont()
    original.setPointSizeF(title_size)
    original.setWeight(QFont.Weight.Normal)
    factory = Mock(side_effect=lambda **kwargs: QFont("Consolas"))
    monkeypatch.setattr(theme, "interface_font", factory)

    title, path = theme.CourseRowDelegate.row_fonts(original)

    factory.assert_called_once_with(monospace=True)
    assert title.weight() == QFont.Weight.DemiBold
    assert title.pointSizeF() == title_size
    assert path.family() == "Consolas"
    assert path.weight() == QFont.Weight.Normal
    assert path.pointSizeF() == path_size
    assert original.weight() == QFont.Weight.Normal
    assert original.pointSizeF() == title_size


@pytest.fixture
def chooser(monkeypatch, tmp_path):
    """Подготовить два одноимённых курса и заменить только интерфейсные границы."""
    roots = [tmp_path / parent / "Python" for parent in ("first", "second")]
    for root in roots:
        root.mkdir(parents=True)
    listing, dialog = Mock(), Mock()
    listing.currentItem.return_value = None
    rows, buttons = [], {}

    def add_items(paths):
        for path in paths:
            item = Mock()
            item.text.return_value = path
            rows.append(item)

    def set_current(item):
        listing.currentItem.return_value = item

    def button(label):
        buttons[label] = Mock()
        return buttons[label]

    listing.addItems.side_effect = add_items
    listing.item.side_effect = lambda row: rows[row]
    listing.findItems.side_effect = lambda path, flags: [
        row for row in rows if row.text() == path
    ]
    listing.setCurrentItem.side_effect = set_current
    monkeypatch.setattr(module, "QDialog", Mock(return_value=dialog))
    monkeypatch.setattr(module, "QVBoxLayout", Mock())
    monkeypatch.setattr(module, "QListWidget", Mock(return_value=listing))
    monkeypatch.setattr(module, "QPushButton", button)
    monkeypatch.setattr(module, "CourseRowDelegate", Mock())
    monkeypatch.setattr(module, "interface_font", Mock())
    message, directory = Mock(), Mock(return_value="")
    monkeypatch.setattr(module, "QMessageBox", message)
    monkeypatch.setattr(module, "QFileDialog", NS(getExistingDirectory=directory))
    state = NS(
        root=roots[1],
        set_course=Mock(),
        persist=Mock(),
        remove_course=Mock(return_value=True),
        store=NS(
            data={"courses": {str(root): {} for root in roots}},
            settings={"app": {"theme": "dark"}},
            relocate=Mock(),
        ),
    )
    return NS(
        state=state,
        roots=roots,
        listing=listing,
        rows=rows,
        buttons=buttons,
        dialog=dialog,
        message=message,
        directory=directory,
    )


@pytest.mark.parametrize("palette", ["dark", "light"])
@pytest.mark.parametrize("double_click", [False, True])
@pytest.mark.parametrize("selected_row", [0, 1])
def test_same_named_courses_keep_paths_selection_and_opening(
    chooser, palette, double_click, selected_row
):
    """Given: два курса Python. When: открывают активный. Then: используется его полный путь."""
    item = chooser
    item.state.store.settings["app"]["theme"] = palette
    module.Window.choose_course(item.state)
    paths = [str(root) for root in item.roots]
    assert [theme.course_title(path) for path in paths] == ["Python", "Python"]
    item.listing.addItems.assert_called_once_with(paths)
    for row, path in zip(item.rows, paths, strict=True):
        row.setToolTip.assert_called_once_with(path)
    item.listing.findItems.assert_called_once_with(paths[1], Qt.MatchFlag.MatchExactly)
    item.listing.setCurrentItem.assert_called_once_with(item.rows[1])
    item.listing.scrollToItem.assert_called_once_with(item.rows[1])
    item.listing.setProperty.assert_called_once_with("theme", palette)
    item.listing.setHorizontalScrollBarPolicy.assert_called_once_with(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )

    item.listing.currentItem.return_value = item.rows[selected_row]
    signal = (
        item.listing.itemDoubleClicked
        if double_click
        else item.buttons["Открыть"].clicked
    )
    signal.connect.call_args.args[0]()

    item.state.set_course.assert_called_once_with(item.roots[selected_row])
    item.dialog.accept.assert_called_once_with()


def test_relocate_passes_full_selected_path(chooser, tmp_path):
    item = chooser
    module.Window.choose_course(item.state)
    target = tmp_path / "new-course"
    item.directory.return_value = str(target)
    item.buttons["Указать новое расположение"].clicked.connect.call_args.args[0]()
    item.state.store.relocate.assert_called_once_with(str(item.roots[1]), target)
    item.state.persist.assert_called_once_with()
    item.state.set_course.assert_called_once_with(target)


def test_missing_course_does_not_open_or_accept(chooser, tmp_path):
    item = chooser
    module.Window.choose_course(item.state)
    item.listing.currentItem.return_value = Mock(
        text=Mock(return_value=str(tmp_path / "missing"))
    )
    item.buttons["Открыть"].clicked.connect.call_args.args[0]()
    item.state.set_course.assert_not_called()
    item.dialog.accept.assert_not_called()
    item.message.information.assert_called_once()


def test_removal_uses_full_selected_path(chooser):
    item = chooser
    module.Window.choose_course(item.state)
    item.listing.row.return_value = 1
    item.buttons["Удалить из списка"].clicked.connect.call_args.args[0]()
    item.state.remove_course.assert_called_once_with(str(item.roots[1]))
    item.listing.takeItem.assert_called_once_with(1)


@pytest.mark.parametrize("palette", ["dark", "light"])
@pytest.mark.parametrize("width", [12, 180, 700])
def test_delegate_draws_two_lines_and_preserves_selection(monkeypatch, palette, width):
    """Given: узкая или широкая строка. When: paint. Then: две области, сокращение и выделение."""
    elisions = []

    class Metrics:
        def __init__(self, font):
            self.font = font

        def height(self):
            return 20

        def elidedText(self, text, mode, available):
            elisions.append((text, mode, available))
            return text if len(text) * 8 <= available else "…"

    monkeypatch.setattr(theme, "QFontMetrics", Metrics)
    monkeypatch.setattr(theme, "interface_font", lambda **kwargs: QFont("Consolas"))
    monkeypatch.setattr(
        theme, "QStyleOptionViewItem", lambda option: NS(**vars(option))
    )
    monkeypatch.setattr(theme.CourseRowDelegate, "initStyleOption", lambda *args: None)
    style, painter = Mock(), Mock()
    widget = NS(style=lambda: style, property=lambda name: palette)
    font = QFont()
    font.setPointSizeF(10.5)
    path = r"C:\Очень длинная папка\Курсы\Python"
    flags = QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus
    option = NS(
        text=path,
        font=font,
        widget=widget,
        state=flags,
        rect=QRect(0, 0, width, 60),
    )
    delegate = theme.CourseRowDelegate()

    delegate.paint(painter, cast(QStyleOptionViewItem, option), cast(QModelIndex, None))

    assert elisions == [
        ("Python", Qt.TextElideMode.ElideRight, max(0, width - 24)),
        (path, Qt.TextElideMode.ElideMiddle, max(0, width - 24)),
    ]
    painted = painter.drawText.call_args_list
    assert len(painted) == 2
    assert painted[0].args[0].bottom() < painted[1].args[0].top()
    assert [entry.args[0].name() for entry in painter.setPen.call_args_list] == [
        theme.PALETTES[palette]["text"].lower(),
        theme.PALETTES[palette]["muted"].lower(),
    ]
    styled = style.drawControl.call_args.args[1]
    assert styled.text == ""
    assert styled.state & QStyle.StateFlag.State_Selected
    assert not styled.state & QStyle.StateFlag.State_HasFocus
    assert option.text == path and option.state == flags
    painter.restore.assert_called_once_with()
    assert (
        delegate.sizeHint(
            cast(QStyleOptionViewItem, option), cast(QModelIndex, None)
        ).height()
        >= 56
    )
    assert (
        delegate.sizeHint(
            cast(QStyleOptionViewItem, option), cast(QModelIndex, None)
        ).width()
        == 0
    )
