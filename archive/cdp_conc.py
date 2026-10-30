import json, subprocess, tempfile, time, urllib.request, urllib.parse, threading, sys
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 8
BASE = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"

class Inst:
    def __init__(self, idx):
        self.port = 9400 + idx
        self.profile = tempfile.mkdtemp(prefix=f"ozon-c{idx}-")
        cmd = [CHROME, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
               "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
               "--disable-blink-features=AutomationControlled", "about:blank"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None; self._i = 0
    def connect(self):
        for _ in range(50):
            time.sleep(0.4)
            try:
                d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2))
                pages = [t for t in d if t["type"]=="page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    self.ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
                    self.call("Page.enable"); self.call("Runtime.enable")
                    return True
            except Exception: pass
        return False
    def call(self, m, params=None, timeout=90):
        self._i += 1; mid = self._i
        self.ws.send(json.dumps({"id":mid,"method":m,"params":params or {}}))
        t0 = time.time()
        while time.time()-t0 < timeout:
            r = json.loads(self.ws.recv())
            if r.get("id") == mid: return r
        raise TimeoutError(m)
    def ev(self, expr, await_p=True):
        r = self.call("Runtime.evaluate", {"expression":expr,"awaitPromise":await_p,"returnByValue":True})
        return r.get("result",{}).get("result",{}).get("value")
    def warm(self):
        self.call("Page.navigate", {"url":"https://www.ozon.ru/"})
        t0 = time.time()
        while time.time()-t0 < 45:
            time.sleep(3)
            try:
                t = self.ev("document.title") or ""
                c = self.ev("document.cookie.length") or 0
                if "Challenge" not in str(t) and c > 20: return round(time.time()-t0,1)
            except Exception: pass
        return -1
    def fetch_page(self, n):
        url = "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(BASE + f"&page={n}", safe="")
        js = """(async()=>{const t0=performance.now();const r=await fetch(%s,{headers:{accept:'application/json'}});const t=await r.text();
        return JSON.stringify({s:r.status,ms:Math.round(performance.now()-t0),len:t.length});})()""" % json.dumps(url)
        t0 = time.time()
        try:
            v = self.ev(js); return json.loads(v), round(time.time()-t0,2)
        except Exception as e:
            return {"s":"ERR","err":str(e)[:40]}, round(time.time()-t0,2)

insts = [Inst(i) for i in range(N)]
print("starting...", [i.port for i in insts])
for i in insts:
    ok = i.connect(); print(" connected", i.port, ok)
warm = {}
def w(i):
    warm[i.port] = i.warm()
ths = [threading.Thread(target=w, args=(i,)) for i in insts]
[t.start() for t in ths]; [t.join() for t in ths]
print("warmup secs:", warm)

results = []
lock = threading.Lock()
def run(i, offset):
    for k in range(PAGES):
        r, wall = i.fetch_page(offset + k + 1)
        with lock: results.append({"port": i.port, **r, "wall": wall})
ths = [threading.Thread(target=run, args=(i, iidx*100)) for iidx, i in enumerate(insts)]
t0 = time.time()
[t.start() for t in ths]; [t.join() for t in ths]
total = time.time() - t0
ok = [r for r in results if r.get("s")==200]
ms = sorted(r["ms"] for r in ok)
print(f"\n== {N} instances x {PAGES} pages ==")
print(f"wall: {total:.1f}s  ok: {len(ok)}/{len(results)}")
if ms: print(f"per-request median: {ms[len(ms)//2]}ms  min {ms[0]}  max {ms[-1]}")
print(f"throughput: {len(ok)/total:.2f} pages/s = {len(ok)/total*8:.1f} SKU/s")
print("by instance:", {p: sum(1 for r in results if r['port']==p and r.get('s')==200) for p in [i.port for i in insts]})
for i in insts:
    try: i.ws.close()
    except Exception: pass
    i.p.terminate()
