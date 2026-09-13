"""Запуск ручной проверки с отдельными данными и синтетическим курсом."""
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from course_reader.storage import Store
from course_reader.window import Window


def main() -> int:
    """Открыть тестовый курс, сохраняя историю только в tests/manual_state."""
    state = PROJECT / 'tests' / 'manual_state'
    state.mkdir(exist_ok=True)
    root = PROJECT / 'tests' / 'manual_course'
    app = QApplication(sys.argv)
    store = Store(state)
    course = store.course(root)
    if not course['last']:
        course['last'] = '01-basics/01-welcome.html'
    window = Window(store)
    window.setWindowTitle('Course Reader — ручная проверка')
    window.view.loadFinished.connect(lambda ok: print(f'LOAD {ok}: {window.view.url().toString()}', flush=True))
    window.show()
    QTimer.singleShot(0, lambda: window.set_course(root))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
