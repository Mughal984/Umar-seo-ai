import json, os, re, time, html as H, urllib.request, urllib.parse, urllib.error
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "agent" else HERE
UA = {"User-Agent": "Mozilla/5.0 (compatible; UMA-SEO-AI-Agent/1.0)"}
esc = lambda s: H.escape(str(s if s is not None else ""), quote=True)
LANG = {"en": "English", "rur": "Roman Urdu (Urdu written in English letters)", "ur": "Urdu (Urdu script)", "hi": "Hindi (Devanagari script)"}
HL = {"en": "en", "rur": "en", "ur": "ur", "hi": "hi"}

def jload(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return d

def jdump(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f: json.dump(o, f, ensure_ascii=False, indent=1)

def cfg():
    return jload(os.path.join(ROOT, "config.json"), {})

SITE_FILES = ["index.html", "style.css", "about.html", "faq.html", "blog", "data", "sitemap.xml", "robots.txt"]
def site_dir(c):
    return (c.get("site_dir", "docs") or "").strip("/")

def site_paths(c):
    d = site_dir(c)
    return [d] if d else SITE_FILES

def site_url(c):
    u = c.get("my_site") or ""
    if not u:
        r = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in r:
            o, n = r.split("/", 1)
            u = "https://%s.github.io/%s" % (o.lower(), "" if n.lower() == o.lower() + ".github.io" else n)
    return (u.rstrip("/") + "/") if u else ""

def get(url, timeout=25, headers=None, data=None):
    h = dict(UA); h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1500000)
            return r.status, raw.decode(r.headers.get_content_charset() or "utf-8", "replace"), r.geturl(), int((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200000).decode("utf-8", "replace"), url, int((time.time() - t0) * 1000)
    except Exception as e:
        return 0, str(e), url, int((time.time() - t0) * 1000)

def norm(u):
    u = (u or "").strip()
    return u if re.match(r"^https?://", u, re.I) else "https://" + u

def ok_url(u):
    p = urllib.parse.urlparse(u); h = p.hostname or ""
    return p.scheme in ("http", "https") and "." in h and not re.match(r"^(10\.|127\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)", h)

def exists(origin, p):
    st, b, _, _ = get(origin + p, timeout=15)
    return st == 200 and "<html" not in b[:300].lower() and "<!doctype" not in b[:300].lower()

def audit(url):
    url = norm(url)
    if not ok_url(url): return {"url": url, "error": "URL sahi nahi hai"}
    st, html, fin, ms = get(url)
    if st == 0: return {"url": url, "error": "Site khuli nahi: " + html[:100]}
    u = urllib.parse.urlparse(fin)
    def g(rx):
        m = re.search(rx, html, re.I | re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    has = lambda rx: bool(re.search(rx, html, re.I))
    cnt = lambda rx: len(re.findall(rx, html, re.I))
    title = g(r"<title[^>]*>(.*?)</title>")
    meta = g(r"<meta[^>]+name=[\"']description[\"'][^>]*content=[\"']([^\"']*)") or g(r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*name=[\"']description[\"']")
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    no_alt = sum(1 for i in imgs if not re.search(r"\balt=[\"'][^\"']+[\"']", i, re.I))
    intl = ext = 0
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"'#][^\"']*)[\"']", html, re.I):
        try: l = urllib.parse.urlparse(urllib.parse.urljoin(fin, m.group(1)))
        except ValueError: continue
        if l.scheme not in ("http", "https"): continue
        if l.hostname == u.hostname: intl += 1
        else: ext += 1
    text = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", " ", html, flags=re.I)
    text = re.sub(r"&nbsp;|\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    origin = "%s://%s" % (u.scheme, u.netloc)
    a = dict(url=fin, status=st, ms=ms, title=title, meta=meta, h1=cnt(r"<h1[\s>]"), h2=cnt(r"<h2[\s>]"),
        words=len(text.split()) if text else 0, imgs=len(imgs), no_alt=no_alt, int=intl, ext=ext,
        canonical=has(r"<link[^>]+rel=[\"']canonical[\"']"), viewport=has(r"<meta[^>]+name=[\"']viewport[\"']"),
        lang=has(r"<html[^>]+lang="), og=has(r"property=[\"']og:title[\"']"), schema=has(r"application/ld\+json"),
        noindex=has(r"<meta[^>]+name=[\"']robots[\"'][^>]*noindex"), https=u.scheme == "https",
        robots=exists(origin, "/robots.txt"), sitemap=exists(origin, "/sitemap.xml"))
    I = []; s = [100]
    def pen(n, lv, t): s[0] -= n; I.append({"l": lv, "t": t})
    if st >= 400: pen(40, "bad", "Page ka status %d hai" % st)
    if not title: pen(12, "bad", "Title tag nahi hai")
    elif not 30 <= len(title) <= 65: pen(5, "warn", "Title %d characters ka hai (behtar: 30 se 65)" % len(title))
    if not meta: pen(10, "bad", "Meta description nahi hai")
    elif not 70 <= len(meta) <= 160: pen(4, "warn", "Meta description %d characters ki hai (behtar: 70 se 160)" % len(meta))
    if a["h1"] == 0: pen(10, "bad", "H1 heading nahi hai")
    elif a["h1"] > 1: pen(4, "warn", "H1 %d hain, sirf 1 hona chahiye" % a["h1"])
    if a["h2"] == 0: pen(3, "warn", "Koi H2 heading nahi")
    if a["words"] < 300: pen(8, "warn", "Content kam hai (%d words), kam az kam 300 rakho" % a["words"])
    if no_alt: pen(min(8, no_alt), "warn", "%d images par alt text nahi hai" % no_alt)
    if not a["canonical"]: pen(3, "warn", "Canonical tag nahi hai")
    if not a["viewport"]: pen(8, "bad", "Mobile viewport tag nahi hai")
    if not a["lang"]: pen(2, "warn", "html lang nahi hai")
    if not a["og"]: pen(2, "warn", "Open Graph (share preview) tags nahi hain")
    if not a["schema"]: pen(2, "warn", "Schema (JSON-LD) nahi hai")
    if a["noindex"]: pen(30, "bad", "Page par noindex laga hai, Google isay index nahi karega")
    if not a["https"]: pen(10, "bad", "Site HTTPS par nahi hai")
    if not a["robots"]: pen(2, "warn", "robots.txt nahi mili")
    if not a["sitemap"]: pen(3, "warn", "sitemap.xml nahi mili")
    if ms > 2500: pen(4, "warn", "Server jawab dene mein %d ms le raha hai" % ms)
    if not I: I.append({"l": "ok", "t": "Koi bara masla nahi mila"})
    a["score"] = max(0, s[0]); a["issues"] = I; a["sample"] = text[:3000]
    return a

def psi(url, strategy, key):
    q = urllib.parse.urlencode({"url": url, "strategy": strategy}) + "".join("&category=" + c for c in ["performance", "seo", "accessibility", "best-practices"])
    if key: q += "&key=" + key
    for i in range(3):
        st, body, _, _ = get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + q, timeout=120)
        if st == 200: break
        if st in (429, 500, 503) and i < 2: time.sleep(25); continue
        raise RuntimeError("PageSpeed error %s" % st)
    d = json.loads(body)["lighthouseResult"]; c = d["categories"]; a = d["audits"]
    sc = lambda k: round((c[k].get("score") or 0) * 100)
    v = lambda k: (a.get(k) or {}).get("displayValue", "-")
    return {"perf": sc("performance"), "seo": sc("seo"), "acc": sc("accessibility"), "bp": sc("best-practices"),
            "fcp": v("first-contentful-paint"), "lcp": v("largest-contentful-paint"), "tbt": v("total-blocking-time"), "cls": v("cumulative-layout-shift")}

def suggest(q, hl):
    st, b, _, _ = get("https://suggestqueries.google.com/complete/search?client=firefox&hl=%s&q=%s" % (hl, urllib.parse.quote(q)), timeout=15)
    try: return json.loads(b)[1] if st == 200 else []
    except Exception: return []

def keywords(seeds, hl):
    qs = []
    for q in seeds:
        qs += [q] + [q + " " + c for c in "abcdefghijklmnopqrstuvwxyz"] + [w + " " + q for w in ("how", "what", "why", "best", "is", "can")]
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda x: suggest(x, hl), qs))
    seen, out = set(), []
    for k in sum(res, []):
        k = k.strip().lower()
        if k and k not in seen: seen.add(k); out.append(k)
    return out

def gemini(prompt, key, json_mode=False):
    model = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_mode: body["generationConfig"] = {"responseMimeType": "application/json"}
    for i in range(4):
        st, txt, _, _ = get("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model, timeout=180,
                            headers={"Content-Type": "application/json", "x-goog-api-key": key}, data=json.dumps(body).encode())
        if st == 200:
            c = (json.loads(txt).get("candidates") or [{}])[0]
            out = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
            if out: return out
            raise RuntimeError("Gemini ne khali jawab diya")
        if st in (429, 500, 503): time.sleep(20 * (i + 1)); continue
        raise RuntimeError("Gemini error %s: %s" % (st, txt[:160]))
    raise RuntimeError("Gemini limit/busy (429), agli run mein dobara try hoga")

def gjson(prompt, key):
    t = re.sub(r"^```(?:json)?|```$", "", gemini(prompt, key, True).strip(), flags=re.M).strip()
    return json.loads(t)

ALLOWED = {"h2", "h3", "h4", "p", "ul", "ol", "li", "strong", "em", "b", "i", "blockquote", "br", "table", "thead", "tbody", "tr", "th", "td", "a"}
DROP = {"script", "style", "iframe", "object", "embed", "svg", "form"}
class _Clean(HTMLParser):
    def __init__(s): super().__init__(convert_charrefs=True); s.out = []; s.skip = 0
    def handle_starttag(s, tag, attrs):
        if tag in DROP: s.skip += 1; return
        if s.skip or tag not in ALLOWED: return
        if tag == "a":
            h = dict(attrs).get("href") or ""
            s.out.append('<a href="%s" rel="nofollow noopener">' % esc(h) if re.match(r"^(https?://|/|#)", h) else "<a>")
        else: s.out.append("<%s>" % tag)
    def handle_endtag(s, tag):
        if tag in DROP: s.skip = max(0, s.skip - 1); return
        if not s.skip and tag in ALLOWED and tag != "br": s.out.append("</%s>" % tag)
    def handle_data(s, d):
        if not s.skip: s.out.append(esc(d))
def sanitize(h):
    h = re.sub(r"^```(?:html)?|```$", "", h.strip(), flags=re.M)
    p = _Clean(); p.feed(h); p.close(); return "".join(p.out)

def slugify(s, fallback="post"):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]
    return s or fallback

