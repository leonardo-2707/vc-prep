#!/usr/bin/env python3
"""VC Prep: scarica le notizie, le classifica e genera il sito.

Gira ogni mattina su GitHub Actions. Nessuna AI e nessuna chiave: solo feed RSS,
parole chiave e regole trasparenti. Solo libreria standard di Python.

Uso:
  python3 scripts/update.py                 # aggiornamento normale
  python3 scripts/update.py --hours 168     # scarica una finestra più lunga
  python3 scripts/update.py --offline       # rigenera il sito senza scaricare nulla
  python3 scripts/update.py --fixtures DIR  # usa feed salvati in DIR/<id>.xml (per i test)
"""

import argparse
import hashlib
import html
import json
import re
import shutil
import ssl
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
ARCHIVE = ROOT / "data" / "archive.json"
TEMPLATE = ROOT / "template" / "index.html"
SITE = ROOT / "site"

RETENTION_DAYS = 45      # quanto tempo restano le notizie nell'archivio
MAX_ITEMS = 600          # tetto all'archivio
EXCERPT_CHARS = 260      # lunghezza massima dell'estratto mostrato

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 VCPrep/1.0")
NS = {"content": "http://purl.org/rss/1.0/modules/content/",
      "dc": "http://purl.org/dc/elements/1.1/",
      "atom": "http://www.w3.org/2005/Atom"}

# ---------------------------------------------------------------- utilità

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def ssl_context():
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"})
            with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
                return resp.read()
        except Exception as exc:  # rete, 403, timeout...
            last = exc
            time.sleep(2 * (i + 1))
    raise last


def clean_text(raw):
    if not raw:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"The post .{0,300}? appeared first on .{0,80}?\.?$", "", text.strip(), flags=re.S)
    text = re.sub(r"\s*(\[(…|\.\.\.)\]|Continue reading.*|Read more.*|Leggi tutto.*)$", "", text, flags=re.S)
    return re.sub(r"\s+", " ", text).strip()


def shorten(text, limit=EXCERPT_CHARS):
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.-–— ")
    return cut + "…"


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_url(url):
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", "", ""))


