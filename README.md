# ChinaBroadnetMonitor

中国广电（China Broadnet）**话费 / 流量监控** —— Home Assistant 自定义集成。

在 Home Assistant 里输入手机号 + 短信验证码登录，自动获取剩余流量、账户余额、当月消费，
并附带一张联通风格的自定义 Lovelace 卡片。

---

## 功能

- **登录**：手机号 → 图形验证码 → 短信验证码（全流程在 HA 界面完成）
- **11 个传感器**：
  - 本月总流量、本月已用流量、剩余流量、流量使用率
  - 结转剩余流量、语音已用、短信已用
  - 当前套餐、套餐月费、账户余额、当月消费
- **自定义卡片**：四宫格 + 进度条 + 三个折叠明细，含官方 logo
- **明细属性**：逐条列出每个流量包的总量 / 已用 / 剩余 / 到期时间

---

## 快速开始

### 1. 部署代理服务

广电的接口有两层防护，纯 HTTP 脚本无法直接调用：

1. **阿里云 WAF** 的 `acw_sc__v2` JS 挑战 —— 非浏览器一律返回挑战页
2. **RSA 加密请求体** —— 需用内嵌在网页 JS 里的 2048 位公钥

因此需要一个常驻的 **本地代理**：用真实浏览器通过 WAF，再发送加密请求。

```bash
cd proxy
npm install playwright-core
# 启动（可用环境变量覆盖）
CBN_PORT=8787 CBN_CHROME=/usr/bin/chromium node cbn_proxy.js
```

需要 **Node.js ≥ 20** 和 Chrome/Chromium。

> 主机用 systemd 常驻、开机自启：
> ```ini
> [Unit]
> Description=China Broadnet proxy
> After=network-online.target
>
> [Service]
> Type=simple
> User=pi
> WorkingDirectory=/home/pi/cbn_login
> Environment=PATH=/usr/local/bin:/usr/bin:/bin
> Environment=CBN_PORT=8787
> Environment=CBN_CHROME=/usr/bin/chromium
> ExecStart=/usr/local/bin/node /home/pi/cbn_login/cbn_proxy.js
> Restart=always
>
> [Install]
> WantedBy=multi-user.target
> ```

### 2. 安装集成

```bash
cp -r ha_integration/custom_components/cbn \
      <HA配置目录>/custom_components/
```
然后**重启 Home Assistant**（首次安装 brand/ 图标需要重启生效）。

### 3. 添加集成

**设置 → 设备与服务 → 添加集成 → 搜索「中国广电」**

流程（三步）：
1. 输入手机号，代理地址默认 `http://127.0.0.1:8787`
2. 界面**直接显示图形验证码图片**，识别图上 4 位字符填入
   - 看不清可勾选**「换一张」**再提交
3. 手机会收到短信，输入**短信验证码** → 完成

> ⚠️ 图形验证码**与浏览器会话绑定**，且服务端每次请求都会生成新码（新码作废旧码）。
> 所以三步必须在**同一次配置流程**内完成，中途不要去刷新别的页面。

### 4. 添加卡片

**仪表盘 → 编辑 → 添加卡片 →「自定义」分组 →「中国广电卡片」**

或手动填 YAML：

```yaml
type: custom:cbn-card
title: 中国广电
balance_warning_below: 20      # 余额低于此值标橙
usage_warning_percent: 80      # 使用率 >=80% 进度条变黄
usage_danger_percent: 95       # >=95% 变红
show_details: true             # 默认展开各组明细
```

「本月流量」进度条右侧有一个 **日均可用** 徽标，表示：

```
日均可用 = 剩余流量 ÷ 本月剩余天数（含今天）
```

这个值是**前端按自然月实时计算**的，不依赖后端新增传感器，所以换月后会自动重置。
鼠标悬停徽标可看到当前用的是"剩余几天"。


集成会自动注册卡片资源（含缓存失效的 `?v=` 参数），**无需手动添加 Lovelace 资源**。

---

## 目录结构

