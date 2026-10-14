"""Проверки разрешений удалённых ресурсов без сети и настоящих окон Qt."""

from itertools import product
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
)
from PySide6.QtWidgets import QDialog

from src.course_reader.remote_settings import RemoteResourcesSettings
from src.course_reader.storage import Store
from src.course_reader.viewer import OfflineInterceptor, Page
from src.course_reader.window import Window

KEYS = ("enabled", "images", "styles", "fonts")
FLAGS = list(product((False, True), repeat=4))
TYPES = QWebEngineUrlRequestInfo.ResourceType
SELECTABLE = {
    "images": TYPES.ResourceTypeImage,
    "styles": TYPES.ResourceTypeStylesheet,
    "fonts": TYPES.ResourceTypeFontResource,
}


def policy(flags):
    result = SimpleNamespace(allowed_types=frozenset())
    result.configure = lambda **values: OfflineInterceptor.configure(
        cast(OfflineInterceptor, result), **values
    )
    result.configure(**dict(zip(KEYS, flags, strict=False)))
    return result


def blocked(interceptor, address, kind, method=b"GET"):
    calls: list[bool] = []
    request = SimpleNamespace(
        requestUrl=lambda: QUrl(address),
        resourceType=lambda: kind,
        requestMethod=lambda: QByteArray(method),
        block=calls.append,
    )
    OfflineInterceptor.interceptRequest(
        interceptor, cast(QWebEngineUrlRequestInfo, request)
    )
    return calls == [True]


@pytest.mark.parametrize("flags", FLAGS)
@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("kind", list(TYPES))
def test_only_selected_webengine_types_can_load(flags, scheme, kind):
    expected = flags[0] and any(
        selected and kind == SELECTABLE[key]
        for key, selected in zip(KEYS[1:], flags[1:], strict=False)
    )
    interceptor = policy(flags)
    assert isinstance(interceptor.allowed_types, frozenset)
    assert (
        blocked(interceptor, scheme + "://example.test/resource.png", kind)
        is not expected
    )


@pytest.mark.parametrize(
    "method", [b"POST", b"PUT", b"DELETE", b"HEAD", b"OPTIONS", b"get", b""]
)
@pytest.mark.parametrize("kind", list(SELECTABLE.values()))
def test_selected_types_cannot_send_non_get_requests(method, kind):
    assert blocked(policy((True,) * 4), "https://example.test/image.png", kind, method)


@pytest.mark.parametrize(
    "address",
    [
        "file:///C:/course/page.html",
        "data:image/png;base64,AA==",
        "blob:https://example.test/id",
        "qrc:/resource",
        "about:blank",
    ],
)
@pytest.mark.parametrize("flags", [(False,) * 4, (True,) * 4])
def test_local_schemes_keep_existing_permissions(address, flags):
    assert not blocked(policy(flags), address, TYPES.ResourceTypeScript, b"POST")


@pytest.mark.parametrize(
    "scheme", ["ws", "wss", "ftp", "mailto", "javascript", "custom"]
)
def test_other_schemes_remain_blocked_with_every_type_enabled(scheme):
    assert blocked(
        policy((True,) * 4),
        scheme + "://example.test/image.png",
        TYPES.ResourceTypeImage,
    )


@pytest.mark.parametrize("suffix", ["png", "css", "woff2"])
@pytest.mark.parametrize(
    "kind",
    [TYPES.ResourceTypeScript, TYPES.ResourceTypeXhr, TYPES.ResourceTypeSubFrame],
)
def test_resource_suffix_cannot_bypass_type_filter(suffix, kind):
    assert blocked(
        policy((True,) * 4), "https://example.test/disguised." + suffix, kind
    )


