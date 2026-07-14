from __future__ import annotations

import json

ZABBIX_OS_ITEM_KEYS = (
    "system.sw.os.get",
    "system.sw.os",
)

ZABBIX_SERVER_MODEL_ITEM_KEY = "vfs.file.contents[/sys/class/dmi/id/product_name]"
ZABBIX_SERVER_VENDOR_ITEM_KEY = "vfs.file.contents[/sys/class/dmi/id/sys_vendor]"

ZABBIX_DETAIL_ITEM_KEYS = (
    "system.cpu.num",
    "vm.memory.size[total]",
    ZABBIX_SERVER_MODEL_ITEM_KEY,
    ZABBIX_SERVER_VENDOR_ITEM_KEY,
    *ZABBIX_OS_ITEM_KEYS,
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


def operating_system_item_label(item_values: dict[str, str], fallback: str | None = None) -> str | None:
    for key in ZABBIX_OS_ITEM_KEYS:
        value = item_values.get(key)
        if value:
            return clean_operating_system_label(value)
    return clean_operating_system_label(fallback)


def clean_operating_system_label(value: str | None) -> str | None:
    return clean_item_text(value, max_length=80)


def clean_item_text(value: str | None, max_length: int | None = None) -> str | None:
    if not value:
        return None

    text = " ".join(value.split())
    if not text or text.lower() in {"none", "unknown", "not specified", "to be filled by o.e.m."}:
        return None

    if max_length and len(text) > max_length:
        return f"{text[: max_length - 3].rstrip()}..."
    return text


def server_model_item_label(item_values: dict[str, str], fallback: str | None = None) -> str | None:
    return clean_item_text(item_values.get(ZABBIX_SERVER_MODEL_ITEM_KEY)) or clean_item_text(fallback)


def server_vendor_item_label(item_values: dict[str, str], fallback: str | None = None) -> str | None:
    return clean_item_text(item_values.get(ZABBIX_SERVER_VENDOR_ITEM_KEY)) or clean_item_text(fallback)