```
ChinaBroadnetMonitor/
├── README.md
├── .gitignore
├── cbn_web.py                    纯 Python 客户端：RSA + md5 签名 + 响应解密
├── ha_integration/
│   └── custom_components/cbn/
│       ├── __init__.py           卡片资源注册 + config entry 装配
│       ├── config_flow.py        三步登录向导（图形验证码 base64 内嵌）
│       ├── api.py                代理客户端（719/720/701 错误码处理）
│       ├── coordinator.py        轮询调度
│       ├── parse.py              字段解析（个人/结转分离）
│       ├── sensor.py             11 个传感器定义
│       ├── manifest.json
│       ├── strings.json
│       ├── translations/
│       ├── brand/                集成图标（HA 启动时读取）
│       └── www/                  Lovelace 卡片 + logo
└── proxy/
    ├── cbn_proxy.js              WAF + 加密代理服务
    ├── package.json
    └── web/
        └── common-85ed7.js       网页版 JS 快照（代理从这里读 RSA 密钥）
```

---

## 加密方案

逆向自网页版 `https://www.10099.com.cn/js/common-85ed7.js`。

该文件内嵌了一对**配对的 2048 位 RSA 密钥**，因此加密与解密都能在本地完整复现：

```
请求体 = {"data": base64( RSA_PKCS1v15( urlencode(JSON(params)) ) )}
请求头 = Access: md5( 递归按键排序后 "k=v" 用 & 连接 )
会话   = sessionId 作为【参数】放在 body 里（不是 header）
```

网页版固定参数（已从真实流量确认）：
- `channelId = cd_20220516_093342`
- `v = 1.1.7.0915_release`
- `type = 5`

> 注意：**微信小程序**用的是另一套参数（`channelId=cd_20220516_173041`、`type=1`、
> `v=w0050`），且只内嵌公钥、无私钥，无法解密响应。本项目基于**网页版**。

### 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/login/getImageCheckCode` | 图形验证码（JPEG，**每次请求生成新码**）|
| POST | `/login/getVerifyCode` | 发送短信验证码 |
| POST | `/login/gwLogin` | 登录，返回 `sessionId` |
| POST | `/busi/qryUserRes` | 流量余量 |
| POST | `/busi/qryBalanceFee` | 余额与当月消费 |
| POST | `/busi/qryPhonePackInfo` | 当前套餐 |

### 服务端错误码

| 码 | 含义 | 集成行为 |
|---|---|---|
| **719** | 图形验证码不能为空 | 提示重新填写 |
| **720** | 图形验证码有误 | **自动重新取图**并退回上一步 |
| **701** | 登录已过期 | 传感器 `unavailable`，需重新登录 |

---

## 数据口径

`/busi/qryUserRes` 返回的是**资源包列表**，单位 KB：

```
highFee    = 资源总量 (KB)
addupValue = 已使用量 (KB)     ← 直接用这个字段，不要用减法推算
balance    = 剩余可用量 (KB)   ← 同上
```

每个资源包的 `busiTypeDesc` 分两类：

- **个人** —— 本月套餐
- **结转** —— 上月没用完滚存的流量

本项目把两者**分开统计**，避免把滚存流量重复累计。三个主指标自洽：

```
本月总流量 = 本月已用流量 + 剩余流量
```

GB 换算除 `1048576`。

---

## 常见问题

**登录失败：图形验证码错误（720）**
换一张重填。注意图形验证码与服务端会话绑定，**每次重新取图都会让旧码失效**。

**登录失败：验证码错误或已过期**
短信验证码有效期通常只有几分钟。如果图形码刚换过但短信码是旧的了，也会这样。

**添加集成时提示"无法连接代理服务"**
`curl http://<代理IP>:8787/health` 应返回 `{"ok":true,...}`。
HA 若为 Docker 且非 host 网络，需把代理监听地址改到 `0.0.0.0`。

**ARM（如树莓派）首次打开集成很慢**
Chromium 在 ARM 上启动约 60–100 秒，属正常现象。之后浏览器常驻，响应会快很多。
内存占用约 900 MB。

**卡片显示空白 / `--`**
`Ctrl+F5` 强制刷新。集成按文件 mtime 生成 `?v=` 版本号，正常情况不会吃到缓存。

**传感器 `unavailable`，提示登录已过期**
`sessionId` 有效期通常几天到几周。集成配置 → 重新登录即可。

---

## 免责声明

- 本项目仅用于**个人**话费/流量查询的自动化，未绕过任何身份验证（仍需手机号 + 短信验证码）。
- 接口为中国广电网上营业厅的**非公开接口**，随时可能变更；改版后需重新从网页 JS 提取密钥与参数
  （密钥在 `proxy/web/` 下的快照里，重新抓 `common-*.js` 替换即可）。
- 轮询间隔默认 30 分钟（`const.py` 的 `DEFAULT_SCAN_INTERVAL`），不建议调更快以免触发风控。
- 仅供学习与研究使用，请遵守相关服务条款。
