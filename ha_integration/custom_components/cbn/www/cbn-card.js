class CbnCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("cbn-card-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:cbn-card",
      title: "中国广电",
      balance_warning_below: 20,
      usage_warning_percent: 80,
      usage_danger_percent: 95,
      show_details: true,
    };
  }

  setConfig(config) {
    this.config = {
      title: "中国广电",
      balance_warning_below: 20,
      usage_warning_percent: 80,
      usage_danger_percent: 95,
      show_details: true,
      ...config,
    };
    if (this.config.device_id === "") delete this.config.device_id;
    this.entities = [];
    this.device = null;
    this.discoveryKey = "";
    this.render();
  }

  connectedCallback() {
    if (this._moreInfoHandler) return;
    this._moreInfoHandler = (event) => {
      const accordionHeader = event.target.closest(".accordion-header");
      if (accordionHeader && this.contains(accordionHeader)) {
        event.stopPropagation();
        const accordion = accordionHeader.closest(".accordion");
        if (accordion) accordion.classList.toggle("open");
        return;
      }
      const target = event.target.closest("[data-entity-id]");
      if (!target || !this.contains(target)) return;

      const entityId = target.dataset.entityId;
      if (!entityId) return;
      event.stopPropagation();
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      }));
    };
    this.addEventListener("click", this._moreInfoHandler);
  }

  disconnectedCallback() {
    if (!this._moreInfoHandler) return;
    this.removeEventListener("click", this._moreInfoHandler);
    this._moreInfoHandler = null;
  }

  set hass(hass) {
    this._hass = hass;
    this.discoverEntities();
    this.render();
  }

  getCardSize() {
    return 5;
  }

  // entity_id 后缀（由 unique_id 派生），用于【精确】匹配。
  // 注意：不能用 /剩余流量/ 这种子串匹配 —— "结转剩余流量" 也含该子串，
  // 会把它错当成 "剩余流量"。
  static SUFFIX = {
    flowTotal: "total_data_this_month",
    flowUsed: "data_used_this_month",
    flowLeft: "data_remaining",
    flowPct: "data_usage_rate",
    flowLeftCarried: "carried_over_remaining",
    voiceTotal: "voice_used",
    smsTotal: "sms_used",
    packName: "current_plan",
    packFee: "monthly_plan_fee",
    balance: "account_balance",
    monthFee: "spent_this_month",
  };

  /** 按 entity_id 后缀精确匹配（最可靠）。 */
  byKey(key) {
    const suffix = CbnCard.SUFFIX[key];
    if (!suffix) return undefined;
    return this.entities.find((e) =>
      e.entity_id === `sensor.${suffix}` || e.entity_id.endsWith(`_${suffix}`));
  }

  async discoverEntities() {
    if (!this._hass?.callWS || this.discovering) return;

    const key = JSON.stringify({
      device_id: this.config.device_id,
      states: Object.keys(this._hass.states || {}).length,
    });
    if (this.discoveryKey === key && this.entities.length) return;

    this.discovering = true;
    try {
      const [devices, registry] = await Promise.all([
        this._hass.callWS({ type: "config/device_registry/list" }),
        this._hass.callWS({ type: "config/entity_registry/list" }),
      ]);

      const cbnDevice = this.config.device_id
        ? devices.find((device) => device.id === this.config.device_id)
        : this.findCbnDevice(devices, registry);
      const deviceId = cbnDevice?.id || this.config.device_id;

      this.device = cbnDevice || null;
      this.entities = registry
        .filter((entry) => entry.device_id === deviceId)
        .filter((entry) => !entry.disabled_by && !entry.hidden_by)
        .filter((entry) => this._hass.states[entry.entity_id])
        .sort((a, b) => this.sortRank(a).localeCompare(this.sortRank(b)));
      this.discoveryKey = key;
    } catch (error) {
      this.discoveryError = error;
    } finally {
      this.discovering = false;
      this.render(true);
    }
  }

  findCbnDevice(devices, registry) {
    const text = (device) => [
      device.name_by_user,
      device.name,
      device.manufacturer,
      device.model,
    ].filter(Boolean).join(" ");

    const byName = devices.find((device) => /中国广电|广电|China Broadnet|CBN/i.test(text(device)));
    if (byName) return byName;

    const byDomain = devices.find((device) =>
      (device.identifiers || []).some((id) => String(id).startsWith("cbn")));
    return byDomain || null;
  }

  sortRank(entry) {
    const entityId = entry.entity_id;
    // 同样用精确后缀，避免子串误判
    const ORDER = [
      "total_data_this_month", "data_remaining", "data_usage_rate",
      "data_used_this_month", "carried_over_remaining",
      "voice_used", "sms_used",
      "current_plan", "monthly_plan_fee", "account_balance", "spent_this_month",
    ];
    for (let i = 0; i < ORDER.length; i++) {
      const s = ORDER[i];
      if (entityId === `sensor.${s}` || entityId.endsWith(`_${s}`)) {
        return `${String(i + 1).padStart(2, "0")}-${entityId}`;
      }
    }
    return `99-${entityId}`;
  }

  entryName(entry) {
    return entry.name || entry.original_name || this._hass?.states?.[entry.entity_id]?.attributes?.friendly_name || entry.entity_id;
  }

  label(entry) {
    return this.entryName(entry)
      .replace(/^\d{3}[*\d_]+ ?/, "")
      .replace(/^广电/, "")
      .trim();
  }

  state(entityId) {
    return this._hass?.states?.[entityId];
  }

  findEntity(patterns) {
    return this.entities.find((entry) => {
      const text = `${entry.entity_id} ${this.entryName(entry)}`;
      return patterns.some((pattern) => pattern.test(text));
    });
  }

  value(entry) {
    const state = entry && this.state(entry.entity_id);
    if (!state) return "--";
    const unit = state.attributes?.unit_of_measurement || "";
    return `${state.state}${unit ? ` ${unit}` : ""}`;
  }

  stateValue(entry) {
    const state = entry && this.state(entry.entity_id);
    if (!state) return "--";
    return state.state;
  }

  numberValue(entry) {
    const state = entry && this.state(entry.entity_id);
    const value = Number.parseFloat(state?.state);
    return Number.isFinite(value) ? value : null;
  }

  /**
   * 平均每日可用流量 = 剩余流量 / 本月剩余天数（含今天）。
   * 纯前端按自然月计算，不需要后端新增传感器。
   * 返回 { perDay, daysLeft }，数据不足时 perDay 为 null。
   */
  dailyAllowance(remainEntry) {
    const remain = this.numberValue(remainEntry);
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const totalDays = new Date(year, month + 1, 0).getDate();
    const today = now.getDate();
    // 含今天在内，最少按 1 天算，避免除零
    const daysLeft = Math.max(1, totalDays - today + 1);
    if (remain === null) return { perDay: null, daysLeft };
    return { perDay: remain / daysLeft, daysLeft };
  }

  render(force = false) {
    if (!this.config) return;
    const key = JSON.stringify({
      config: this.config,
      entities: this.entities.map((entry) => [entry.entity_id, this.state(entry.entity_id)?.state]),
      discovering: this.discovering,
      error: Boolean(this.discoveryError),
    });
    if (!force && this.lastRenderKey === key) return;
    this.lastRenderKey = key;

    // 全部用精确后缀匹配，避免子串误判
    const balance = this.byKey("balance");
    const monthFee = this.byKey("monthFee");
    const dataRate = this.byKey("flowPct");
    const pack = this.byKey("packName");
    const flowTotal = this.byKey("flowTotal");
    const flowLeft = this.byKey("flowLeft");

    this.innerHTML = `
      <ha-card>
        <div class="cbn-card">
          <div class="card-header">
            <div class="card-title">
              <img class="card-logo" src="/cbn-local/logo.png" alt="logo">
              ${this.escape(this.config.title || "中国广电")}
            </div>
            <div class="header-right">
              ${this.dailyAllowanceBadge(flowLeft)}
              <div class="card-subtitle">${this.escape(pack ? this.value(pack) : "")}</div>
            </div>
          </div>
          ${this.discoveryError ? `<div class="message">实体读取失败：${this.escape(this.discoveryError.message || this.discoveryError)}</div>` : ""}
          ${this.discovering && !this.entities.length ? `<div class="message">正在读取设备实体...</div>` : ""}
          ${!this.discovering && !this.entities.length ? `<div class="message">未找到可显示实体，请在卡片编辑器选择广电设备。</div>` : ""}
          ${this.entities.length ? `
            <div class="summary-row">
              ${this.summaryItem("剩余流量", flowLeft, "mdi:signal", "green")}
              ${this.summaryItem("本月总流量", flowTotal, "mdi:database", "blue")}
              ${this.summaryItem("账户余额", balance, "mdi:wallet", "green")}
              ${this.summaryItem("当月消费", monthFee, "mdi:currency-cny", "orange")}
            </div>
            <div class="meters">
              ${this.progress("本月流量", dataRate, flowLeft, flowTotal)}
            </div>
            <div class="accordions">
              ${this.accordionSection("流量", "mdi:cellphone-link",
                ["flowTotal", "flowUsed", "flowLeft", "flowLeftCarried", "flowPct"])}
              ${this.accordionSection("语音 / 短信", "mdi:message-text",
                ["voiceTotal", "smsTotal"], {"voiceTotal": "分钟", "smsTotal": "条"})}
              ${this.accordionSection("套餐与账单", "mdi:file-document",
                ["packFee", "balance", "monthFee"],
                {"packFee": "元", "balance": "元", "monthFee": "元"})}
            </div>
          ` : ""}
        </div>
        <style>
          .cbn-card { padding: 0; color: var(--primary-text-color); }
          .card-header {
            display: flex; align-items: center; justify-content: space-between;
            padding: 16px 20px 12px; border-bottom: 2px solid transparent;
            border-image: linear-gradient(90deg, #0066a8, #2196f3, #90caf9, transparent) 1;
          }
          .card-title {
            font-size: 18px; font-weight: bold; color: var(--primary-text-color);
            display: flex; align-items: center; gap: 10px;
          }
          .card-title img.card-logo {
            width: 30px; height: 30px; border-radius: 6px;
            object-fit: contain; box-shadow: 0 1px 4px rgba(0,0,0,0.12);
          }
          .card-subtitle { font-size: 12px; color: var(--secondary-text-color, #999); }
          /* 右上角：日均可用徽标 + 套餐名 并排 */
          .header-right {
            display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
            justify-content: flex-end;
          }
          /* 日均可用：浅色胶囊，跟随主题主色，不与标题抢视觉重心 */
          .daily-badge {
            display: inline-flex; align-items: center; gap: 4px;
            padding: 3px 9px 3px 7px; border-radius: 999px;
            background: color-mix(in srgb, var(--primary-color, #2196f3) 12%, transparent);
            color: var(--primary-color, #2196f3);
            white-space: nowrap; cursor: default; line-height: 1;
          }
          .daily-badge ha-icon { --mdi-icon-size: 14px; opacity: 0.85; }
          .daily-badge .daily-value { font-size: 13px; font-weight: 700; }
          .daily-badge .daily-unit { font-size: 10px; font-weight: 500; opacity: 0.8; }
          .message { color: var(--secondary-text-color); padding: 12px 16px 4px; font-size: 14px; }
          .summary-row { display: grid; grid-template-columns: repeat(4, 1fr); padding: 12px; gap: 8px; }
          .summary-item {
            text-align: center; background: var(--secondary-background-color, rgba(0,0,0,0.03));
            border-radius: 10px; padding: 10px 4px 8px;
            transition: transform 0.15s, box-shadow 0.15s; cursor: pointer;
          }
          .summary-item:hover { transform: translateY(-2px); box-shadow: 0 3px 10px rgba(0,0,0,0.08); }
          .summary-icon { margin-bottom: 4px; }
          .summary-icon ha-icon { --mdi-icon-size: 20px; color: var(--secondary-text-color, #999); }
          .summary-value { font-size: 18px; font-weight: bold; line-height: 1.3; }
          .summary-value.green { color: #43A047; }
          .summary-value.orange { color: #FF6D00; }
          .summary-value.blue { color: #1E88E5; }
          .summary-value.red { color: #EF5350; }
          .summary-label {
            font-size: 10px; color: var(--secondary-text-color, #999);
            margin-top: 2px; letter-spacing: 0.3px; line-height: 1.3; word-break: keep-all;
          }
          .meters { display: grid; gap: 10px; margin-bottom: 12px; padding: 0 12px; }
          .meter {
            background: var(--secondary-background-color, rgba(0,0,0,0.03));
            border-radius: 10px; padding: 10px 12px;
          }
          .meter-header {
            display: flex; justify-content: space-between; align-items: baseline;
            margin-bottom: 6px; font-size: 13px;
          }
          .meter-name { font-weight: 600; display: flex; align-items: center; gap: 6px; }
          .meter-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
          .meter-dot.normal { background: #43A047; }
          .meter-dot.warn { background: #FFB300; }
          .meter-dot.danger { background: #E53935; }
          .meter-volume { font-weight: bold; font-size: 14px; }
          .meter-body { display: flex; align-items: center; gap: 10px; }
          .meter-bar {
            flex: 1 1 auto; min-width: 0;
            height: 8px; border-radius: 4px; overflow: hidden;
            background: var(--divider-color, rgba(0,0,0,0.08));
          }
          .meter-bar-fill { height: 100%; border-radius: 4px; transition: width 0.4s ease; }
          .meter-bar-fill.normal { background: linear-gradient(90deg, #66bb6a, #43a047); }
          .meter-bar-fill.warn { background: linear-gradient(90deg, #ffca28, #ffb300); }
          .meter-bar-fill.danger { background: linear-gradient(90deg, #ef5350, #e53935); }
          .meter-info {
            display: flex; justify-content: space-between;
            font-size: 11px; color: var(--secondary-text-color, #999); margin-top: 4px;
          }
          .clickable-value { cursor: pointer; }
          .clickable-value:hover { color: var(--primary-color); }
          .accordions { display: grid; gap: 8px; padding: 0 12px 12px; }
          .accordion {
            border-radius: 10px; overflow: hidden;
            background: var(--secondary-background-color, rgba(0,0,0,0.03));
          }
          .accordion-header {
            display: flex; align-items: center; gap: 8px;
            padding: 10px 12px; cursor: pointer; user-select: none;
          }
          .accordion-header ha-icon { --mdi-icon-size: 18px; color: var(--secondary-text-color, #999); }
          .accordion-title { font-size: 13px; font-weight: 600; flex: 1; }
          .accordion-chevron { transition: transform 0.2s; }
          .accordion-body { display: none; padding: 0 12px 10px; }
          .accordion.open .accordion-body { display: block; }
          .accordion.open .accordion-chevron { transform: rotate(180deg); }
          .entity-grid { display: grid; gap: 6px; }
          .entity-row {
            display: flex; justify-content: space-between; align-items: center;
            font-size: 12px; padding: 6px 8px; border-radius: 6px;
            background: var(--card-background-color, rgba(255,255,255,0.5)); cursor: pointer;
          }
          .entity-row:hover { background: var(--primary-background-color, rgba(0,0,0,0.03)); }
          .row-name { color: var(--secondary-text-color, #666); }
          .row-value { font-weight: 600; }
        </style>
      </ha-card>
    `;
  }

  summaryItem(label, entry, icon, color) {
    return `
      <div class="summary-item"${this.entityAttr(entry)}>
        <div class="summary-icon"><ha-icon icon="${icon}"></ha-icon></div>
        <div class="summary-value ${color || ""}">${this.escape(this.stateValue(entry))}</div>
        <div class="summary-label">${this.escape(label)}</div>
      </div>
    `;
  }

  progress(label, rateEntry, remainEntry, totalEntry, unit = "") {
    const rate = this.numberValue(rateEntry);
    const percent = rate === null ? 0 : Math.max(0, Math.min(100, rate));
    const level = this.usageLevel(rate);
    const fillClass = level === "danger" ? "danger" : level === "warn" ? "warn" : "normal";
    return `
      <div class="meter">
        <div class="meter-header">
          <span class="meter-name"><span class="meter-dot ${fillClass}"></span>${this.escape(label)}</span>
          <span class="meter-volume">${this.clickableValue(rateEntry)}</span>
        </div>
        <div class="meter-body">
          <div class="meter-bar"><div class="meter-bar-fill ${fillClass}" style="width:${percent}%"></div></div>
        </div>
        <div class="meter-info">
          <span>剩余 ${this.clickableValue(remainEntry)}${unit ? ` ${this.escape(unit)}` : ""}</span>
          <span>总量 ${this.clickableValue(totalEntry)}${unit ? ` ${this.escape(unit)}` : ""}</span>
        </div>
      </div>
    `;
  }

  /**
   * 顶部右上角、套餐名左侧的「日均可用」徽标。
   * 日均可用 = 剩余流量 ÷ 本月剩余天数（含今天），纯前端按自然月算。
   */
  dailyAllowanceBadge(remainEntry) {
    const { perDay, daysLeft } = this.dailyAllowance(remainEntry);
    if (perDay === null) return "";
    const text = perDay >= 10 ? perDay.toFixed(1) : perDay.toFixed(2);
    return `
      <div class="daily-badge" title="日均可用：剩余流量 ÷ 本月剩余 ${daysLeft} 天（含今天）">
        <ha-icon icon="mdi:calendar-today"></ha-icon>
        <span class="daily-value">${this.escape(text)}</span>
        <span class="daily-unit">GB/天</span>
      </div>
    `;
  }


  clickableValue(entry, extraClass = "") {
    const className = `clickable-value${extraClass ? ` ${extraClass}` : ""}`;
    return `<span class="${className}"${this.entityAttr(entry)}>${this.escape(this.value(entry))}</span>`;
  }

  usageLevel(value) {
    if (value === null) return "normal";
    const warning = Number.parseFloat(this.config.usage_warning_percent);
    const danger = Number.parseFloat(this.config.usage_danger_percent);
    if (Number.isFinite(danger) && danger > 0 && value >= danger) return "danger";
    if (Number.isFinite(warning) && warning > 0 && value >= warning) return "warn";
    return "normal";
  }

  /** keys 是 CbnCard.SUFFIX 的键名，按精确后缀挑实体。 */
  accordionSection(title, icon, keys, unitMap = {}) {
    const rows = keys.map((k) => this.byKey(k)).filter(Boolean);
    rows.sort((a, b) => this.sortRank(a).localeCompare(this.sortRank(b)));
    if (!rows.length) return "";
    const sectionId = `accordion-${title}`;
    const isOpen = this.config?.show_details !== false;
    // key -> 后缀，便于查单位覆盖
    const suffixOf = (entry) => {
      for (const k of Object.keys(CbnCard.SUFFIX)) {
        if (this.byKey(k)?.entity_id === entry.entity_id) return k;
      }
      return null;
    };
    return `
      <div class="accordion${isOpen ? " open" : ""}" data-accordion="${sectionId}">
        <div class="accordion-header">
          <ha-icon class="accordion-icon" icon="${icon}"></ha-icon>
          <span class="accordion-title">${this.escape(title)}</span>
          <ha-icon class="accordion-chevron" icon="mdi:chevron-down"></ha-icon>
        </div>
        <div class="accordion-body" id="${sectionId}">
          <div class="entity-grid">
            ${rows.map((entry) => {
              const key = suffixOf(entry);
              const unit = key ? unitMap[key] : undefined;
              const displayValue = unit
                ? `${this.stateValue(entry)} ${unit}`
                : this.value(entry);
              return `
              <div class="entity-row"${this.entityAttr(entry)}>
                <div class="row-name">${this.escape(this.label(entry))}</div>
                <div class="row-value">${this.escape(displayValue)}</div>
              </div>
            `;
            }).join("")}
          </div>
        </div>
      </div>
    `;
  }

  escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }

  entityAttr(entry) {
    return entry?.entity_id ? ` data-entity-id="${this.escape(entry.entity_id)}"` : "";
  }
}

