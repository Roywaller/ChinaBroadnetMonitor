"""
中国广电 网页版 API 客户端
==========================
逆向自 https://www.10099.com.cn/js/common-85ed7.js

核心发现：网页版 JS 内嵌了【配对的 2048 位公钥 + 私钥】，
因此加密与解密都能在本地完整复现。

方案：RSA_PKCS1v15 分块 + md5 签名
  请求体 = {"data": base64(RSA( urlencode(JSON(params)) ))}
  请求头 = Access: md5(按键排序的 k=v 串联)
  会话   = sessionId 放在 body 参数里（不是 header）

重要：阿里云 WAF 的 acw_sc__v2 JS 挑战必须先通过（见 proxy 方案）。
"""

import base64
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 密钥
# 网页版内嵌的 2048 位配对密钥（公钥加密 / 私钥解密）
PUB_2048 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA4QJmWsYFtBbd/yoySbBAy7pBbfrgHr2SGSOGoBukd65IUqQ9uWhvzCN9r0nWESIXWW6FR2A5adHUFFeETucXGjU61BZxbLLf0ARL4F1NkkFMUF/D3GMY401+6TK8jVMxy4vLb6EKzlyZaI8jKBJ9jh0HMli6U7JHydsXstGRUnyx8Mu11bJ3+ZMUcKe51Zi+85Ez756EdZhGTXSY7pUAvh8/0Fea6mtsOs9OLMHbGMKAOE0alN1QdfqE3QMKgB58MVwlPY7uljelSocjNxCIS58CLvu1iWFrLvsCp8t3DavyA1OD/PPcXRrNLYZgzG5304/LAqfurOpU35AaB5tOnwIDAQAB"
)
PRIV_2048 = (
    "MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDhAmZaxgW0Ft3/KjJJsEDLukFt+uAevZIZI4agG6R3rkhSpD25aG/MI32vSdYRIhdZboVHYDlp0dQUV4RO5xcaNTrUFnFsst/QBEvgXU2SQUxQX8PcYxjjTX7pMryNUzHLi8tvoQrOXJlojyMoEn2OHQcyWLpTskfJ2xey0ZFSfLHwy7XVsnf5kxRwp7nVmL7zkTPvnoR1mEZNdJjulQC+Hz/QV5rqa2w6z04swdsYwoA4TRqU3VB1+oTdAwqAHnwxXCU9ju6WN6VKhyM3EIhLnwIu+7WJYWsu+wKny3cNq/IDU4P889xdGs0thmDMbnfTj8sCp+6s6lTfkBoHm06fAgMBAAECggEAdwFz7TKqtZMamuhQbJTh0F6UWHzFqLyO1ujpPSkhlYMCEWN4meVYq9lhkiI1LB6hxtUjfJqyAvvNdWzMN4cVuvDISoAMQXdh1H1RPDtc2avblu7vglKPSTkllGUXQI/t2D/5uvKr6nUjVh/OclVFPrKvqbsv4TB7s5FDOXqJp9v5jhJOs8fmS1eA5wL4SuvwfXqxVU+e7DCL21hWICLsFLpysvsmfcToPMZ9og7KZG4nHkEBMTZ6HVBS3RnayFcF6Q7kIqkKrIeIFb88R81PnH1xXhBr9k7Mgm6l+wxtWRhhdQsjDY542c1Buh7eBcE7rdClUPucyyv3w9vKgDngIQKBgQD6YcWcguASxL2IYSIdZNCqEey0I8MdPsJ5OfCrkrOQnEUCQCLEyZUcfGxr1+VsGvIfNSLVLiZJVEvB7tsUb+OLmlElDycMfKzvAPEsbh/UKryeAZF4VJeNOeYuT10z2OMxsxh1tmkOdobaK4eIUxr7CpUNa2v2DDYithB0GshzyQKBgQDmDuJve7+bFSbB6aZCuJFnIcF1pgGR/jiTbMqJmvm8LVNpu8SQdd1fQX1/szOjtzfiXGWrlkBNQIlYOi2iWnyRBQYHXQeji/zcCIJCTXDsEYtFj3A4ovJZUUZW7N0aUq7h+zQCWZ2H/Iq8SPeA1OnGJV78CAzLJ/kcjZd4sgvTJwKBgGIBpW1nGTifhCT/CHCDBt6bV5EHspce+tai5F70dI81bBm+ax2mXlShK3tnLemL/pxSm0jg4KGxeln2GhE83s/FXt/nt3w+zR5cuwqOLK1K8TvUF1IHoq7oK/6SmEP0MLJCjV9+QE8l/BEoGsw044nCkaeIFeFg1EvwAi7AURhpAoGASgJBz/F0a1R7mmgq503u4MmYLdvQp4Gr+6lE4s2rR2Ehc2NHUd3I8GrmD527oBBB9x0YTAHS/8ciJ/LXWWJYrmJ6VQYVfgR7vOEz3laBXEAsmJ0TUfUBl8Awq6gZXO16exJP4e2oYuXYT8f9b0GPTwIYs2V3kCd02T2nm9lTOoMCgYB9sbBXCnnuht0TCA88cZtSKDRa1YtgdYCjSq6xClvhnKa1bh+Ldfp5GVF4CLsEvgHgQS5QWh6pWO6wH0GOrr13SdgT50AwInmpdvqnD37kP1goyMtITiKxI6gNwbSsDMaGpJNSGzHFQR1Wy3iQ+r6XI/pSFZDhK6PFjUVVwbRFQw=="
)

