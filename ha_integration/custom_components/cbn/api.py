"""调用本地代理服务的 API 客户端。"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class CbnApiError(Exception):
    """API 调用异常。"""


class CbnAuthError(CbnApiError):
    """登录态失效（需要重新登录）。"""


class CbnCaptchaError(CbnApiError):
    """图形验证码问题。"""


# 服务端错误码 -> 可读信息
ERROR_MESSAGES = {
    "719": "图形验证码不能为空，请重新获取图片并填写",
    "720": "图形验证码有误，已为你刷新，请重新填写",
    "701": "登录已过期，请重新登录",
}


class CbnProxyClient:
    """通过本地 Playwright 代理访问广电接口。

    代理负责：真实浏览器过 WAF 挑战、RSA 加密、md5 签名。
    """

    def __init__(self, proxy_url: str, session: aiohttp.ClientSession) -> None:
        self._base = proxy_url.rstrip("/")
        self._session = session

    async def async_get_captcha(self) -> bytes:
        """取图形验证码图片（JPEG/PNG 字节）。"""
        url = f"{self._base}/captcha"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise CbnApiError(f"获取验证码失败 HTTP {resp.status}: {body[:200]}")
                return await resp.read()
        except aiohttp.ClientError as err:
            raise CbnApiError(f"无法连接本地代理 {url}: {err}") from err

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}{path}"
        try:
            async with self._session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise CbnApiError(f"代理返回 HTTP {resp.status}: {body[:200]}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise CbnApiError(f"无法连接本地代理 {url}: {err}") from err

        status = str(data.get("status", ""))
        if status == "701":
            raise CbnAuthError(ERROR_MESSAGES["701"])
        if status in ("719", "720"):
            raise CbnCaptchaError(ERROR_MESSAGES[status])
        if status and status != "000000":
            raise CbnApiError(data.get("message") or f"接口返回 {status}")
        return data

    async def async_send_code(self, phone: str) -> dict[str, Any]:
        return await self._post("/send_code", {"phone": phone})

    async def async_login(self, phone: str, sms_code: str,
                          image_code: str) -> dict[str, Any]:
        return await self._post("/login", {
            "phone": phone, "code": sms_code, "image_code": image_code,
        })

    async def async_flow(self, session_id: str, access_num: str) -> dict[str, Any]:
        return await self._post("/flow", {
            "sessionId": session_id, "accessNum": access_num,
        })

    async def async_balance(self, session_id: str, access_num: str) -> dict[str, Any]:
        return await self._post("/balance", {
            "sessionId": session_id, "accessNum": access_num,
        })

    async def async_pack(self, session_id: str, access_num: str) -> dict[str, Any]:
        return await self._post("/pack", {
            "sessionId": session_id, "accessNum": access_num,
        })
