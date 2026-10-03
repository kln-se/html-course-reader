"""Проверки отрисовки меток через записывающие границы Qt без QApplication."""
from types import SimpleNamespace as NS

import pytest

from src.course_reader import theme


class RecordingPainter:
    """Записать команды рисования и при необходимости имитировать ошибку."""
    def __init__(self):
        self.events = []
        self.failure = None

    def __getattr__(self, name):
        def record(*args):
            self.events.append((name, args))
            if name == self.failure:
                raise RuntimeError('drawing failed')
        return record

    def calls(self, name):
        return [args for method, args in self.events if method == name]


@pytest.fixture
def drawing(monkeypatch):
    """Подготовить внешние границы Qt, сохранив настоящий код делегата."""
    class Metrics:
        def __init__(self, font):
            self.font = theme.QFont(font)
            self.elisions = []

        def horizontalAdvance(self, text):
            return len(text) * 7

        def height(self):
            return 12

        def elidedText(self, text, mode, width):
            self.elisions.append((text, mode, width))
            if width <= 0:
                return ''
            if self.horizontalAdvance(text) <= width:
                return text
            return text[:max(0, width // 7 - 1)] + '…'

    class BadgeMetrics(Metrics):
        def elidedText(self, *args):
            raise AssertionError('paint не должен сокращать метку формата')

    monkeypatch.setattr(theme, 'QFontMetrics', BadgeMetrics)
    monkeypatch.setattr(theme, 'QStyleOptionViewItem', lambda option: NS(**vars(option)))
    monkeypatch.setattr(theme.TreeRowDelegate, 'initStyleOption', lambda self, option, index: None)

    def make(theme_name='dark', selected=False, enabled=True, width=120):
        font = theme.QFont()
        font.setPointSizeF(12)
        state = theme.QStyle.StateFlag.State_None
        if selected:
            state |= theme.QStyle.StateFlag.State_Selected
        if enabled:
            state |= theme.QStyle.StateFlag.State_Enabled
        rect = theme.QRect(10, 20, width, 28)
        painter = RecordingPainter()
        palette_calls = []

        def color(group, role):
            palette_calls.append((group, role))
            return theme.QColor('#123456')

        style = NS(
            subElementRect=lambda *args: theme.QRect(rect),
            drawControl=lambda control, styled, painter, widget:
                painter.native(control, styled.text, styled.state),
        )
        widget = NS(style=lambda: style,
                    property=lambda name: theme_name if name == 'theme' else None)
        option = NS(font=font, fontMetrics=Metrics(font), state=state,
                    rect=rect, widget=widget, palette=NS(color=color), text='[.html] lesson')
        index = NS(data=lambda role: '[.html]' if role == theme.TREE_PREFIX_ROLE else None)
        return NS(delegate=theme.TreeRowDelegate(), option=option, index=index,
                  painter=painter, palette_calls=palette_calls)
    return make


@pytest.mark.parametrize('theme_name', ['dark', 'light'])
@pytest.mark.parametrize(('selected', 'enabled', 'background', 'foreground', 'group', 'role'), [
    (False, True, 'hover', 'text', 'Normal', 'Text'),
    (True, True, 'panel', 'text', 'Normal', 'HighlightedText'),
    (False, False, 'hover', 'muted', 'Disabled', 'Text'),
])
def test_paint_colors_and_name(drawing, theme_name, selected, enabled, background, foreground, group, role):
    """Given: тема и состояние. When: paint. Then: верные цвета и исходное имя."""
    item = drawing(theme_name, selected, enabled)
    item.delegate.paint(item.painter, item.option, item.index)
    colors = theme.PALETTES[theme_name]
    assert item.painter.calls('setBrush') == [(theme.QColor(colors[background]),)]
    assert item.painter.calls('setPen') == [
        (theme.Qt.PenStyle.NoPen,), (theme.QColor(colors[foreground]),), (theme.QColor('#123456'),),
    ]
    assert item.palette_calls == [
        (getattr(theme.QPalette.ColorGroup, group), getattr(theme.QPalette.ColorRole, role))
    ]
    assert item.painter.calls('drawRoundedRect') == [(theme.QRect(10, 25, 40, 18), 4, 4)]
    assert item.painter.calls('drawText') == [
        (theme.QRect(10, 25, 40, 18), theme.Qt.AlignmentFlag.AlignCenter, 'HTML'),
        (theme.QRect(58, 20, 72, 28),
         theme.Qt.AlignmentFlag.AlignVCenter | theme.Qt.AlignmentFlag.AlignLeft, 'lesson'),
    ]
    assert item.painter.calls('native') == [
        (theme.QStyle.ControlElement.CE_ItemViewItem, '', item.option.state)
    ]
    assert item.option.text == '[.html] lesson'
    assert item.painter.events[0] == ('save', ())
    assert item.painter.events[-1] == ('restore', ())


@pytest.mark.parametrize(('width', 'name_width'), [(71, 23), (40, 0), (0, 0)])
def test_narrow_row_keeps_complete_badge(drawing, width, name_width):
    """Given: узкая строка. When: paint. Then: метка полная, имя занимает остаток."""
    item = drawing(width=width)
    item.delegate.paint(item.painter, item.option, item.index)
    badge_rect = theme.QRect(10, 25, 40, 18)
    name_rect = theme.QRect(58, 20, name_width, 28)
    assert item.painter.calls('drawRoundedRect') == [(badge_rect, 4, 4)]
    assert item.painter.calls('setBrush') == [(theme.QColor(theme.PALETTES['dark']['hover']),)]
    assert item.option.fontMetrics.elisions == [
        ('lesson', theme.Qt.TextElideMode.ElideMiddle, name_width)
    ]
    text_calls = item.painter.calls('drawText')
    assert text_calls[0] == (badge_rect, theme.Qt.AlignmentFlag.AlignCenter, 'HTML')
    assert item.painter.calls('setClipRect') == [
        (item.option.rect, theme.Qt.ClipOperation.IntersectClip)
    ]
    operations = [operation for operation, _ in item.painter.events]
    assert operations.index('setClipRect') < operations.index('drawRoundedRect')
    if name_width:
        assert len(text_calls) == 2
        assert text_calls[1][0] == name_rect
        assert text_calls[1][1] == theme.Qt.AlignmentFlag.AlignVCenter | theme.Qt.AlignmentFlag.AlignLeft
    else:
        assert len(text_calls) == 1
    assert not badge_rect.intersects(name_rect)


def test_missing_prefix_delegates_to_parent(drawing, monkeypatch):
    """Given: нет префикса. When: paint. Then: вызван родительский paint."""
    item = drawing()
    item.index.data = lambda role: None
    calls = []
    monkeypatch.setattr(theme.RowDelegate, 'paint',
                        lambda self, painter, option, index: calls.append((self, painter, option, index)))
    item.delegate.paint(item.painter, item.option, item.index)
    assert calls == [(item.delegate, item.painter, item.option, item.index)]
    assert item.painter.events == []


def test_long_name_requests_middle_elision_without_changing_model(drawing):
    """Given: длинное имя. When: paint. Then: запрошено сокращение в середине."""
    item = drawing()
    name = 'very-long-lesson-name.html'
    item.option.text = '[.html] ' + name
    item.delegate.paint(item.painter, item.option, item.index)
    assert item.option.fontMetrics.elisions == [(name, theme.Qt.TextElideMode.ElideMiddle, 72)]
    assert item.option.text == '[.html] ' + name


def test_painter_restored_after_drawing_failure(drawing):
    """Given: ошибка рисования. When: paint. Then: restore и исходная ошибка."""
    item = drawing()
    item.painter.failure = 'drawRoundedRect'
    with pytest.raises(RuntimeError, match='^drawing failed$'):
        item.delegate.paint(item.painter, item.option, item.index)
    assert item.painter.calls('save') == [()]
    assert item.painter.calls('restore') == [()]
    assert item.painter.events[-1] == ('restore', ())


@pytest.mark.parametrize(('prefix', 'expected_width', 'expected_height'), [
    ('[.html]', 92, 26), (None, 100, 20),
])
def test_size_hint_replaces_prefix_and_fits_badge(drawing, monkeypatch, prefix, expected_width, expected_height):
    """Given: базовый размер. When: sizeHint. Then: учтены метка и префикс."""
    item = drawing()
    item.index.data = lambda role: prefix
    monkeypatch.setattr(theme.RowDelegate, 'sizeHint', lambda self, option, index: theme.QSize(100, 20))
    size = item.delegate.sizeHint(item.option, item.index)
    assert size.width() == expected_width
    assert size.height() == expected_height