# 网页版参数（已从真实流量确认）
BASE = "https://www.10099.com.cn/contact-web/api"
CHANNEL_ID = "cd_20220516_093342"
API_V = "1.1.7.0915_release"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")


# ---------------------------------------------------------------- DER
def _b64d(x):
    x = "".join(x.split())
    return base64.b64decode(x + "=" * (-len(x) % 4))


def _tlvs(b):
    out, i = [], 0
    while i < len(b):
        tag = b[i]; i += 1
        ln = b[i]; i += 1
        if ln & 0x80:
            n = ln & 0x7F
            ln = int.from_bytes(b[i:i + n], "big"); i += n
        out.append((tag, b[i:i + ln])); i += ln
    return out


def _parse_pub(b64txt):
    seq = _tlvs(_b64d(b64txt))[0][1]
    bit = [v for t, v in _tlvs(seq) if t == 0x03][0][1:]
    v = [int.from_bytes(c, "big") for t, c in _tlvs(_tlvs(bit)[0][1]) if t == 0x02]
    return {"n": v[0], "e": v[1]}


def _parse_priv(b64txt):
    seq = _tlvs(_b64d(b64txt))[0][1]
    octet = [v for t, v in _tlvs(seq) if t == 0x04][0]
    inner = _tlvs(octet)
    if inner and inner[0][0] == 0x30:
        inner = _tlvs(inner[0][1])
    v = [int.from_bytes(c, "big") for t, c in inner if t == 0x02]
    return {"ver": v[0], "n": v[1], "e": v[2], "d": v[3]}


_PUB = _parse_pub(PUB_2048)
_PRIV = _parse_priv(PRIV_2048)


# ---------------------------------------------------------------- crypto
def _pad(msg, k):
    if len(msg) > k - 11:
        raise ValueError("chunk too long")
    ps = bytearray()
    while len(ps) < k - 3 - len(msg):
        b = os.urandom(1)[0]
        if b:
            ps.append(b)
    return b"\x00\x02" + bytes(ps) + b"\x00" + msg


def _unpad(em):
    if em[0] != 0x00 or em[1] != 0x02:
        raise ValueError(f"bad PKCS#1 header {em[:2].hex()}")
    return em[em.find(b"\x00", 2) + 1:]


