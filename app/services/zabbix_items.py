from __future__ import annotations

import json

ZABBIX_DETAIL_ITEM_KEYS = (
    "system.cpu.num",
    "vm.memory.size[total]",
    "system.sw.os",
)

ZABBIX_ITEMS_NOTE_MARKER = "Zabbix items:"


def serialize_zabbix_item_values(item_values: dict[str, str]) -> str:
    return json.dumps(item_values, sort_keys=True)


def parse_zabbix_item_values(notes: str | None) -> dict[str, str]:
    if not notes or ZABBIX_ITEMS_NOTE_MARKER not in notes:
        return {}
    item_text = notes.split(ZABBIX_ITEMS_NOTE_MARKER, 1)[1].split(";", 1)[0].strip()
    if not item_text:
        return {}
    try:
        parsed = json.loads(item_text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if key and value not in (None, "")
    }


def replace_zabbix_item_values(notes: str | None, item_values: dict[str, str]) -> str | None:
    segments = [
        segment.strip()
        for segment in (notes or "").split(";")
        if segment.strip() and not segment.strip().startswith(ZABBIX_ITEMS_NOTE_MARKER)
    ]
    if item_values:
        segments.append(f"{ZABBIX_ITEMS_NOTE_MARKER} {serialize_zabbix_item_values(item_values)}")
    return "; ".join(segments) or None