def test_reconfiguration_revokes_previous_permissions():
    interceptor = policy((True, True, False, False))
    previous = interceptor.allowed_types
    interceptor.configure(enabled=True, images=False, styles=True, fonts=False)
    assert previous == frozenset([TYPES.ResourceTypeImage])
    assert blocked(interceptor, "https://example.test/image", TYPES.ResourceTypeImage)
    assert not blocked(
        interceptor, "https://example.test/style", TYPES.ResourceTypeStylesheet
    )
    interceptor.configure(enabled=False, images=True, styles=True, fonts=True)
    assert interceptor.allowed_types == frozenset()


@pytest.mark.parametrize(
    "legacy", ["", "[app]\ninternet_links = true\nvisible_patterns = *.html\n"]
)
def test_defaults_and_legacy_ini_do_not_enable_network_or_write(tmp_path, legacy):
    path = tmp_path / "settings.ini"
    if legacy:
        path.write_text(legacy, encoding="utf-8")
    store = Store(tmp_path)
    assert dict(store.settings["remote_resources"]) == {
        "enabled": "false",
        "images": "true",
        "styles": "true",
        "fonts": "true",
    }
    assert set(tmp_path.iterdir()) == ({path} if legacy else set())
    if legacy:
        assert path.read_text(encoding="utf-8") == legacy


@pytest.mark.parametrize("field", KEYS)
def test_partial_resource_section_fills_only_missing_fields(tmp_path, field):
    value = "true" if field == "enabled" else "false"
    path = tmp_path / "settings.ini"
    original = f"[remote_resources]\n{field} = {value}\n"
    path.write_text(original, encoding="utf-8")
    section = Store(tmp_path).settings["remote_resources"]
    assert section[field] == value
    for other in set(KEYS) - {field}:
        assert section.getboolean(other) is (other != "enabled")
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("field", KEYS)
@pytest.mark.parametrize("value", ["perhaps", "", "2"])
def test_invalid_resource_boolean_preserves_ini(tmp_path, field, value):
    path = tmp_path / "settings.ini"
    original = f"[remote_resources]\n{field} = {value}\n".encode()
    path.write_bytes(original)
    with pytest.raises(ValueError, match=r"Некорректный settings\.ini:"):
        Store(tmp_path)
    assert path.read_bytes() == original
    assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize("flags", FLAGS)
def test_resource_choices_roundtrip_without_affecting_internet_links(tmp_path, flags):
    store = Store(tmp_path)
    values = {key: str(value).lower() for key, value in zip(KEYS, flags, strict=False)}
    store.settings["remote_resources"].update(values)
    store.save()
    restored = Store(tmp_path)
    assert dict(restored.settings["remote_resources"]) == values
    assert restored.settings.getboolean("app", "internet_links") is False


@pytest.mark.parametrize("flags", FLAGS)
@pytest.mark.parametrize("internet_links", [False, True])
def test_window_applies_policy_and_remote_attribute_independently(
    tmp_path, flags, internet_links
):
    store = Store(tmp_path)
    store.settings["app"]["internet_links"] = str(internet_links).lower()
    store.settings["remote_resources"].update(
        {key: str(value).lower() for key, value in zip(KEYS, flags, strict=False)}
    )
    attributes = []
    state = SimpleNamespace(
        store=store,
        interceptor=policy((False,) * 4),
        page=SimpleNamespace(
            settings=lambda: SimpleNamespace(
                setAttribute=lambda *args: attributes.append(args)
            )
        ),
    )
    Window.apply_remote_resources(cast(Window, state))
    assert attributes == [
        (
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            flags[0] and any(flags[1:]),
        )
    ]
    for key, enabled in zip(KEYS[1:], flags[1:], strict=False):
        assert (SELECTABLE[key] in state.interceptor.allowed_types) is (
            flags[0] and enabled
        )
    assert store.settings.getboolean("app", "internet_links") is internet_links


