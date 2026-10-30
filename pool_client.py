#!/usr/bin/env python3
"""
Cookie 池客户端：轮换多个无痕会话，403 自动补池。

为什么值得：
  实测单个 cookie 的并发甜点 ~24 线程（66 SKU/s），40 线程直接崩（4 SKU/s）。
  N 个独立 cookie 各自限速 → 吞吐近似线性叠加：
      4 cookie × 16 并发（新鲜池）= 247 SKU/s，96% 成功，0 个 403
      4 cookie × 24 并发          = 341 SKU/s，但 74% 成功（过载）
  每个 cookie 大约有 100~150 页的新鲜额度，用完后转 403；
  重新预热（prepare_pool.py --force，约 8 秒）立刻恢复。

用法：
    from pool_client import PoolClient
    pc = PoolClient(n=4)              # 自动 ensure 池（没有就预热）
    r = pc.get(url, headers=extra, timeout=45)
    pc.stats()                        # 看每个 cookie 的用量/失败
"""
import json
import os
import threading
import time

from curl_cffi import requests as cr

try:
    from prepare_pool import prepare, load_pool, CACHE
except ImportError:
    CACHE = os.path.expanduser("~/.cache/ozon-search")
    prepare = None
    load_pool = None

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")

# 每个 cookie 建议的并发（超过 24 会过载，16 是稳定值）
CONCURRENCY_PER_COOKIE = 16


class PoolClient:
    def __init__(self, n=4, refresh_after_403=30, quiet=False):
        self.n = n
        self.refresh_threshold = refresh_after_403
        self.quiet = quiet
        self._lock = threading.Lock()
        self._i = 0
        self._sessions = {}          # cookie index -> curl Session
        self.fail403 = 0
        self.requests = 0
        self.per_cookie = {}         # idx -> {"ok":n, "403":n}
        self.refreshes = 0
        self.pool = self._ensure_pool()

    # ---------- 池管理 ----------
    def _ensure_pool(self):
        pool = load_pool(auto=0) if load_pool else []
        if len(pool) < self.n:
            if prepare is None:
                raise RuntimeError("需要 prepare_pool.py 来预热 cookie 池")
            if not self.quiet:
                print(f"[*] cookie 池不足（{len(pool)}/{self.n}），静默预热（约 8 秒）...")
            prepare(self.n)
            pool = load_pool(auto=0) if load_pool else []
        if not pool:
            raise RuntimeError("拿不到 cookie 池")
        if not self.quiet:
            print(f"[+] cookie 池: {len(pool)} 个会话")
        return pool

    def _refresh(self):
        """403 过多 → 重新预热整个池"""
        with self._lock:
            self.refreshes += 1
            n = self.refreshes
        if not self.quiet:
            print(f"[!] 403 过多（{self.fail403}），第 {n} 次重新预热池...")
        try:
            prepare(self.n)      # 覆盖写 pool-*.json
            with self._lock:
                self.pool = load_pool(auto=0) or self.pool
                self._sessions.clear()
                self.fail403 = 0
                self.per_cookie.clear()
        except Exception as e:
            if not self.quiet:
                print(f"[!] 补池失败: {e}")

    # ---------- 请求 ----------
    def _session(self, idx):
        with self._lock:
            s = self._sessions.get(idx)
            if s is None:
                s = cr.Session(impersonate="chrome")
                self._sessions[idx] = s
            return s

    def headers_for(self, idx, extra=None):
        c = self.pool[idx % len(self.pool)]
        h = {
            "accept": "application/json",
            "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
            "referer": "https://www.ozon.ru/",
            "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": c.get("ua") or DEFAULT_UA,
            "cookie": c["cookie"],
        }
        if extra:
            h.update(extra)
        return h

    def get(self, url, extra_headers=None, timeout=45, retry=2):
        for attempt in range(retry + 1):
            with self._lock:
                idx = self._i
                self._i += 1
                self.requests += 1
            try:
                r = self._session(idx).get(url, headers=self.headers_for(idx, extra_headers), timeout=timeout)
                with self._lock:
                    st = self.per_cookie.setdefault(idx % len(self.pool), {"ok": 0, "403": 0})
                    if r.status_code == 403:
                        self.fail403 += 1
                        st["403"] += 1
                    elif r.status_code == 200:
                        st["ok"] += 1
                if r.status_code == 403 and self.fail403 >= self.refresh_threshold:
                    self.fail403 = 0
                    threading.Thread(target=self._refresh, daemon=True).start()
                    time.sleep(1.5)
                return r
            except Exception:
                if attempt == retry:
                    raise
                time.sleep(1)
        return None

    def post(self, url, multipart=None, extra_headers=None, timeout=90):
        with self._lock:
            idx = self._i
            self._i += 1
            self.requests += 1
        return self._session(idx).post(url, headers=self.headers_for(idx, extra_headers),
                                       multipart=multipart, timeout=timeout)

    def stats(self):
        with self._lock:
            return {"requests": self.requests, "403": self.fail403,
                    "refreshes": self.refreshes,
                    "per_cookie": dict(self.per_cookie)}

    def recommended_threads(self):
        return len(self.pool) * CONCURRENCY_PER_COOKIE


if __name__ == "__main__":
    pc = PoolClient(n=4)
    print("threads:", pc.recommended_threads())
    import urllib.parse
    u = ("https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="
         + urllib.parse.quote("/seller/78486/", safe=""))
    t0 = time.time()
    r = pc.get(u)
    print(f"test: {r.status_code} {len(r.text)} {int((time.time()-t0)*1000)}ms")
    print(pc.stats())
