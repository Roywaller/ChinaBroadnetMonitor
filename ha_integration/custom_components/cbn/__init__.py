"""中国广电 HASS 集成。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, CoreState, EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, CONF_PROXY_URL, DEFAULT_PROXY_URL, PLATFORMS

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Optional("proxy_url", default=DEFAULT_PROXY_URL): cv.url})},
    extra=vol.ALLOW_EXTRA,
)

URL_BASE = "/cbn-local"
CARD_FILENAME = "cbn-card.js"

_STATIC_REGISTERED = False


def _card_version() -> str:
    """用文件 mtime 做缓存失效，避免浏览器拿到旧版卡片。"""
    try:
        p = Path(__file__).parent / "www" / CARD_FILENAME
        return str(int(p.stat().st_mtime))
    except OSError:
        return "1"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """注册前端卡片资源。"""
    hass.data.setdefault(DOMAIN, {})
    await _register_static_and_js(hass)

    async def _register_lovelace_storage(_event=None) -> None:
        await _register_lovelace_resource(hass)

    if hass.state == CoreState.running:
        await _register_lovelace_storage()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_lovelace_storage)

    return True


async def _register_static_and_js(hass: HomeAssistant) -> None:
    global _STATIC_REGISTERED
    if _STATIC_REGISTERED:
        return
    _STATIC_REGISTERED = True
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(URL_BASE, str(Path(__file__).parent / "www"), False),
        ])
    except RuntimeError:
        _LOGGER.debug("静态路径已注册: %s", URL_BASE)

    ver = _card_version()
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}?v={ver}")
    _LOGGER.info("cbn: 已注册前端卡片资源 %s/%s?v=%s", URL_BASE, CARD_FILENAME, ver)


async def _register_lovelace_resource(hass: HomeAssistant) -> None:
    lovelace = hass.data.get("lovelace")
    if not lovelace or not hasattr(lovelace, "resources") or lovelace.resources is None:
        return

    ver = _card_version()
    url = f"{URL_BASE}/{CARD_FILENAME}?v={ver}"
    url_base = f"{URL_BASE}/{CARD_FILENAME}"

    async def _check_and_register(_now=None) -> None:
        try:
            if not lovelace.resources.loaded:
                async_call_later(hass, 3, _check_and_register)
                return
            existing = [r for r in lovelace.resources.async_items()
                        if r["url"].startswith(URL_BASE)]
            for resource in existing:
                # 已存在：若版本变了就更新（缓存失效）
                if resource["url"] == url:
                    return
                if resource["url"].split("?")[0] == url_base:
                    _LOGGER.info("更新卡片资源版本: %s -> %s", resource["url"], url)
                    await lovelace.resources.async_update_item(
                        resource["id"], {"res_type": "module", "url": url})
                    return
            _LOGGER.info("持久化注册前端卡片: %s", url)
            await lovelace.resources.async_create_item(
                {"res_type": "module", "url": url})
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("Lovelace 资源注册失败: %s", ex)

    await _check_and_register()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # 前端卡片注册放这里：async_setup() 对纯 config-flow 集成不保证被调用，
    # 而 async_setup_entry() 一定会在配置项建立时执行。
    await _ensure_card(hass)

    from .coordinator import CbnCoordinator

    coordinator = CbnCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(coordinator.async_shutdown)
    return True


async def _ensure_card(hass: HomeAssistant) -> None:
    """注册静态路径 + 卡片资源（两种方式都做，确保生效）。"""
    await _register_static_and_js(hass)

    async def _later(_now=None) -> None:
        await _register_lovelace_resource(hass)

    if hass.state == CoreState.running:
        await _later()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _later)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
