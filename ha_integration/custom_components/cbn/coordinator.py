"""数据协调器：定期拉取流量、套餐、余额。"""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CbnApiError, CbnAuthError, CbnProxyClient
from .const import (
    CONF_ACCESS_NUM,
    CONF_PHONE,
    CONF_PROXY_URL,
    CONF_SESSION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .parse import summarize_balance, summarize_flow, summarize_pack

_LOGGER = logging.getLogger(__name__)


class CbnCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.phone: str = entry.data[CONF_PHONE]
        self.proxy_url: str = entry.data[CONF_PROXY_URL]
        self._session: aiohttp.ClientSession | None = None
        self.api: CbnProxyClient | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_setup(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self.api = CbnProxyClient(self.proxy_url, self._session)

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _async_update_data(self) -> dict:
        await self._async_setup()
        assert self.api is not None

        sess = (self.entry.options.get(CONF_SESSION_ID)
                or self.entry.data.get(CONF_SESSION_ID, ""))
        acct = (self.entry.options.get(CONF_ACCESS_NUM)
                or self.entry.data.get(CONF_ACCESS_NUM, self.phone))
        if not sess:
            raise UpdateFailed("尚未登录，请在集成选项中完成登录")

        try:
            flow_raw = await self.api.async_flow(sess, acct)
            bal_raw = await self.api.async_balance(sess, acct)
            pack_raw = await self.api.async_pack(sess, acct)
        except CbnAuthError as err:
            raise UpdateFailed(f"登录态失效：{err}") from err
        except CbnApiError as err:
            raise UpdateFailed(str(err)) from err

        try:
            return {
                "phone": self.phone,
                "flow": summarize_flow(flow_raw),
                "balance": summarize_balance(bal_raw),
                "pack": summarize_pack(pack_raw),
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("解析响应失败")
            raise UpdateFailed(f"解析响应失败：{err}") from err
