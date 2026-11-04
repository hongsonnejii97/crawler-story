"""
HTTP Fetcher module with anti-bot bypass, retry logic and browser impersonation.
"""
import time
import random
import logging
from typing import Optional, Dict, Any

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False

logger = logging.getLogger("CrawlerFetcher")

DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
]

class Fetcher:
    def __init__(self, proxy: Optional[str] = None, timeout: int = 15, max_retries: int = 3):
        self.proxy = proxy
        self.timeout = timeout
        self.max_retries = max_retries

    def get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": random.choice(DEFAULT_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if referer else "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def fetch(self, url: str, referer: Optional[str] = None, retry_count: int = 0) -> str:
        """Fetch HTML content with automatic retries and anti-bot bypass."""
        headers = self.get_headers(referer)
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if HAS_CURL_CFFI:
                    resp = cffi_requests.get(
                        url,
                        headers=headers,
                        proxies=proxies,
                        timeout=self.timeout,
                        impersonate="chrome120",
                        allow_redirects=True
                    )
                else:
                    import requests
                    resp = requests.get(
                        url,
                        headers=headers,
                        proxies=proxies,
                        timeout=self.timeout,
                        allow_redirects=True
                    )

                if resp.status_code == 200:
                    # Fix character encoding if needed
                    text = resp.text
                    if "charset=windows-1258" in text.lower() or "windows-1258" in resp.headers.get("content-type", "").lower():
                        text = resp.content.decode("windows-1258", errors="replace")
                    return text
                elif resp.status_code in [403, 503]:
                    logger.warning(f"Got {resp.status_code} for {url} (attempt {attempt}/{self.max_retries})")
                else:
                    logger.warning(f"HTTP {resp.status_code} for {url}")

            except Exception as e:
                last_err = e
                logger.debug(f"Fetch error for {url}: {e} (attempt {attempt}/{self.max_retries})")

            # Exponential backoff jitter
            sleep_time = (2 ** attempt) * 0.5 + random.uniform(0.1, 0.5)
            time.sleep(sleep_time)

        raise RuntimeError(f"Failed to fetch {url} after {self.max_retries} attempts: {last_err}")

