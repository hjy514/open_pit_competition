# -*- coding: utf-8 -*-

def business_label(value):
    labels = {
        "IDLE": "空闲",
        "LOADING": "装载",
        "UNLOADING": "卸载",
        "TO_DUMP": "运输中",
        "TO_LOADING": "前往装载点",
        "FAULT": "故障",
    }
    key = str(value or "IDLE").upper()
    return labels.get(key, key)


def health_label(healthy):
    return "正常" if bool(healthy) else "故障"
