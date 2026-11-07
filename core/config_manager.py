"""
Configuration Manager for crawler settings and ad filters.
"""
import os
import json
import tempfile
from typing import Dict, Any

CONFIG_FILE = "config.json"
TMP_CONFIG_FILE = os.path.join(tempfile.gettempdir(), "story_crawler_config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "max_workers": 3,
    "request_delay": 0.3,
    "export_mode": "individual",
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
    """Load configuration from config.json (and /tmp overlay on serverless), fallback to defaults."""
    config = dict(DEFAULT_CONFIG)
    for path in (CONFIG_FILE, TMP_CONFIG_FILE):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        config.update(data)
            except Exception:
                pass
    return config

def save_config(new_config: Dict[str, Any]):
    """Save configuration to config.json, falling back to /tmp on read-only serverless file systems."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(new_config, f, ensure_ascii=False, indent=2)
    except OSError:
        with open(TMP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(new_config, f, ensure_ascii=False, indent=2)