def encrypt_long(plaintext, key=None):
    """等价 JS encryptLong：按 UTF-16 charCode 长度分块 + PKCS1v15"""
    key = key or _PUB
    n, e = key["n"], key["e"]
    k = (n.bit_length() + 7) // 8
    limit = k - 12                      # JS 用 k-12，保守 1 字节
    out = bytearray()
    start = cur = 0
    for i, ch in enumerate(plaintext):
        c = ord(ch)
        clen = 1 if c <= 127 else 2 if c <= 2047 else 3 if c <= 65535 else 4
        cur += clen
        if cur > limit:
            m = int.from_bytes(_pad(plaintext[start:i].encode(), k), "big")
            out += pow(m, e, n).to_bytes(k, "big")
            start, cur = i, clen
    m = int.from_bytes(_pad(plaintext[start:].encode(), k), "big")
    out += pow(m, e, n).to_bytes(k, "big")
    return base64.b64encode(bytes(out)).decode()


def decrypt_long(cipher_b64, key=None):
    key = key or _PRIV
    n, d = key["n"], key["d"]
    k = (n.bit_length() + 7) // 8
    raw = _b64d(cipher_b64)
    out = b""
    for i in range(0, len(raw), k):
        ch = raw[i:i + k]
        if len(ch) < k:
            break
        out += _unpad(pow(int.from_bytes(ch, "big"), d, n).to_bytes(k, "big"))
    return out.decode("utf-8", "replace")


def make_sign(params):
    """Access = md5(递归按 key 排序的 k=v 串联)"""
    def conv(o, nested=False):
        if not isinstance(o, dict) or not o:
            return ""
        parts = []
        for k in sorted(o.keys()):
            v = o[k]
            if isinstance(v, dict) and not nested:
                parts.append(f"{k}={conv(v, True)}")
            elif v is not None and v != "" and not isinstance(v, (dict, list)):
                parts.append(f"{k}={v}")
        return "&".join(parts)
    return hashlib.md5(conv(params).encode()).hexdigest()


def build_payload(params):
    """返回 (body_dict, access_header)"""
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["v"] = API_V
    p.setdefault("channelId", CHANNEL_ID)
    body = {"data": encrypt_long(urllib.parse.quote(
        json.dumps(p, separators=(",", ":"), ensure_ascii=False)))}
    return body, make_sign(p)


def parse_response(text):
    """解析响应；若 data 是加密串则自动解密"""
    j = json.loads(text)
    d = j.get("data")
    if isinstance(d, str) and len(d) > 80:
        try:
            j["data"] = json.loads(urllib.parse.unquote(decrypt_long(d)))
        except Exception:
            pass
    return j


# ---------------------------------------------------------------- client
class CbnWeb:
    """直连客户端。

    注意：必须通过已过 WAF 挑战的会话（例如本地代理服务）才能成功，
    直接裸连会被阿里云 WAF 用 acw_sc__v2 挑战页拦下。
    """

    def __init__(self, session_id="", access_num="", base=None, timeout=25):
        self.session_id = session_id
        self.access_num = access_num
        self.base = base or BASE
        self.timeout = timeout

    def post(self, path, params=None):
        body, access = build_payload(params or {})
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Access": access,
                "User-Agent": UA,
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://www.10099.com.cn",
                "Referer": "https://www.10099.com.cn/login.html",
            }, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return parse_response(r.read().decode("utf-8", "replace"))

    # ---- 业务接口 ----
    def send_code(self, phone, type_=5):
        return self.post("/login/getVerifyCode", {"recieveNum": phone, "type": type_})

    def login(self, phone, code, image_check_code=""):
        r = self.post("/login/gwLogin", {
            "loginPhone": phone,
            "loginPassWord": code,
            "loginType": "5",
            "channelType": "1",
            "imageCheckCode": image_check_code,
        })
        if r.get("status") == "000000":
            d = r.get("data") or {}
            self.session_id = d.get("sessionId", "")
            self.access_num = d.get("loginPhone") or phone
        return r

    def _authed(self, path, extra=None):
        p = {"sessionId": self.session_id, "accessNum": self.access_num}
        if extra:
            p.update(extra)
        return self.post(path, p)

    def query_flow(self):
        """套餐余量（含流量 balance/highFee，单位字节）"""
        return self._authed("/busi/qryUserRes")

    def query_balance(self):
        """余额与当月消费（单位分）"""
        return self._authed("/busi/qryBalanceFee")

    def query_bill(self):
        return self._authed("/busi/qryBillInfo")

    def query_pack(self):
        return self._authed("/busi/qryPhonePackInfo")


