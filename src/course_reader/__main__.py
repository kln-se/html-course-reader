"""Запуск приложения с данными рядом с программой."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from .storage import Store
from .window import Window


def main() -> int:
    """Создать приложение, открыть выбор курса и вернуть код завершения Qt.

    Данные размещаются у EXE в сборке или в корне исходников. Ошибка
    создания хранилища или окна выводится в диалоге и возвращает код 1."""
    app = QApplication(sys.argv)
    app.setApplicationName('Course Reader')
    directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    try:
        store = Store(directory)
        window = Window(store)
    except Exception as error:
        QMessageBox.critical(None, 'Ошибка запуска', str(error))
        return 1
    window.show()
    window.choose_course()
    return app.exec()
