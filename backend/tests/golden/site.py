"""Ground-truth fixture site served on localhost. Every page documents what is TRUE about it;
the golden end-to-end test crawls it with the real crawler and compares the results."""
import threading, http.server, socketserver

def words(n, w="lorem"): return " ".join(f"{w}{i}" for i in range(n))
META150 = "A clear and useful description of this page that explains the value to searchers in roughly one hundred and fifty characters total."
def page(title="Good Title Here For Page", meta=META150, h1=1, body=400, extra_head="", extra_body="", lang="en", imgs=""):
    h = "".join(f"<h1>Heading {i}</h1>" for i in range(h1))
    t = f"<title>{title}</title>" if title else ""
    m = f'<meta name="description" content="{meta}">' if meta else ""
    return f'<!doctype html><html lang="{lang}"><head>{t}{m}{extra_head}</head><body><nav><a href="/">Home</a> <a href="/thin">t</a></nav>{h}<p>{words(body)}</p>{imgs}{extra_body}</body></html>'

JSON_LD = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"X"}</script>'
# 600 words of inline JS: NOT visible content
BIG_JS = "<script>var data=[" + ",".join(f'"w{i}"' for i in range(600)) + "];</script>"
BIG_CSS = "<style>" + " ".join(f".c{i}{{color:red}}" for i in range(300)) + "</style>"

PAGES = {
 "/":            (200, {}, page(body=500, extra_head=JSON_LD, imgs='<img src="/a.png" alt="a"><img src="/b.png" alt="b">') ),
 "/thin":        (200, {}, page(body=40, extra_head=BIG_JS + BIG_CSS)),                 # TRUTH: thin (40 visible words)
 "/no-title":    (200, {}, page(title="", meta="", h1=0, body=400)),                    # TRUTH: no title, no meta, no h1
 "/dup1":        (200, {}, page(title="Dup One Title Page", meta=META150, body=400)),   # TRUTH: meta dup with /dup2 and /
 "/dup2":        (200, {}, page(title="Dup Two Title Page", meta=META150, body=400)),
 "/noindex-meta":(200, {}, page(extra_head='<meta name="robots" content="noindex">')),  # TRUTH: noindex
 "/noindex-gbot":(200, {}, page(extra_head='<meta name="googlebot" content="noindex">')),# TRUTH: noindex
 "/noindex-hdr": (200, {"X-Robots-Tag": "noindex"}, page()),                           # TRUTH: noindex
 "/multi-h1":    (200, {}, page(h1=2)),                                                 # TRUTH: 2 h1
 "/alt":         (200, {}, page(imgs='<img src="/1.png" alt="ok"><img src="/2.png"><img src="/3.png" alt="">')),  # TRUTH: 1 missing alt (alt="" is decorative = valid)
 "/hindi":       (200, {}, page(lang="hi", title="हिंदी पृष्ठ का शीर्षक यहाँ", body=400)),           # TRUTH: valid indexable page
 "/de":          (200, {}, page(lang="de", title="Deutsche Seite mit gutem Titel", body=400)),       # TRUTH: valid indexable page
 "/desc-case":   (200, {}, page(meta="", extra_head=f'<meta name="Description" content="{META150} unique-case">')),  # TRUTH: HAS a description
 "/canon":       (200, {}, page(extra_head='<link rel="canonical" href="/">')),         # TRUTH: canonicalised to /
 "/links":       (200, {}, page(extra_body='<a href="/missing-page">broken</a><a href="mailto:a@b.co">m</a><a href="tel:123">t</a><a href="javascript:void(0)">j</a><a href="#frag">f</a><a href="https://external.example/x">e</a><a href="/alt">ok</a>')),
}
TRUE_URLS = sorted(PAGES)            # 15 real pages
INDEX_LINKS = "".join(f'<a href="{u}">{u}</a>' for u in PAGES if u != "/")
PAGES["/"] = (200, {}, PAGES["/"][2].replace("</body>", INDEX_LINKS + "</body>"))

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/robots.txt":
            body, code, hdr = b"User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}
        elif p in PAGES:
            code, hdr, html = PAGES[p]; body = html.encode(); hdr = {**hdr, "Content-Type": "text/html; charset=utf-8"}
        else:
            code, body, hdr = 404, b"<html><body>not found</body></html>", {"Content-Type": "text/html"}
        self.send_response(code)
        for k, v in hdr.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True

def serve(port=0):
    s = S(("127.0.0.1", port), H); threading.Thread(target=s.serve_forever, daemon=True).start(); return s
