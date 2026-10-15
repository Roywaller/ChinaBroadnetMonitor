"""传感器平台：流量、套餐、余额。

传感器清单（按用户要求确认）：
  本月总流量    = 本月已用 + 剩余        （self-consistent）
  本月已用流量  = 含结转消耗的累计已用
  剩余流量      = 个人口径剩余
  结转剩余流量  = 上月滚存剩余
  流量使用率    = 本月已用 / 本月总流量

数值口径：
  服务端返回单位 KB；highFee=总量, addupValue=已用, balance=剩余。
  GB 换算除 1048576。
  个人与结转分开统计，避免把滚存流量重复累计。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class CbnSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any]
    attributes_fn: Callable[[dict], dict[str, Any]] | None = None


def _left_for_rate(d: dict) -> float:
    """计算使用率时的分母剩余：个人剩余（结转已用完时即为全部可用）。"""
    p_left = d["flow"]["personal"]["left_kb"]
    c_left = d["flow"]["carried"]["left_kb"]
    return round(((p_left + c_left) / 1048576), 3)


def _pack_items(d: dict) -> list[dict]:
    rows = []
    for kind in ("personal_items", "carried_items", "other_items"):
        for it in d["flow"].get(kind, []):
            rows.append({
                "名称": it["name"],
                "类型": it["kind"] or it["item_type"],
                "总量GB": it["total_gb"],
                "已用GB": it["used_gb"],
                "剩余GB": it["left_gb"],
                "已用百分比": it["pct"],
                "生效": it["start"],
                "失效": it["end"],
            })
    return rows


def _flow_attrs(d: dict) -> dict[str, Any]:
    """「本月总流量」实体的属性：完整明细。"""
    return {
        "本月已用GB": d["flow"]["all"]["used_gb"],
        "剩余GB": _left_for_rate(d),
        "个人已用GB": d["flow"]["personal"]["used_gb"],
        "个人总量GB": d["flow"]["personal"]["total_gb"],
        "结转总量GB": d["flow"]["carried"]["total_gb"],
        "服务端累计已用GB": d["flow"]["ext_total_gb"],
        "语音累计": d["flow"].get("ext_voice_total"),
        "短信累计": d["flow"].get("ext_sms_total"),
        "流量明细": _pack_items(d),
    }


SENSORS: tuple[CbnSensorDescription, ...] = (
    # ---------------- 流量 ----------------
    CbnSensorDescription(
        key="flow_total",
        translation_key="flow_total",
        name="本月总流量",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:database",
        value_fn=lambda d: round(
            d["flow"]["all"]["used_kb"] / 1048576
            + d["flow"]["personal"]["left_kb"] / 1048576
            + d["flow"]["carried"]["left_kb"] / 1048576, 3),
        attributes_fn=_flow_attrs,
    ),
    CbnSensorDescription(
        key="flow_used",
        translation_key="flow_used",
        name="本月已用流量",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:chart-line",
        value_fn=lambda d: d["flow"]["all"]["used_gb"],
    ),
    CbnSensorDescription(
        key="flow_left",
        translation_key="flow_left",
        name="剩余流量",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:signal",
        value_fn=lambda d: round(
            (d["flow"]["personal"]["left_kb"]
             + d["flow"]["carried"]["left_kb"]) / 1048576, 3),
    ),
    CbnSensorDescription(
        key="flow_pct",
        translation_key="flow_pct",
        name="流量使用率",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=lambda d: (
            round(d["flow"]["all"]["used_kb"]
                  / (d["flow"]["all"]["used_kb"]
                     + d["flow"]["personal"]["left_kb"]
                     + d["flow"]["carried"]["left_kb"]) * 100, 1)
            if (d["flow"]["all"]["used_kb"]
                + d["flow"]["personal"]["left_kb"]
                + d["flow"]["carried"]["left_kb"]) else 0.0
        ),
    ),
    CbnSensorDescription(
        key="flow_left_carried",
        translation_key="flow_left_carried",
        name="结转剩余流量",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transfer-right",
        value_fn=lambda d: d["flow"]["carried"]["left_gb"],
    ),
    # ---------------- 语音 / 短信 ----------------
    CbnSensorDescription(
        key="voice_total",
        translation_key="voice_total",
        name="语音已用",
        native_unit_of_measurement="分钟",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:phone",
        value_fn=lambda d: d["flow"].get("ext_voice_total"),
    ),
    CbnSensorDescription(
        key="sms_total",
        translation_key="sms_total",
        name="短信已用",
        native_unit_of_measurement="条",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:message-text",
        value_fn=lambda d: d["flow"].get("ext_sms_total"),
    ),
    # ---------------- 套餐 ----------------
    CbnSensorDescription(
        key="pack_name",
        translation_key="pack_name",
        name="当前套餐",
        icon="mdi:package-variant",
        value_fn=lambda d: d["pack"]["pack_name"],
        attributes_fn=lambda d: {
            "月费(元)": d["pack"]["pack_fee"],
            "套餐编码": d["pack"]["offer_code"],
            "开通日期": d["pack"]["open_date"],
        },
    ),
    CbnSensorDescription(
        key="pack_fee",
        translation_key="pack_fee",
        name="套餐月费",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:currency-cny",
        value_fn=lambda d: d["pack"]["pack_fee"],
    ),
    # ---------------- 余额 / 消费 ----------------
    CbnSensorDescription(
        key="balance",
        translation_key="balance",
        name="账户余额",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:wallet",
        value_fn=lambda d: d["balance"]["balance"],
    ),
    CbnSensorDescription(
        key="month_fee",
        translation_key="month_fee",
        name="当月消费",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-minus",
        value_fn=lambda d: d["balance"]["month_fee"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CbnSensor(coordinator, entry, desc) for desc in SENSORS)


class CbnSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    entity_description: CbnSensorDescription

    def __init__(self, coordinator, entry: ConfigEntry, description: CbnSensorDescription):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"中国广电 {coordinator.phone}",
            "manufacturer": "China Broadnet",
            "model": "网上营业厅",
        }

    @property
    def native_value(self):
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, TypeError, AttributeError, ZeroDivisionError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.entity_description.attributes_fn is None:
            return {}
        try:
            attrs = self.entity_description.attributes_fn(self.coordinator.data)
            # HA 要求 attributes 是 dict；防御性检查
            return attrs if isinstance(attrs, dict) else {}
        except (KeyError, TypeError, AttributeError):
            return {}
