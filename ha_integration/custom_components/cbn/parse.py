"""数据解析：把广电 /busi/qryUserRes 和 /busi/qryBalanceFee 转成汇总数据。"""
from __future__ import annotations

KB = 1024
MB = 1024 * 1024
GB = 1024 * 1024 * 1024


def _to_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _to_yuan(fen) -> float:
    try:
        return int(fen) / 100.0
    except (TypeError, ValueError):
        return 0.0


def summarize_flow(resp: dict) -> dict:
    """qryUserRes -> 流量汇总。

    字段含义（实测确认）：
      highFee    = 资源总量 (KB)
      addupValue = 已使用量 (KB)
      balance    = 剩余可用量 (KB)
      busiTypeDesc = "个人" / "结转"
    """
    bean = ((resp.get("data") or {}).get("intfResultBean") or {})
    items = bean.get("userResList") or []

    personal = []      # 本月个人资源
    carried = []        # 上月结转
    other = []          # 其他分类

    for it in items:
        total_kb = _to_int(it.get("highFee"))
        used_kb = _to_int(it.get("addupValue"))
        left_kb = _to_int(it.get("balance"))
        kind = (it.get("busiTypeDesc") or "").strip()
        entry = {
            "name": it.get("discntName") or "",
            "kind": kind,
            "item_type": it.get("itemTypeDesc") or "",
            "total_kb": total_kb,
            "used_kb": used_kb,
            "left_kb": left_kb,
            "total_mb": round(total_kb / KB, 2),
            "used_mb": round(used_kb / KB, 2),
            "left_mb": round(left_kb / KB, 2),
            "total_gb": round(total_kb / (1024 * 1024), 3),
            "used_gb": round(used_kb / (1024 * 1024), 3),
            "left_gb": round(left_kb / (1024 * 1024), 3),
            "start": it.get("startTime"),
            "end": it.get("endTime"),
            "pct": round(used_kb / total_kb * 100, 1) if total_kb else 0.0,
        }
        if kind == "结转":
            carried.append(entry)
        elif kind == "个人":
            personal.append(entry)
        else:
            other.append(entry)

    def agg(rows):
        t = sum(r["total_kb"] for r in rows)
        u = sum(r["used_kb"] for r in rows)
        l = sum(r["left_kb"] for r in rows)
        return {
            "total_kb": t, "used_kb": u, "left_kb": l,
            "total_mb": round(t / KB, 2),
            "used_mb": round(u / KB, 2),
            "left_mb": round(l / KB, 2),
            "total_gb": round(t / (1024 * 1024), 3),
            "used_gb": round(u / (1024 * 1024), 3),
            "left_gb": round(l / (1024 * 1024), 3),
            "pct": round(u / t * 100, 1) if t else 0.0,
        }

    # ext 汇总（服务端算的累计值）
    ext = (bean.get("userExtResList") or [{}])[0]

    return {
        "personal": agg(personal),
        "carried": agg(carried),
        "other": agg(other),
        "all": agg(personal + carried + other),
        "personal_items": personal,
        "carried_items": carried,
        "other_items": other,
        # 服务端 ext 汇总，用于交叉校验
        "ext_total_kb": _to_int(ext.get("addupTotalValue")),
        "ext_total_gb": round(_to_int(ext.get("addupTotalValue")) / (1024 * 1024), 3),
        "ext_voice_total": ext.get("addupVoiceTotalValue"),
        "ext_sms_total": ext.get("addupSmsTotalValue"),
        "raw_count": len(items),
    }


def summarize_balance(resp: dict) -> dict:
    """qryBalanceFee -> 余额/当月消费（单位：元）。"""
    bean = ((resp.get("data") or {}).get("intfResultBean") or {})
    return {
        "balance": _to_yuan(bean.get("balance")),
        "month_fee": _to_yuan(bean.get("currealFee")),
        "cycle": bean.get("curCycleId"),
        "as_of": bean.get("xsysdate"),
        "spay_fee": _to_yuan(bean.get("spayFee")),
    }


def summarize_pack(resp: dict) -> dict:
    """qryPhonePackInfo -> 当前套餐。"""
    d = resp.get("data") or {}
    return {
        "pack_name": d.get("packName") or "",
        "pack_fee": _to_yuan(d.get("packFee")),
        "offer_code": d.get("offerCode") or "",
        "open_date": d.get("openDate") or "",
        "state": d.get("state") or "",
        "is_old_age": d.get("isOldAge") or "0",
        "cx_pack_name": d.get("cxPackName") or "",
    }
