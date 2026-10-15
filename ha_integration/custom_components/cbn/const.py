"""常量定义。"""

DOMAIN = "cbn"

CONF_PROXY_URL = "proxy_url"
CONF_PHONE = "phone"
CONF_SESSION_ID = "session_id"
CONF_ACCESS_NUM = "access_num"

DEFAULT_PROXY_URL = "http://127.0.0.1:8787"
DEFAULT_SCAN_INTERVAL = 1800          # 30 分钟，避免触发风控

PLATFORMS = ["sensor"]

ATTR_FLOW_DETAIL = "flow_items"
