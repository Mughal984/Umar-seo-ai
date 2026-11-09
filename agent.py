import os, re, sys, time, json
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *

DOCS = DATA = ""

def gaps(me, comps):
    ok = [c for c in comps if not c.get("error")]; out = []
    if not ok or me.get("error"): return out
    for k, n in (("words", "words"), ("h2", "H2 headings"), ("imgs", "images"), ("int", "internal links")):
        a = sum(c[k] for c in ok) / len(ok)
        if me[k] < 0.7 * a: out.append("Muqable ki sites mein average %d %s hain, tumhari site mein %d" % (a, n, me[k]))
    for k, n in (("schema", "Schema (JSON-LD)"), ("og", "Open Graph tags"), ("sitemap", "sitemap.xml"), ("canonical", "canonical tag")):
        c = sum(1 for x in ok if x[k])
        if not me[k] and c >= len(ok) / 2: out.append("%d/%d muqable sites mein %s hai, tumhari site mein nahi" % (c, len(ok), n))
    return out

def main():
    global DOCS, DATA
    c = cfg(); DOCS = os.path.join(ROOT, site_dir(c)); DATA = os.path.join(DOCS, "data")
    site = site_url(c); key = os.environ.get("GEMINI_API_KEY", ""); pk = os.environ.get("PSI_KEY", "")
    if not site: sys.exit("Site ka URL nahi mila (config.json my_site ya GITHUB_REPOSITORY)")
    SP = os.path.join(DATA, "state.json")
    st = jload(SP, {}); st.setdefault("articles", []); st.setdefault("competitors", [])
    errors = []; today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cl = c.get("content_language", "en"); rl = c.get("report_language", "rur")
    def step(name, fn, default=None):
        try: return fn()
        except Exception as e:
            errors.append("%s: %s" % (name, str(e)[:200])); print("ERR", name, e); return default
    def ai(name, prompt):
        if not key: errors.append("%s: GEMINI_API_KEY set nahi hai" % name); return None
        time.sleep(4); return step(name, lambda: gjson(prompt, key))

    # 1) site audit + speed
    targets = [site] + [norm(s) for s in c.get("sites_to_audit", [])]
    if os.environ.get("EXTRA_SITE", "").strip(): targets.append(norm(os.environ["EXTRA_SITE"]))
    targets = list(dict.fromkeys(targets)); res = []
    for i, u in enumerate(targets):
        a = audit(u)
        if not a.get("error"):
            a["speed"] = {s: step("speed %s %s" % (u, s), lambda: psi(u, s, pk)) for s in (["mobile", "desktop"] if i == 0 else ["mobile"])}
        res.append(a)
    me = res[0]

    # 2) competitors (auto-found once, then remembered)
    if not st["competitors"]:
        st["competitors"] = [norm(x) for x in c.get("competitors", [])]
    if not st["competitors"]:
        j = ai("competitors", 'Website niche: %s. Site title: %s. List 6 real, well-known websites that directly compete with it. Return JSON {"urls": ["https://example.com"]} with homepage URLs only.' % (c.get("niche", ""), me.get("title", "")))
        if j: st["competitors"] = [norm(x) for x in j.get("urls", [])][:6]
    comps = []
    for u in st["competitors"]:
        a = audit(u)
        if not a.get("error") and a.get("status", 0) < 400: a.pop("sample", None); comps.append(a)
    comps = comps[:5]; gp = gaps(me, comps)

    # 3) keywords, tags, titles, topics
    kw = {"count": 0, "questions": [], "others": [], "tags": [], "titles": []}; topics = []
    allk = step("keywords", lambda: keywords(c.get("seed_keywords", ["seo checker"]), HL.get(cl, "en")), []) or []
    qr = re.compile(r"^(how|what|why|is|can|when|which|should)\b")
    kw["count"] = len(allk); kw["questions"] = [k for k in allk if qr.match(k)][:80]; kw["others"] = [k for k in allk if not qr.match(k)][:120]
    used = [a["keyword"] for a in st["articles"]]
    j = ai("keywords-ai", 'Site niche: %s. Language of output: %s. From this real Google Autocomplete keyword list pick the best article topics, tags and title ideas. Use or lightly rephrase given keywords only. Already written keywords (avoid): %s.\nKeywords: %s\nReturn JSON {"tags":[15 short tags],"titles":[5 SEO title ideas under 60 chars],"topics":[{"keyword":"...","title":"..."}] with %d items}.' % (
        c.get("niche", ""), LANG.get(cl), used[-30:], "; ".join(allk[:200]), int(c.get("articles_per_run", 1)) + 3)) if allk else None
    if j: kw["tags"] = [str(x) for x in j.get("tags", [])][:15]; kw["titles"] = [str(x) for x in j.get("titles", [])][:5]; topics = [t for t in j.get("topics", []) if isinstance(t, dict) and t.get("keyword")]

    # 4) articles
    made = 0
    for t in topics:
        if made >= int(c.get("articles_per_run", 1)): break
        if t["keyword"].lower() in [u.lower() for u in used]: continue
        a = ai("article", 'Write an SEO article in %s for the keyword "%s" (working title: "%s") for a site about: %s.\nRules: practical, accurate, no invented statistics, quotes, names or claims you cannot be sure of. 700 to 1000 words. Body HTML only using h2,h3,p,ul,ol,li,strong,em,table (no h1, no scripts). Return JSON {"title":"...","description":"max 155 chars","html":"..."}.' % (LANG.get(cl), t["keyword"], t.get("title", ""), c.get("niche", "")))
        if not a: continue
        body = sanitize(str(a.get("html", ""))); words = len(re.sub(r"<[^>]+>", " ", body).split())
        if words < 350: errors.append("article: bahut chhota (%d words), publish nahi kiya" % words); continue
        title = str(a.get("title") or t.get("title") or t["keyword"])[:110]; desc = str(a.get("description", ""))[:160]
        slug = slugify(t["keyword"], "post-" + today); n = 2; base = slug
        while any(x["slug"] == slug for x in st["articles"]): slug = "%s-%d" % (base, n); n += 1
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": title, "description": desc, "datePublished": today, "mainEntityOfPage": site + "blog/%s.html" % slug}
        html = page(c, site, title, desc, '<article><h1>%s</h1><p class="meta">%s</p>%s<p class="meta">Written by the UMA SEO AI agent with Gemini.</p></article>' % (esc(title), today, body), "blog/%s.html" % slug, "../", ld, cl)
        if c.get("publish_articles", True):
            os.makedirs(os.path.join(DOCS, "blog"), exist_ok=True)
            open(os.path.join(DOCS, "blog", slug + ".html"), "w", encoding="utf-8").write(html)
            st["articles"].append({"slug": slug, "title": title, "desc": desc, "date": today, "keyword": t["keyword"]}); used.append(t["keyword"]); made += 1
    arts = sorted(st["articles"], key=lambda x: x["date"], reverse=True)
    items = "".join('<li><a href="%s.html">%s</a><br><span class="meta">%s . %s</span></li>' % (esc(a["slug"]), esc(a["title"]), a["date"], esc(a["desc"])) for a in arts) or "<li>Pehla article agli agent run mein aayega.</li>"
    os.makedirs(os.path.join(DOCS, "blog"), exist_ok=True)
    open(os.path.join(DOCS, "blog", "index.html"), "w", encoding="utf-8").write(page(c, site, "Blog - " + c.get("site_name", ""), "SEO guides written by the agent.", '<h1>Blog</h1><ul class="posts">%s</ul>' % items, "blog/index.html", "../", None, "en"))

    # 5) About + FAQ (made once, refreshed every 30 days)
    def old(k): return not st.get(k) or (datetime.now(timezone.utc) - datetime.strptime(st[k], "%Y-%m-%d").replace(tzinfo=timezone.utc)).days >= 30
    facts = "\n".join("- " + f for f in c.get("about_facts", []))
    if old("about") or not os.path.exists(os.path.join(DOCS, "about.html")):
        a = ai("about", 'Write an About Us page in %s for "%s". Use ONLY these facts, invent no names, numbers, awards, team or history:\n%s\nBody HTML only (h2,p,ul,li,strong), 250 to 400 words. Return JSON {"title":"...","description":"max 155 chars","html":"..."}.' % (LANG.get(cl), c.get("site_name"), facts))
        if a:
            t = str(a.get("title") or "About")[:100]; d = str(a.get("description", ""))[:160]
            open(os.path.join(DOCS, "about.html"), "w", encoding="utf-8").write(page(c, site, t, d, "<h1>%s</h1>%s" % (esc(t), sanitize(str(a.get("html", "")))), "about.html", "", None, cl)); st["about"] = today
    if old("faq") or not os.path.exists(os.path.join(DOCS, "faq.html")):
        a = ai("faq", 'Write 8 FAQ items in %s about the tool "%s". Use ONLY these facts about the tool, no invented claims:\n%s\nReturn JSON {"items":[{"q":"...","a":"short answer"}]}.' % (LANG.get(cl), c.get("site_name"), facts))
        if a and a.get("items"):
            its = [i for i in a["items"] if isinstance(i, dict) and i.get("q") and i.get("a")][:10]
            body = "<h1>FAQ</h1>" + "".join("<h2>%s</h2><p>%s</p>" % (esc(i["q"]), esc(i["a"])) for i in its)
            ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": str(i["q"]), "acceptedAnswer": {"@type": "Answer", "text": str(i["a"])}} for i in its]}
            open(os.path.join(DOCS, "faq.html"), "w", encoding="utf-8").write(page(c, site, "FAQ - " + c.get("site_name", ""), "Frequently asked questions.", body, "faq.html", "", ld, cl)); st["faq"] = today

    # 6) fix plan
    plan = []
    if not me.get("error"):
        sp = (me.get("speed") or {}).get("mobile") or {}
        j = ai("plan", 'You are an SEO expert. Language of output: %s. Site data: score %s/100, issues: %s. Mobile speed: %s. Competitor gaps: %s. Give a prioritised action list (most important first), specific (e.g. a better title and meta description when needed). Return JSON {"plan":[{"priority":"high|medium|low","title":"...","detail":"..."}]} with up to 8 items.' % (
            LANG.get(rl), me["score"], "; ".join(i["t"] for i in me["issues"]), json.dumps(sp), "; ".join(gp) or "none"))
        if j: plan = [p for p in j.get("plan", []) if isinstance(p, dict)][:8]

    # 7) outputs
    for a in res + comps: a.pop("sample", None)
    latest = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "site": site, "ai": bool(key), "sites": res, "competitors": comps, "gaps": gp,
              "keywords": kw, "plan": plan, "articles": arts[:20], "errors": errors}
    jdump(os.path.join(DATA, "latest.json"), latest)
    hist = [h for h in jload(os.path.join(DATA, "history.json"), []) if h.get("d") != today]
    sp = (me.get("speed") or {}).get("mobile") or {}
    hist.append({"d": today, "score": me.get("score"), "perf": sp.get("perf"), "seo": sp.get("seo")}); jdump(os.path.join(DATA, "history.json"), hist[-120:])
    pages = ["index.html", "blog/index.html", "about.html", "faq.html"] + ["blog/%s.html" % a["slug"] for a in arts]
    open(os.path.join(DOCS, "sitemap.xml"), "w", encoding="utf-8").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % "".join("<url><loc>%s</loc><lastmod>%s</lastmod></url>\n" % (esc(site + p), today) for p in pages if os.path.exists(os.path.join(DOCS, p))))
    open(os.path.join(DOCS, "robots.txt"), "w").write("User-agent: *\nAllow: /\nSitemap: %ssitemap.xml\n" % site)
    jdump(SP, st)
    print("Score:", me.get("score"), "| competitors:", len(comps), "| keywords:", kw["count"], "| new articles:", made, "| errors:", len(errors))

if __name__ == "__main__": main()
