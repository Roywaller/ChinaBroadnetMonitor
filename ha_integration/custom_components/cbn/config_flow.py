"""配置流程：手机号 -> 显示图形验证码 -> 输入两个验证码 -> 登录。

图形验证码采用 **base64 data URI 内嵌**到表单描述里，
不依赖额外 HTTP 路由（避免 HA 路由注册时机的坑）。
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import CbnApiError, CbnCaptchaError, CbnProxyClient
from .const import (
    CONF_ACCESS_NUM,
    CONF_PHONE,
    CONF_PROXY_URL,
    CONF_SESSION_ID,
    DEFAULT_PROXY_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _validate_proxy(hass, proxy_url: str) -> bool:
    """确认代理服务在运行。"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{proxy_url.rstrip('/')}/health",
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                return r.status == 200
    except Exception:
        return False


def _img_data_uri(data: bytes) -> str:
    """把图片字节转成 data URI，可直接用在 markdown 里。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


class CbnConfigFlow(ConfigFlow, domain=DOMAIN):
    """三步：手机号 -> 图形验证码图片 -> 短信验证码"""

    VERSION = 1

    def __init__(self) -> None:
        self._phone: str = ""
        self._proxy: str = DEFAULT_PROXY_URL
        self._session: aiohttp.ClientSession | None = None
        self._captcha: bytes | None = None
        self._image_code: str = ""

    async def _client(self) -> CbnProxyClient:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return CbnProxyClient(self._proxy, self._session)

    async def _close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---------- 步骤 1：手机号 ----------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = user_input[CONF_PHONE].strip()
            proxy = user_input.get(CONF_PROXY_URL, DEFAULT_PROXY_URL).strip()

            if not phone.isdigit() or len(phone) != 11:
                errors["base"] = "invalid_phone"
            elif not await _validate_proxy(self.hass, proxy):
                errors["base"] = "proxy_unreachable"
            else:
                self._phone = phone
                self._proxy = proxy
                await self.async_set_unique_id(phone)
                self._abort_if_unique_id_configured()

                try:
                    client = await self._client()
                    self._captcha = await client.async_get_captcha()
                    return await self.async_step_captcha()
                except CbnApiError as err:
                    _LOGGER.error("获取图形验证码失败: %s", err)
                    errors["base"] = "captcha_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PHONE): str,
                vol.Optional(CONF_PROXY_URL, default=DEFAULT_PROXY_URL): str,
            }),
            errors=errors,
        )

    # ---------- 步骤 2：图形验证码 + 发短信 ----------
    async def async_step_captcha(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("refresh"):
                # 换一张：重新取图（注意会使服务端会话里旧码失效）
                try:
                    client = await self._client()
                    self._captcha = await client.async_get_captcha()
                except CbnApiError:
                    errors["base"] = "captcha_failed"
            else:
                self._image_code = user_input.get("image_code", "").strip()
                if not self._image_code:
                    errors["base"] = "captcha_required"
                else:
                    # 发短信
                    try:
                        client = await self._client()
                        res = await client.async_send_code(self._phone)
                        _LOGGER.info("短信已发送: %s", res.get("message"))
                        return await self.async_step_sms()
                    except CbnApiError as err:
                        _LOGGER.error("发送短信失败: %s", err)
                        errors["base"] = "cannot_send_code"

        return self.async_show_form(
            step_id="captcha",
            data_schema=_captcha_schema(),
            errors=errors,
            description_placeholders={"img_data": _img_data_uri(self._captcha or b"")},
        )

    # ---------- 步骤 3：短信验证码 ----------
    async def async_step_sms(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            sms_code = user_input.get("sms_code", "").strip()
            try:
                client = await self._client()
                res = await client.async_login(self._phone, sms_code, self._image_code)
                data = res.get("data") or {}
                session_id = data.get("sessionId", "")
                if not session_id:
                    errors["base"] = "login_failed"
                else:
                    await self._close()
                    return self.async_create_entry(
                        title=f"中国广电 {data.get('loginPhone') or self._phone}",
                        data={
                            CONF_PHONE: self._phone,
                            CONF_PROXY_URL: self._proxy,
                            CONF_SESSION_ID: session_id,
                            CONF_ACCESS_NUM: data.get("loginPhone") or self._phone,
                        },
                    )
            except CbnCaptchaError:
                # 图形验证码错：重新取图，退回上一步
                _LOGGER.warning("图形验证码错误，刷新后重试")
                try:
                    client = await self._client()
                    self._captcha = await client.async_get_captcha()
                except CbnApiError:
                    pass
                return await self.async_step_captcha()
            except CbnApiError as err:
                _LOGGER.error("登录失败: %s", err)
                errors["base"] = "login_failed"

        return self.async_show_form(
            step_id="sms",
            data_schema=vol.Schema({vol.Required("sms_code"): str}),
            errors=errors,
            description_placeholders={"phone": self._phone},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CbnOptionsFlow(config_entry)


def _captcha_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required("image_code"): str,
        vol.Optional("refresh", default=False): bool,
    })


class CbnOptionsFlow(OptionsFlow):
    """选项流程：重新登录（同样需要图形验证码）。

    注意：ConfigEntry.options 在 HA 里是只读 mappingproxy，
    不能直接赋值。验证码图片临时存放在 hass.data[DOMAIN]["_captcha_b64"]。
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._session: aiohttp.ClientSession | None = None
        self._image_code: str = ""

    @property
    def config_entry(self) -> ConfigEntry:
        return self._entry

    # ---- 验证码临时存放（放在可写的 hass.data 里）----
    @property
    def _store(self) -> dict:
        return self.hass.data.setdefault(DOMAIN, {})

    def _get_captcha_b64(self) -> str:
        return self._store.get("_captcha_b64", "")

    async def _set_captcha(self, cap: bytes) -> str:
        b64 = base64.b64encode(cap).decode()
        self._store["_captcha_b64"] = b64
        return b64

    async def _client(self) -> CbnProxyClient:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        proxy = self._entry.data.get(CONF_PROXY_URL, DEFAULT_PROXY_URL)
        return CbnProxyClient(proxy, self._session)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["relogin"])

    def _placeholders(self, img_data: str) -> dict[str, str]:
        return {
            "phone": self._entry.data[CONF_PHONE],
            "img_data": f"data:image/jpeg;base64,{img_data}" if img_data else "",
        }

    async def async_step_relogin(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        phone = self._entry.data[CONF_PHONE]

        # 首次进入：取验证码
        if not self._get_captcha_b64():
            try:
                client = await self._client()
                await self._set_captcha(await client.async_get_captcha())
            except CbnApiError as err:
                _LOGGER.error("获取验证码失败: %s", err)
                errors["base"] = "captcha_failed"
                return self.async_show_form(
                    step_id="relogin",
                    data_schema=_relogin_schema(),
                    errors=errors,
                    description_placeholders=self._placeholders(""),
                )

        if user_input is not None:
            if user_input.get("refresh"):
                try:
                    client = await self._client()
                    await self._set_captcha(await client.async_get_captcha())
                except CbnApiError:
                    errors["base"] = "captcha_failed"
            else:
                img = user_input.get("image_code", "").strip()
                sms = user_input.get("sms_code", "").strip()

                if not img:
                    errors["base"] = "captcha_required"
                elif not sms:
                    # 第一步只填了图形码：先发短信，再要短信码
                    try:
                        client = await self._client()
                        await client.async_send_code(phone)
                        self._image_code = img
                        return self.async_show_form(
                            step_id="relogin",
                            data_schema=_relogin_schema(need_sms=True),
                            errors={},
                            description_placeholders=self._placeholders(
                                self._get_captcha_b64()),
                        )
                    except CbnApiError as err:
                        _LOGGER.error("发送短信失败: %s", err)
                        errors["base"] = "cannot_send_code"
                else:
                    # 两个码都有：登录
                    try:
                        client = await self._client()
                        res = await client.async_login(phone, sms, img)
                        data = res.get("data") or {}
                        sid = data.get("sessionId", "")
                        if not sid:
                            errors["base"] = "login_failed"
                        else:
                            if self._session and not self._session.closed:
                                await self._session.close()
                            self._store.pop("_captcha_b64", None)
                            new_data = dict(self._entry.data)
                            new_data[CONF_SESSION_ID] = sid
                            new_data[CONF_ACCESS_NUM] = data.get("loginPhone") or phone
                            self.hass.config_entries.async_update_entry(
                                self._entry, data=new_data)
                            return self.async_create_entry(title="", data={})
                    except CbnCaptchaError:
                        # 图形码错：重新取图，留在本步重填
                        _LOGGER.warning("图形验证码错误，刷新后重试")
                        try:
                            client = await self._client()
                            await self._set_captcha(await client.async_get_captcha())
                        except CbnApiError:
                            pass
                        errors["base"] = "captcha_wrong"
                    except CbnApiError as err:
                        _LOGGER.error("登录失败: %s", err)
                        errors["base"] = "login_failed"

        return self.async_show_form(
            step_id="relogin",
            data_schema=_relogin_schema(need_sms=bool(self._image_code)),
            errors=errors,
            description_placeholders=self._placeholders(self._get_captcha_b64()),
        )


def _relogin_schema(need_sms: bool = False) -> vol.Schema:
    fields: dict = {
        vol.Required("image_code"): str,
        vol.Optional("refresh", default=False): bool,
    }
    if need_sms:
        fields[vol.Required("sms_code")] = str
    return vol.Schema(fields)
