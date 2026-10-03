"""Явно запускаемая через pytest проверка шрифтов с настоящими виджетами Qt.

Имя файла исключает автоматический запуск GUI обычной командой pytest.
"""

from pathlib import Path
import subprocess
import sys


def test_font_metrics_survive_repeated_theme_application():
    """Given: виджеты Qt с обычным, заголовочным и моноширинным шрифтом.

    When: тема повторно применяется и переключается между тёмной и светлой.
    Then: гарнитуры, размеры и высота текста остаются стабильными.
    """
    probe = Path(__file__).with_name('window_font_probe.py').resolve()
    result = subprocess.run(
        [sys.executable, '-B', str(probe)],
        cwd=probe.parent.parent,
        capture_output=True,
        text=True,
        errors='replace',
        timeout=30,
        check=False,
    )
    output = result.stdout + '\n' + result.stderr
    assert result.returncode == 0, output
    assert 'FONT_REGRESSION_PASS' in result.stdout, output
