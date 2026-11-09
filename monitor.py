import os, sys, time, json, subprocess, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *

def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True, cwd=ROOT); return r.returncode, (r.stdout + r.stderr).strip()

def healthy(url):
    last = ""
    for i in range(3):
        st, body, _, ms = get(url, timeout=20)
        if st == 200 and len(body) > 400 and "<html" in body.lower(): return True, "OK (%d ms)" % ms
        last = "status %s" % st
        if i < 2: time.sleep(15)
    return False, last

def gh(method, path, payload=None):
    req = urllib.request.Request("https://api.github.com/repos/%s/%s" % (os.environ.get("GITHUB_REPOSITORY"), path),
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""), "Accept": "application/vnd.github+json", "User-Agent": "uma-monitor"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"null")
    except Exception as e:
        print("GitHub API error:", e); return None

def open_issues():
    return [i for i in (gh("GET", "issues?state=open&per_page=50") or []) if "pull_request" not in i and i["title"].startswith("[UMA Monitor]")]

def main():
    c = cfg(); site = site_url(c)
    if not site: sys.exit("Site URL nahi mila")
    extra = [norm(u) for u in c.get("monitor_extra_urls", []) + c.get("sites_to_audit", [])]
    opened = {i["title"]: i for i in open_issues()}
    bad = []
    ok, why = healthy(site)
    print("my site:", ok, why)
    if ok:
        rc, ct = sh("git", "log", "-1", "--format=%ct", "HEAD")
        if rc == 0 and time.time() - int(ct) > 900:   # tag only commits that had time to deploy
            sh("git", "tag", "-f", "last-good", "HEAD"); sh("git", "push", "-f", "origin", "refs/tags/last-good")
    else:
        bad.append((site, why))
        msg = "Auto-rollback nahi hua."
        rc, _ = sh("git", "rev-parse", "-q", "--verify", "refs/tags/last-good")
        if rc == 0 and c.get("monitor_auto_rollback", True):
            paths = site_paths(c)
            drc, _ = sh("git", "diff", "--quiet", "last-good", "HEAD", "--", *paths)
            if drc == 1:
                for pth in paths: sh("git", "checkout", "last-good", "--", pth)
                sh("git", "commit", "-am", "UMA monitor: auto-rollback of site files to last-good")
                prc, out = sh("git", "push", "origin", "HEAD")
                msg = "Site files ko last-good version par wapas kar diya gaya." if prc == 0 else "Rollback push fail hua: " + out[-200:]
            else: msg = "Site files mein last-good ke baad koi tabdeeli nahi, is liye rollback ki zaroorat nahi (masla GitHub Pages ya network ka ho sakta hai)."
        t = "[UMA Monitor] Site down: " + site
        if t not in opened: gh("POST", "issues", {"title": t, "body": "Site check fail hui (%s).\n\n%s\n\nAgli ghante dobara check hoga." % (why, msg)})
    for u in extra:
        g, w = healthy(u); print(u, g, w)
        if not g:
            bad.append((u, w)); t = "[UMA Monitor] Site down: " + u
            if t not in opened: gh("POST", "issues", {"title": t, "body": "Check fail hui (%s). Ye site sirf monitor hoti hai, auto-rollback nahi karti." % w})
    if not bad:
        for i in opened.values():
            gh("POST", "issues/%d/comments" % i["number"], {"body": "Site wapas theek hai. Issue band kiya ja raha hai."}); gh("PATCH", "issues/%d" % i["number"], {"state": "closed"})

if __name__ == "__main__": main()
