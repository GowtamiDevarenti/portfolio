#!/usr/bin/env python3
"""
Swedish Remote Job Agent — Gowtami Devarenti
============================================

Searches Sweden's official job board API (Platsbanken / JobTech) every hour for
remote / work-from-home roles matching your profile, remembers jobs it has
already seen, and emails you a digest with one-click apply links plus a
ready-to-send, personalised cover letter draft for each match.

Honest note: fully automatic submission of applications is not possible in a
safe/allowed way — most career portals (LinkedIn, Arbetsformedlingen apply
flows) prohibit bots and require your login. This agent automates everything up
to the final click: finding, filtering, deduplicating, ranking, drafting the
cover letter, and delivering it to your inbox hourly. You review and click.

Setup (GitHub Actions — free, runs 24/7 even when your laptop is off):
  1. Push this folder to a GitHub repo, e.g. "job-agent".
  2. Add repo Secrets (Settings -> Secrets and variables -> Actions):
       SMTP_USER   = your Gmail address
       SMTP_PASS   = a Gmail App Password (myaccount.google.com/apppasswords)
       MAIL_TO     = the inbox where you want the digest
  3. The workflow in .github/workflows/hourly.yml runs this every hour.
Local run:  python job_agent.py            (one pass, prints digest)
            python job_agent.py --loop     (runs every hour locally)
"""

import json, os, re, smtplib, ssl, sys, time, datetime
import urllib.request, urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ----------------------------- CONFIG ---------------------------------------
API = "https://jobsearch.api.jobtechdev.se/search"

# Roles you want — mostly sales / business / customer-facing, plus junior
# Python/AI roles that bridge your business + tech profile.
ROLE_QUERIES = [
    "account manager", "business development", "business developer",
    "customer success", "customer relationship", "key account manager",
    "sales manager", "sales executive", "inside sales",
    "customer service swedish english", "junior python", "AI junior",
]

# Remote signals in Swedish + English job ads
REMOTE_WORDS = ["remote", "distans", "work from home", "hemifrån",
                "hybrid remote", "fully remote", "på distans", "remote work"]

MAX_PER_QUERY = 20          # newest 20 hits per role query
STATE_FILE = "seen_jobs.json"
CSV_FILE = "matches.csv"

PROFILE = {
    "name": "Gowtami Devarenti",
    "phone": "+46769798346",
    "email": os.environ.get("SMTP_USER", "your.email@gmail.com"),
    "github": "https://github.com/GowtamiDevarenti",
}

COVER_LETTER = """Hej {company} team,

I would like to apply for the {title} position.

I am a business and sales professional with an MBA in Finance and hands-on
entrepreneurial experience in business development, sales negotiation, and
customer relationship management. I have managed the full sales cycle from
lead generation to closing, built and trained a team of 40 sales
professionals, and founded and run my own businesses.

I now combine this business experience with strong Python skills, building
AI-powered solutions for sales, marketing and customer engagement automation.
Based in Sweden and fully set up for remote work, I am confident I can
contribute to your team from day one.

I would welcome the chance to discuss how my background fits your needs.

Best regards,
Gowtami Devarenti
Phone: {phone}
GitHub: {github}
"""

# ----------------------------- HELPERS --------------------------------------
def api_search(query):
    params = urllib.parse.urlencode({"q": query, "limit": MAX_PER_QUERY,
                                     "sort": "pubdate-desc"})
    req = urllib.request.Request(f"{API}?{params}",
                                 headers={"User-Agent": "job-agent/1.0",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("hits", [])

def is_remote(job):
    text = " ".join([
        job.get("headline", ""),
        (job.get("working_hours_type") or {}).get("label", ""),
        (job.get("description") or {}).get("text", "")[:4000],
    ]).lower()
    return any(w in text for w in REMOTE_WORDS)

def norm(job):
    emp = (job.get("employer") or {}).get("name", "Unknown")
    return {
        "id": job.get("id"),
        "title": job.get("headline", "N/A"),
        "company": emp,
        "location": (job.get("workplace_address") or {}).get("municipality", "Sweden"),
        "published": (job.get("publication_date") or "")[:10],
        "url": job.get("webpage_url") or job.get("application_details", {}).get("url", ""),
    }

def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            return set(json.load(open(STATE_FILE)))
        except Exception:
            return set()
    return set()

def save_seen(seen):
    json.dump(sorted(seen), open(STATE_FILE, "w"))

def rank(j):
    t = j["title"].lower()
    score = 0
    for kw in ["account manager", "business development", "business developer",
               "customer success", "key account", "sales"]:
        if kw in t:
            score += 2
    for kw in ["python", "ai", "automation", "junior", "trainee"]:
        if kw in t:
            score += 1
    return -score

def send_email(matches):
    user = os.environ.get("SMTP_USER"); pw = os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO", user)
    if not user or not pw:
        print("[email] SMTP_USER/SMTP_PASS not set — skipping email, digest below.")
        return False
    body = [f"{len(matches)} new remote job(s) in Sweden — {datetime.date.today()}\n"]
    for m in matches:
        letter = COVER_LETTER.format(company=m['company'], title=m['title'],
                                     phone=PROFILE['phone'], github=PROFILE['github'])
        body.append(f"### {m['title']} @ {m['company']} ({m['location']})")
        body.append(f"Apply: {m['url']}\n")
        body.append("Cover letter draft:\n" + letter)
        body.append("-" * 60 + "\n")
    msg = MIMEMultipart()
    msg["Subject"] = f"[Job Agent] {len(matches)} new remote jobs — {datetime.date.today()}"
    msg["From"] = user; msg["To"] = to
    msg.attach(MIMEText("\n".join(body), "plain", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls(context=ctx); s.login(user, pw); s.sendmail(user, to, msg.as_string())
    print(f"[email] digest sent to {to}")
    return True

# ----------------------------- MAIN -----------------------------------------
def run_once():
    seen = load_seen()
    found = {}
    for q in ROLE_QUERIES:
        try:
            hits = api_search(q)
        except Exception as e:
            print(f"[warn] query '{q}' failed: {e}")
            continue
        for job in hits:
            j = norm(job)
            if j["id"] and j["id"] not in seen and is_remote(job):
                found[j["id"]] = j
        time.sleep(1)  # be polite to the public API

    matches = sorted(found.values(), key=rank)
    if matches:
        seen.update(found.keys()); save_seen(seen)
        with open(CSV_FILE, "a", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write("date,title,company,location,url\n")
            for m in matches:
                f.write(f"{datetime.date.today()},"
                        f"\"{m['title']}\",\"{m['company']}\",{m['location']},{m['url']}\n")
    print(f"[{datetime.datetime.now():%H:%M}] {len(matches)} new remote matches.")
    for m in matches[:15]:
        print(f"  - {m['title']} @ {m['company']} ({m['location']})")
        print(f"    {m['url']}")
    send_email(matches)
    return len(matches)

if __name__ == "__main__":
    if "--loop" in sys.argv:
        print("Job agent running — checking every hour. Ctrl+C to stop.")
        while True:
            run_once()
            time.sleep(3600)
    else:
        run_once()
