"""Сравнить координаты Qt и JavaScript при масштабе; запускать вручную отдельно от pytest.

Открывает временный просмотрщик с искусственной страницей без сетевых ресурсов.
Не читает настройки и историю приложения и ничего не сохраняет на диск.
"""

import json
import sys
import argparse

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from shiboken6 import delete


HTML = """<!doctype html><meta charset="utf-8">
<style>body{margin:0;font:20px sans-serif}p{height:100px;margin:0}</style>
""" + "".join(f"<p>Проверка прокрутки — абзац {i}</p>" for i in range(150))


def main() -> int:
    """Вывести исходную и восстановленные позиции и завершить проверку за минуту."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corrected", action="store_true", help="Пересчитать Qt-координату в CSS-пиксели")
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    view = QWebEngineView()
    profile = QWebEngineProfile(app)
    page = QWebEnginePage(profile, view)
    view.setPage(page)
    view.resize(900, 650)
    view.setWindowTitle("Диагностика прокрутки — тестовые данные")
    scales = iter((1.0, 1.1, 1.5))
    state = {"zoom": 1.0, "cycle": 0, "saved": 900.0, "stopped": False}

    def stop(code=0):
        """Остановить callback и освободить страницу до профиля."""
        if state["stopped"]:
            return
        state["stopped"] = True
        delete(view)
        delete(profile)
        app.exit(code)

    def next_scale():
        """Начать серию с фиксированной CSS-позиции 900 на следующем масштабе."""
        try:
            state["zoom"] = next(scales)
        except StopIteration:
            stop()
            return
        state.update(cycle=0, saved=900.0)
        view.setZoomFactor(state["zoom"])
        page.setHtml(HTML)

    def measured(css_y):
        """Записать обе координаты и повторить текущий алгоритм приложения."""
        if state["stopped"]:
            return
        qt_y = page.scrollPosition().y()
        print(json.dumps({"zoom": state["zoom"], "cycle": state["cycle"],
                          "corrected": args.corrected,
                          "requested_css_y": state["requested"], "actual_css_y": css_y,
                          "qt_y": qt_y}, ensure_ascii=False), flush=True)
        state["saved"] = qt_y
        state["cycle"] += 1
        if state["cycle"] == 4:
            QTimer.singleShot(0, next_scale)
        else:
            page.setHtml(HTML)

    def sample():
        """Прочитать CSS-координату после отрисовки искусственной страницы."""
        if not state["stopped"]:
            page.runJavaScript("window.scrollY", measured)

    def loaded(success):
        """Воспроизвести window.scrollTo после окончания загрузки."""
        if state["stopped"]:
            return
        if not success:
            print("Ошибка загрузки тестовой страницы", flush=True)
            stop(1)
            return
        target = state["saved"]
        if args.corrected and state["cycle"] > 0:
            target /= view.zoomFactor()
        state["requested"] = target
        page.runJavaScript(f"window.scrollTo(0, {target});",
                           lambda _result: QTimer.singleShot(600, sample))

    page.loadFinished.connect(loaded)
    QTimer.singleShot(60000, lambda: stop(2))
    view.show()
    QTimer.singleShot(0, next_scale)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