@pytest.mark.parametrize("main_frame", [False, True])
def test_remote_resources_never_enable_internet_navigation(main_frame):
    signals: list[str] = []
    state = SimpleNamespace(
        internet_requested=SimpleNamespace(emit=signals.append),
        allowed_types=policy((True,) * 4).allowed_types,
    )
    assert (
        Page.acceptNavigationRequest(
            cast(Page, state),
            QUrl("https://example.test/page"),
            QWebEnginePage.NavigationType.NavigationTypeLinkClicked,
            main_frame,
        )
        is False
    )
    assert signals == (["https://example.test/page"] if main_frame else [])


@pytest.mark.parametrize("selected", list(product((False, True), repeat=3)))
def test_widget_toggle_retains_choices_and_changes_explanation(selected):
    state = SimpleNamespace(
        on=MagicMock(),
        options=MagicMock(),
        warning=MagicMock(),
        message=MagicMock(),
        checks={key: MagicMock() for key in KEYS[1:]},
    )
    for check, value in zip(state.checks.values(), selected, strict=False):
        check.isChecked.return_value = value
    for enabled in (True, False, True):
        state.on.isChecked.return_value = enabled
        RemoteResourcesSettings.update_message(cast(RemoteResourcesSettings, state))
        state.options.setEnabled.assert_called_with(enabled)
        state.warning.setVisible.assert_called_with(enabled)
        text = state.message.setText.call_args.args[0]
        if not enabled:
            assert text == "Загрузка ресурсов из интернета заблокирована"
        elif any(selected):
            assert "разрешена" in text and "внешним серверам" in text
        else:
            assert "Типы ресурсов не выбраны" in text
        assert RemoteResourcesSettings.values(cast(RemoteResourcesSettings, state)) == {
            key: str(value).lower()
            for key, value in zip(KEYS, (enabled, *selected), strict=False)
        }
    for check in state.checks.values():
        check.setChecked.assert_not_called()


@pytest.mark.parametrize("accepted", [False, True])
def test_settings_dialog_commits_resources_only_on_apply(
    tmp_path, monkeypatch, accepted
):
    import src.course_reader.window as module

    store = Store(tmp_path)
    original = dict(store.settings["remote_resources"])
    new_values = {
        "enabled": "true",
        "images": "false",
        "styles": "true",
        "fonts": "false",
    }
    real_dialog = QDialog
    dialog_factory = MagicMock()
    dialog_factory.DialogCode = real_dialog.DialogCode
    dialog_factory.return_value.exec.return_value = (
        real_dialog.DialogCode.Accepted if accepted else real_dialog.DialogCode.Rejected
    )
    monkeypatch.setattr(module, "QDialog", dialog_factory)
    widget_factories: dict[str, MagicMock] = {}
    for name in (
        "QFormLayout",
        "QCheckBox",
        "QLineEdit",
        "QComboBox",
        "QWidget",
        "QHBoxLayout",
        "QDialogButtonBox",
        "style_checkbox",
    ):
        widget_factories[name] = MagicMock()
        monkeypatch.setattr(module, name, widget_factories[name])
    widget_factories["QLineEdit"].side_effect = lambda value: MagicMock(
        text=lambda: value
    )
    widget_factories["QCheckBox"].return_value.isChecked.return_value = False
    widget_factories["QComboBox"].return_value.currentData.return_value = "dark"
    resources = MagicMock()
    resources.return_value.values.return_value = new_values
    monkeypatch.setattr(module, "RemoteResourcesSettings", resources)
    applied = []
    state = SimpleNamespace(
        store=store,
        persist=MagicMock(),
        apply_theme=MagicMock(),
        rebuild=MagicMock(),
        apply_remote_resources=lambda: applied.append(
            dict(store.settings["remote_resources"])
        ),
    )
    Window.settings_dialog(cast(Window, state))
    assert dict(store.settings["remote_resources"]) == (
        new_values if accepted else original
    )
    assert applied == ([new_values] if accepted else [])
    assert state.persist.call_count == int(accepted)
    assert state.apply_theme.call_count == int(accepted)
    assert state.rebuild.call_count == int(accepted)
    assert set(tmp_path.iterdir()) == set()