class CbnCardEditor extends HTMLElement {
  setConfig(config) {
    this.config = {
      title: "中国广电",
      balance_warning_below: 20,
      usage_warning_percent: 80,
      usage_danger_percent: 95,
      show_details: true,
      ...config,
    };
    if (this.config.device_id === "") delete this.config.device_id;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) {
      this._form.hass = hass;
      return;
    }
    this.render();
  }

  render() {
    if (!this._hass || !this.config) return;
    if (!this._form) {
      this.innerHTML = `<ha-form></ha-form>`;
      this._form = this.querySelector("ha-form");
      this._form.schema = [
        { name: "title", selector: { text: {} } },
        { name: "device_id", selector: { device: {} } },
        { name: "balance_warning_below", selector: { number: { min: 0, mode: "box", unit_of_measurement: "元" } } },
        { name: "usage_warning_percent", selector: { number: { min: 0, max: 100, mode: "box", unit_of_measurement: "%" } } },
        { name: "usage_danger_percent", selector: { number: { min: 0, max: 100, mode: "box", unit_of_measurement: "%" } } },
        { name: "show_details", selector: { boolean: {} } },
      ];
      this._form.computeLabel = (schema) => ({
        title: "标题",
        device_id: "广电设备",
        balance_warning_below: "余额低于此值标红",
        usage_warning_percent: "使用率提醒百分比",
        usage_danger_percent: "使用率危险百分比",
        show_details: "明细展开显示",
      }[schema.name] || schema.name);
      this._form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        const nextConfig = { ...this.config, ...event.detail.value };
        if (JSON.stringify(nextConfig) === JSON.stringify(this.config)) return;
        this.config = nextConfig;
        this.dispatchEvent(new CustomEvent("config-changed", {
          detail: { config: this.config },
          bubbles: true,
          composed: true,
        }));
      });
    }
    this._form.hass = this._hass;
    this._form.data = this.config;
  }
}

customElements.define("cbn-card", CbnCard);
customElements.define("cbn-card-editor", CbnCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "cbn-card",
  name: "中国广电卡片",
  description: "自动读取广电设备的剩余流量、余额、套餐与账单。",
});
