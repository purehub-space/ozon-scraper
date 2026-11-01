"""
Ozon Scraper 公共环境探测与工具函数
支持 Windows / macOS / Linux 自动探测 Chrome/Edge、本地代理、Cookie 缓存
"""
import glob
import json
import os
import re
import socket
import sys
import tempfile
import time
import urllib.parse
import urllib.request

CACHE_DIR = os.path.expanduser("~/.cache/ozon-search")

CHROME_CANDIDATES = [
    # Windows Chrome & Edge
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def get_chrome_executable():
    for p in CHROME_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


def detect_proxy():
    # 环境变量优先
    for var in ["https_proxy", "http_proxy", "ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"]:
        val = os.environ.get(var)
        if val:
            if not val.startswith("http"):
                val = "http://" + val
            return val
    # 探测本地端口
    for port in [7897, 7890, 10808, 10809]:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    return None


def parse_num(s):
    if s is None:
        return None
    c = re.sub(
        r"[^\d.,-]", "",
        str(s).replace("\u202f", "").replace("\u00a0", "").replace(" ", "")
    ).replace(",", ".")
    if not c:
        return None
    try:
        v = float(c)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def parse_count_num(s):
    if s is None:
        return None
    t = str(s).strip()
    m = re.search(r"([\d.,]+)\s*([kKкКmMмМ])?", t)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "").lower()
        if unit in ("k", "к"):
            v *= 1000
        elif unit in ("m", "м"):
            v *= 1000000
        return int(v)
    except Exception:
        return None
