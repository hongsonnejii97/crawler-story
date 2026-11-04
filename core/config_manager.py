"""
Configuration Manager for crawler settings and ad filters.
"""
import os
import json
from typing import Dict, Any, List

CONFIG_FILE = "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "max_workers": 3,
    "request_delay": 0.3,
    "include_toc": True,
    "font_name": "Times New Roman",
    "font_size": 12,
    "filter_html_ads": True,
    "filter_text_ads": True,
    "custom_ad_phrases": [
        "đọc truyện tại",
        "truy cập website",
        "ủng hộ dịch giả",
        "donate qua",
        "stk ngân hàng",
        "mời bạn tham gia group",
        "chúc bạn đọc truyện vui vẻ",
        "tải app để đọc"
    ]
}

def load_config() -> Dict[str, Any]:
    """Load configuration from config.json, fallback to defaults."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = dict(DEFAULT_CONFIG)
                config.update(data)
                return config
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(new_config: Dict[str, Any]):
    """Save configuration to config.json."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(new_config, f, ensure_ascii=False, indent=2)

