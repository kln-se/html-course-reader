"""Собрать QtGui без неиспользуемого плагина виртуальной клавиатуры."""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# Фильтруем плагин до анализа DLL-зависимостей, сохраняя прочие плагины QtGui.
binaries = [
    (source, destination)
    for source, destination in binaries
    if Path(source).name.casefold() != "qtvirtualkeyboardplugin.dll"
]
