"""Измерить наследование шрифтов при повторном применении темы без WebEngine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QLabel, QMainWindow, QPushButton,
    QVBoxLayout, QWidget,
)

from course_reader.theme import DockTitleStyle, interface_font, stylesheet


def main():
    """Сравнить исходную тему, повторное применение и смену палитры."""
    app = QApplication(sys.argv)
    app.setFont(interface_font())
    window = QMainWindow()
    window.setWindowTitle('Диагностика шрифтов — автоматическое закрытие')
    window.setFont(interface_font())
    body = QWidget()
    layout = QVBoxLayout(body)
    label = QLabel('Надпись панели')
    button = QPushButton('Применить')
    brand = QLabel('Заголовок')
    brand.setObjectName('brand')
    for widget in (brand, label, button):
        layout.addWidget(widget)
    window.setCentralWidget(body)
    dock = QDockWidget('Заметки', window)
    dock_label = QLabel('Текст заметки')
    dock.setWidget(dock_label)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    status = window.statusBar()
    status.setFont(interface_font(monospace=True))
    status.showMessage('Путь к файлу')
    widgets = dict(window=window, label=label, button=button, brand=brand,
                   dock=dock, dock_label=dock_label, status=status)
    current_style = None
    baseline = None

    def apply(theme):
        """Повторить порядок обновления стилей основного окна."""
        nonlocal current_style
        window.setStyleSheet(stylesheet(theme))
        previous = current_style
        current_style = DockTitleStyle(theme, dock)
        dock.setStyle(current_style)
        if previous is not None:
            previous.deleteLater()

    def report(stage):
        """Напечатать заявленный и фактический размеры вместе с метриками."""
        nonlocal baseline
        print(stage, flush=True)
        snapshot = {}
        for name, widget in widgets.items():
            font = widget.font()
            actual = QFontInfo(font)
            print(name, font.family(), 'pt=', font.pointSizeF(),
                  'actual_pt=', actual.pointSizeF(),
                  'height=', widget.fontMetrics().height(), flush=True)
            expected_size = 17.0 if name == 'brand' else 9.5 if name == 'status' else 10.5
            assert font.pointSizeF() == expected_size, (
                f'{name}: expected {expected_size} pt, got {font.pointSizeF()}'
            )
            snapshot[name] = (font.family(), font.pointSizeF(), actual.family(),
                              actual.pointSizeF(), widget.fontMetrics().height())
        if baseline is None:
            baseline = snapshot
        else:
            assert snapshot == baseline, f'Font metrics changed: {baseline!r} -> {snapshot!r}'

    stages = iter(('dark', 'dark', 'light', 'dark'))

    def step():
        """Дать Qt обработать смену стиля до измерения."""
        try:
            report('snapshot')
            theme = next(stages, None)
            if theme is None:
                print('FONT_REGRESSION_PASS', flush=True)
                window.close()
                app.quit()
                return
            print('apply', theme, flush=True)
            apply(theme)
            QTimer.singleShot(250, step)
        except Exception as error:
            print(f'FONT_REGRESSION_FAIL: {error}', file=sys.stderr, flush=True)
            window.close()
            app.exit(1)

    apply('dark')
    window.show()
    QTimer.singleShot(250, step)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