NAV = [("Dashboard", "index.html"), ("Blog", "blog/index.html"), ("About", "about.html"), ("FAQ", "faq.html")]
def page(c, site, title, desc, body, path, root="", ld=None, lang="en"):
    nav = "".join('<a href="%s%s">%s</a>' % (root, h, n) for n, h in NAV)
    j = ('<script type="application/ld+json">%s</script>' % json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")) if ld else ""
    return ('<!doctype html><html lang="%s"%s><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><meta name="description" content="%s"><link rel="canonical" href="%s"><meta property="og:title" content="%s">'
        '<meta property="og:description" content="%s"><meta property="og:type" content="website"><link rel="stylesheet" href="%sstyle.css">%s</head>'
        '<body><header><a class="brand" href="%sindex.html">%s</a><nav>%s</nav></header><main>%s</main>'
        '<footer>Automated by the %s agent. Competitor search volume and backlinks need paid data, so they are not shown.</footer></body></html>') % (
        "ur" if lang == "ur" else "hi" if lang == "hi" else "en", ' dir="rtl"' if lang == "ur" else "", esc(title), esc(desc),
        esc(site.rstrip("/") + "/" + path), esc(title), esc(desc), root, j, root, esc(c.get("site_name", "UMA SEO AI")), nav, body, esc(c.get("site_name", "UMA SEO AI")))