def text_of(el, path):
    found = el.find(path, NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_feed(data):
    root = ET.fromstring(data)
    out = []
    for it in root.iter("item"):
        out.append({"title": html.unescape(text_of(it, "title")), "url": text_of(it, "link"),
                    "published": text_of(it, "pubDate"), "author": text_of(it, "dc:creator"),
                    "description": text_of(it, "description")})
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = it.find("atom:link", NS)
        out.append({"title": html.unescape(text_of(it, "atom:title")),
                    "url": link.get("href", "") if link is not None else "",
                    "published": text_of(it, "atom:published") or text_of(it, "atom:updated"),
                    "author": text_of(it, "atom:author/atom:name"),
                    "description": text_of(it, "atom:summary")})
    return out

# ---------------------------------------------------------------- classificazione

def kw_regex(words):
    """Parole chiave → regex. 'recycl*' = prefisso; il resto a parola intera."""
    parts = []
    for w in words:
        w = w.strip().lower()
        if not w:
            continue
        prefix = w.endswith("*")
        core = w[:-1] if prefix else w
        left = r"\b" if core[0].isalnum() else ""
        right = "" if prefix or not core[-1].isalnum() else r"\b"
        parts.append(left + re.escape(core) + right)
    return re.compile("|".join(parts), re.I) if parts else None


TAGS = {
    "ai": ["ai", "artificial intelligence", "intelligenza artificiale", "llm*", "machine learning", "openai", "anthropic", "mistral", "agentic", "ai agent*", "genai", "generative"],
    "deep-tech": ["quantum", "chip", "chips", "semiconductor*", "fusion", "space", "satellite*", "biotech*", "photonic*", "robot*", "humanoid*", "deep tech", "deeptech", "drone*", "defence", "defense", "neuromorphic"],
    "climate": ["climate", "energy", "battery", "batteries", "solar", "wind power", "wind farm*", "hydrogen", "carbon", "geothermal", "nuclear", "grid", "cleantech", "emission*", "steel", "recycl*", "circular", "decarboni*", "electric vehicle*", "heat pump*"],
    "fintech": ["fintech", "payment*", "banking", "neobank*", "lending", "insurtech", "crypto", "stablecoin*", "wealth", "welfare", "pagament*"],
    "europa": ["europe", "europe's", "european", "eu", "uk", "britain", "british", "london", "germany", "german", "berlin", "munich", "france", "french", "paris", "spain", "spanish", "madrid", "barcelona", "netherlands", "dutch", "amsterdam", "sweden", "swedish", "stockholm", "finland", "finnish", "helsinki", "denmark", "danish", "copenhagen", "norway", "norwegian", "oslo", "estonia", "estonian", "tallinn", "poland", "polish", "warsaw", "portugal", "portuguese", "lisbon", "ireland", "irish", "dublin", "switzerland", "swiss", "zurich", "austria", "austrian", "vienna", "belgium", "belgian", "brussels", "luxembourg", "czech", "prague", "greece", "greek", "europa", "europeo", "europea", "europee", "europei"],
    "italia": ["italy", "italian", "milan", "milano", "rome", "roma", "turin", "torino", "bologna", "naples", "napoli", "padova", "padua", "venice", "venezia", "florence", "firenze", "italia", "italiana", "italiano", "italiane", "italiani", "cdp venture"],
    "usa": ["silicon valley", "san francisco", "bay area", "new york", "u.s.", "us-based", "american", "sequoia", "andreessen", "a16z", "y combinator", "texas", "boston", "seattle"],
    "policy": ["regulation", "regulat*", "commission", "legislation", "policy", "government", "antitrust", "28th regime", "eu inc", "ministry", "governo", "legge", "decreto"],
}
TAG_RE = {k: kw_regex(v) for k, v in TAGS.items()}

STAGE_RE = re.compile(r"\b(pre-?seed|seed|series\s+[a-h]\b|serie\s+[a-h]\b|growth round|bridge round|first close|extension)", re.I)
MONEY_RE = re.compile(
    r"(?P<cur>[$€£])\s?(?P<num>\d+(?:[.,]\d+)?)\s?(?P<unit>bn|billion|b|mn|million|m|k)\b"
    r"|(?P<num2>\d+(?:[.,]\d+)?)\s?(?P<unit2>milioni|miliardi|million|billion)\s+(?:di\s+)?(?P<cur2>euro|dollari|dollars|pounds|sterline|eur|usd)",
    re.I)
ROUND_VERB_RE = re.compile(r"\b(rais\w*|funding|financing|round|lands|secures?|secured|nabs|bags|snags|grabs|picks up|backs|backed|invest\w*|raccogli\w*|finanziament\w*|chiude|completes)\b", re.I)
FUND_RE = re.compile(r"\b(new fund|debut fund|venture fund|fund\s+(ii|iii|iv|v|vi|vii|2|3|4|5|6)\b|limited partners|\blps?\b|fund of funds|nuovo fondo|fondo da|fondo di venture)", re.I)
FUND_VERB_RE = re.compile(r"\b(fund)\b.*\b(raises?|raised|closes?|closed|launch\w*|unveils?|hits)\b|\b(raises?|closes?|closed|launch\w*|unveils?)\b.*\bfund\b", re.I)
EXIT_RE = re.compile(r"\b(acquir\w*|acquisition|buys|to buy|buyout|merg\w*|ipo|goes public|go public|listing|lists on|sold to|sells to|exit|acquisisce|acquisizione|quotazione|option to buy)\b", re.I)
NOISE_RE = re.compile(r"\b(tickets?|save \$|% off|webinar|register now|sponsored|podcast|disrupt 20\d\d|startup battlefield|days? to (techcrunch )?disrupt)\b", re.I)
ITALIAN_VC_RE = re.compile(r"\b(raccoglie|raccolto|round|investiment\w*|investe|finanziament\w*|seed|serie [a-h]|venture capital|fondo|exit|acquisisce|acquisizione|unicorno|aumento di capitale)\b", re.I)
COMPANY_RE = re.compile(r"^(?P<name>.{2,80}?)\s+(raises|raised|lands|secures|nabs|bags|snags|grabs|closes|completes|picks up|gets|scores|raccoglie|chiude|ottiene)\b", re.I)

FX = {"$": 1.0, "€": 1.1, "£": 1.3, "usd": 1.0, "dollars": 1.0, "dollari": 1.0, "eur": 1.1, "euro": 1.1, "pounds": 1.3, "sterline": 1.3}


def extract_amount(text):
    m = MONEY_RE.search(text)
    if not m:
        return None
    if m.group("cur"):
        cur, num, unit = m.group("cur"), m.group("num"), m.group("unit").lower()
    else:
        num, unit = m.group("num2"), m.group("unit2").lower()
        cur = {"euro": "€", "eur": "€", "dollari": "$", "dollars": "$", "usd": "$", "pounds": "£", "sterline": "£"}[m.group("cur2").lower()]
    value = float(num.replace(",", "."))
    mult = {"k": 0.001, "m": 1, "mn": 1, "million": 1, "milioni": 1, "b": 1000, "bn": 1000, "billion": 1000, "miliardi": 1000}[unit]
    musd = value * mult * FX[cur]
    millions = value * mult
    if millions >= 1000:
        label = f"{cur}{millions / 1000:.1f}B".replace(".0B", "B")
    elif millions >= 100:
        label = f"{cur}{millions:.0f}M"
    elif millions >= 0.1:
        label = f"{cur}{millions:.1f}M".replace(".0M", "M")
    else:
        label = f"{cur}{millions * 1000:.0f}K"
    return {"label": label, "musd": round(musd, 2)}


def classify(item, source, topics, funds):
    title = item["title"]
    text = (title + " " + item["excerpt"]).lower()
    tags = [k for k, rx in TAG_RE.items() if rx and rx.search(text)]
    matched_topics = [t["id"] for t in topics if t.get("_rx") and t["_rx"].search(text)]
    watch = sorted({w for f in funds for w in f.get("watch", []) if re.search(r"\b" + re.escape(w.lower()) + r"\b", text)})

    kinds = []
    amount = extract_amount(title) or extract_amount(item["excerpt"][:300])
    stage = STAGE_RE.search(title) or STAGE_RE.search(item["excerpt"][:300])
    is_fund = bool(FUND_RE.search(title) or FUND_VERB_RE.search(title))
    if is_fund:
        kinds.append("fondi")
    funding_words = re.search(r"\b(raises|raised|lands|secures|nabs|bags|closes|raccoglie|ottiene)\b.*\b(funding|round|investment|seed|finanziamento)\b", title, re.I)
    if not is_fund and (stage or (amount and ROUND_VERB_RE.search(title)) or funding_words):
        kinds.append("round")
    if EXIT_RE.search(title):
        kinds.append("exit")

    company = None
    m = COMPANY_RE.search(title)
    if m and "round" in kinds:
        company = re.split(r"[:!,–—]\s+|\s+[-–—]\s+", m.group("name"))[-1].strip(" '\"“”‘’")
        # "Robot data startup Mecka AI" → "Mecka AI"; "Helsinki's Ambio" → "Ambio"
        company = re.split(r"\b(?:startup|company|firm|platform|maker|unicorn|scaleup|scale-up|provider|developer)\s+", company, flags=re.I)[-1]
        company = re.sub(r"^[A-Z][\w-]*['’]s\s+", "", company).strip() or None

    item.update({
        "tags": tags,
        "topics": matched_topics,
        "watch": watch,
        "kinds": kinds,
        "round": ({"amount": amount["label"] if amount else None,
                   "musd": amount["musd"] if amount else None,
                   "stage": stage.group(0).title().replace("Pre-Seed", "Pre-seed") if stage else None,
                   "company": company} if "round" in kinds or "fondi" in kinds else None),
    })
    return item


def relevant(item, mode):
    if NOISE_RE.search(item["title"]):
        return False
    signals = bool(item["kinds"] or item["watch"] or item["topics"])
    if mode == "all":
        return True
    if mode == "signals":
        return signals
    if mode == "italian":
        return bool(item["kinds"] or item["watch"] or ITALIAN_VC_RE.search(item["title"]))
    return signals


def score(item, source):
    s = 3 if source.get("recommended") else 2
    s += 4 if "round" in item["kinds"] else 0
    s += 3 if "fondi" in item["kinds"] else 0
    s += 3 if "exit" in item["kinds"] else 0
    s += min(6, 2 * len(item["topics"]))
    s += 3 if "italia" in item["tags"] else 0
    s += 2 if "europa" in item["tags"] else 0
    s += 6 if item["watch"] else 0
    musd = (item.get("round") or {}).get("musd") or 0
    s += 2 if musd >= 50 else (1 if musd >= 10 else 0)
    return s


KIND_PROMPTS = {
    "round": "Faresti questo investimento? Chiediti chi è il team, quanto è grande il mercato e se l'azienda può restituire un fondo.",
    "fondi": "Cosa dice questa raccolta sull'appetito degli LP per il venture capital in questo momento?",
    "exit": "Chi guadagna da questa exit e cosa insegna sulle strade di uscita per le startup europee?",
}


def angles(item, topics_by_id):
    out = []
    if item["watch"]:
        out.append("Riguarda un fondo che segui (" + ", ".join(item["watch"]) + "): preparati a commentarla al colloquio.")
    for tid in item["topics"][:1]:
        out.append(topics_by_id[tid]["question"])
    for k in item["kinds"]:
        if len(out) >= 2:
            break
        out.append(KIND_PROMPTS[k])
    return out[:2]

# ---------------------------------------------------------------- pipeline

def collect(sources, hours, fixtures):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    status, items = [], []
    for src in sources:
        st = {"id": src["id"], "name": src["name"], "url": src["url"], "ok": False, "found": 0, "kept": 0, "error": None}
        try:
            data = (Path(fixtures) / f"{src['id']}.xml").read_bytes() if fixtures else fetch(src["url"])
            raw = parse_feed(data)
            st["ok"] = True
        except Exception as exc:
            st["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            status.append(st)
            continue
        for r in raw:
            if not r["title"] or not r["url"]:
                continue
            if src["id"].startswith("techcrunch") and r["author"].lower() == "techcrunch events":
                continue
            if src["id"] == "sifted" and r["url"].rstrip("/").endswith("-brnd"):
                continue
            dt = parse_date(r["published"])
            if dt and dt < cutoff:
                continue
            st["found"] += 1
            items.append({"source_id": src["id"], "raw": r, "dt": dt})
        status.append(st)
    return status, items


def build_items(collected, sources_by_id, topics, funds, now):
    topics_by_id = {t["id"]: t for t in topics}
    out = {}
    for c in collected:
        src = sources_by_id[c["source_id"]]
        r = c["raw"]
        url = normalize_url(r["url"])
        item = {
            "id": hashlib.sha1(url.encode()).hexdigest()[:12],
            "url": r["url"].strip(),
            "title": re.sub(r"\s+", " ", r["title"]).strip(),
            "source": src["name"],
            "source_id": src["id"],
            "recommended": bool(src.get("recommended")),
            "date": (c["dt"] or now).isoformat(timespec="minutes"),
            "excerpt": shorten(clean_text(r["description"])),
        }
        classify(item, src, topics, funds)
        if not relevant(item, src.get("mode", "all")):
            continue
        item["score"] = score(item, src)
        item["angles"] = angles(item, topics_by_id)
        key = url
        if key not in out or out[key]["score"] < item["score"]:
            out[key] = item
    return out


def merge(archive, fresh, now):
    by_url = {normalize_url(a["url"]): a for a in archive}
    added = 0
    for key, item in fresh.items():
        if key in by_url:
            first_seen = by_url[key].get("first_seen", item["date"])
            item["first_seen"] = first_seen
        else:
            item["first_seen"] = now.isoformat(timespec="minutes")
            added += 1
        by_url[key] = item
    limit = now - timedelta(days=RETENTION_DAYS)
    merged = [a for a in by_url.values() if (parse_date(a.get("date")) or now) >= limit]
    merged.sort(key=lambda a: a["date"], reverse=True)
    return merged[:MAX_ITEMS], added


def build_site(archive, status, topics, funds, interview, sources, now):
    SITE.mkdir(exist_ok=True)
    public_topics = [{k: v for k, v in t.items() if not k.startswith("_") and k != "keywords"} for t in topics]
    bundle = {
        "generated_at": now.isoformat(timespec="minutes"),
        "sources": [{"id": s["id"], "name": s["name"], "recommended": s.get("recommended", False), "note": s.get("note")} for s in sources],
        "status": status,
        "news": archive,
        "topics": public_topics,
        "funds": funds,
        "interview": interview,
    }
    (SITE / "data.js").write_text("window.APP_DATA = " + json.dumps(bundle, ensure_ascii=False) + ";\n", encoding="utf-8")
    shutil.copyfile(TEMPLATE, SITE / "index.html")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=72, help="finestra di download in ore (default 72)")
    ap.add_argument("--offline", action="store_true", help="non scaricare, rigenera solo il sito")
    ap.add_argument("--fixtures", help="cartella con feed salvati (<id>.xml) per i test")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    sources = load_json(CONFIG / "sources.json", [])
    topics = load_json(CONFIG / "topics.json", [])
    funds = load_json(CONFIG / "funds.json", [])
    interview = load_json(CONFIG / "interview.json", {})
    for t in topics:
        t["_rx"] = kw_regex(t.get("keywords", []))
    archive = load_json(ARCHIVE, [])

    if args.offline:
        status, added = [], 0
    else:
        status, collected = collect(sources, args.hours, args.fixtures)
        fresh = build_items(collected, {s["id"]: s for s in sources}, topics, funds, now)
        for st in status:
            st["kept"] = sum(1 for i in fresh.values() if i["source_id"] == st["id"])
        archive, added = merge(archive, fresh, now)
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    build_site(archive, status, topics, funds, interview, sources, now)

    print(f"Archivio: {len(archive)} notizie ({added} nuove). Sito generato in site/.")
    failed = [s for s in status if not s["ok"]]
    for s in status:
        line = f"  {s['name']:<22} {s['id']:<20} " + (f"trovate {s['found']}, tenute {s['kept']}" if s["ok"] else f"ERRORE — {s['error']}")
        print(line)
    if status and len(failed) == len(status):
        print("Nessuna fonte raggiungibile: il sito resta con le notizie precedenti.", file=sys.stderr)


if __name__ == "__main__":
    main()
