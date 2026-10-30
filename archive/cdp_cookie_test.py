import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
API = "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + "&page=3", safe="")

class Inst:
    def __init__(self, tag, port):
        self.port = port; self.tag = tag
        self.profile = tempfile.mkdtemp(prefix=f"ozon-ck-{tag}-")
        self.p = subprocess.Popen([CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
            "--no-first-run","--no-default-browser-check","--window-size=1440,900",
            "--disable-blink-features=AutomationControlled","about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._i = 0; self.ws = None
    def connect(self):
        for _ in range(60):
            time.sleep(0.4)
            try:
                d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2))
                pg = [t for t in d if t["type"]=="page" and t.get("webSocketDebuggerUrl")]
                if pg:
                    self.ws = websocket.create_connection(pg[0]["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
                    self.call("Page.enable"); self.call("Runtime.enable"); self.call("Network.enable")
                    return True
            except Exception: pass
        return False
    def call(self, m, params=None, timeout=90):
        self._i += 1; mid=self._i
        self.ws.send(json.dumps({"id":mid,"method":m,"params":params or {}}))
        t0=time.time()
        while time.time()-t0<timeout:
            r=json.loads(self.ws.recv())
            if r.get("id")==mid: return r
        raise TimeoutError(m)
    def ev(self, expr):
        r=self.call("Runtime.evaluate",{"expression":expr,"awaitPromise":True,"returnByValue":True})
        return r.get("result",{}).get("result",{}).get("value")
    def warm(self):
        self.call("Page.navigate",{"url":"https://www.ozon.ru/"})
        t0=time.time()
        while time.time()-t0<50:
            time.sleep(2.5)
            try:
                t=str(self.ev("document.title") or ""); c=self.ev("document.cookie.length") or 0
                if "Challenge" not in t and c>20: return round(time.time()-t0,1)
            except Exception: pass
        return -1
    def cookies(self):
        r=self.call("Network.getAllCookies")
        return r.get("result",{}).get("cookies",[])
    def fetch(self, url):
        js=("(async()=>{const t0=performance.now();const r=await fetch(%s,{headers:{accept:'application/json'}});"
            "const t=await r.text();return JSON.stringify({s:r.status,ms:Math.round(performance.now()-t0),len:t.length});})()") % json.dumps(url)
        v=self.ev(js); return json.loads(v) if v else {"s":"ERR"}
    def stop(self):
        try: self.ws.close()
        except Exception: pass
        self.p.terminate()

A = Inst("A", 9500); A.connect()
print("A warm:", A.warm())
print("A fetch(before export):", A.fetch(API))
ck = [c for c in A.cookies() if "ozon" in c.get("domain","")]
print("A cookies:", len(ck), [c["name"] for c in ck])
json.dump(ck, open("/tmp/ozon-fresh-cookies.json","w"))

# B: 不预热，只注入 cookie
Bw = Inst("B", 9501); Bw.connect()
Bw.call("Page.navigate",{"url":"https://www.ozon.ru/robots.txt"}); time.sleep(2)
n=0
for c in ck:
    try:
        Bw.call("Network.setCookie", {"name":c["name"],"value":c["value"],"domain":c["domain"],"path":c.get("path","/"),
                                      "secure":bool(c.get("secure")),"httpOnly":bool(c.get("httpOnly"))})
        n+=1
    except Exception as e: pass
print("B injected:", n)
Bw.call("Page.navigate",{"url":"https://www.ozon.ru/robots.txt"}); time.sleep(1.5)
print("B title:", Bw.ev("document.title"))
print("B fetch(no warm, with cookie):", Bw.fetch(API))
print("B fetch again:", Bw.fetch(API))
A.stop(); Bw.stop()