# ---------------------------------------------------------------- 汇总
def summarize_flow(resp):
    """把 qryUserRes 原始响应整理成 总量/已用/剩余"""
    bean = ((resp.get("data") or {}).get("intfResultBean") or {})
    items = bean.get("userResList") or []
    used = total = 0
    detail = []
    for it in items:
        try:
            hi = int(it.get("highFee") or 0)
            bal = int(it.get("balance") or 0)
        except (TypeError, ValueError):
            continue
        name = it.get("discntName") or ""
        detail.append({"name": name, "total": hi, "left": bal,
                       "used": max(0, hi - bal), "end": it.get("endTime")})
        total += hi
        used += max(0, hi - bal)
    return {"total_bytes": total, "used_bytes": used,
            "left_bytes": max(0, total - used), "items": detail}


def summarize_balance(resp):
    """qryBalanceFee -> 元为单位的余额/当月消费"""
    bean = ((resp.get("data") or {}).get("intfResultBean") or {})
    def fen(x):
        try:
            return int(x) / 100.0
        except (TypeError, ValueError):
            return 0.0
    return {"balance_yuan": fen(bean.get("balance")),
            "month_fee_yuan": fen(bean.get("currealFee")),
            "cycle": bean.get("curCycleId"),
            "as_of": bean.get("xsysdate")}


if __name__ == "__main__":
    print("=== 自检 ===")
    print("密钥配对:", _PUB["n"] == _PRIV["n"])
    rt = "roundtrip-中文-test-12345"
    print("加解密往返:", decrypt_long(encrypt_long(rt)) == rt)

    CAP = "zZ7SCjpGeMRlzdBGjGShc4CgU2tOmRuTVGc8p6v/unVRZhmersk9E9Xtgi1osj5sw7Svvfq1hI801r75T1PK15D/fd1bPI6JwPw9CwaiCN4wE3Htrv1Z6NzRhl+//cSvfy4l7dO8Rt0DQmyvwN5sUSoDS5At5Ek9jfc55J9E+8NRKYRszaWHPnWEOVnzZw6oeGPd1ZUSeF26oqXbti3gue4HKnxbrpSnSL9y3Hy4G6BG6Xf0W9q2XHC4S230OHnefARAEwS0Zh5II30HfHF9Z5l1h3Mq9suCZ3qG/oE0Jm33Hr02E2Jp15hIzcLlzNlDqBa/FMg2XpF8Q9RD7MZ0N68ZftUlF/R/N5kOnOvv8h0Ytk+ddf5Py8dIyWDd2xTzHm/oEKZ+RmyibpfRvXsXhLNEzOWasEPFJLrBQhXKAepL/X79a1xHvcHYjzh/rufWzEiWtieiOL5N2HdrZQccyMZKLuQzEZnwfigWnQ2ViZYbPmpsVs7ntoZbD2kr7wfX/E87IJhN7fgRzFvl9i5FILvbTTlhKkSFXP5pzUGOYE71os/ZtXJmUOxIBcHeLxwjCIThIU2xiX9oMzK+8Ra5j4FoIPrDeQOI7yDoXZXMTdgqs+5iJRYSaKE7YdZ5tTpo9WO9xMS2eUtBNKGzCeaTbDvkVnnJzzlFCJe+v98ILMo="
    print("真实抓包解密:", urllib.parse.unquote(decrypt_long(CAP)))
    print()
    b, a = build_payload({"recieveNum": "19286832590", "type": 5})
    print("生成密文长度:", len(_b64d(b["data"])), "字节")
    print("Access:", a)
