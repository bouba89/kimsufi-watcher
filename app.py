#!/usr/bin/env python3
"""Kimsufi watcher : surveillance des disponibilités OVH Eco + interface web + alertes Discord.

Lancement :
    KW_USER=admin KW_PASS=monmotdepasse gunicorn -w 1 --threads 4 -b 0.0.0.0:8080 app:app

IMPORTANT : un seul worker (-w 1), sinon le thread de surveillance est dupliqué
et vous recevrez les alertes en double.
"""
import hmac
import json
import os
import re
import threading
import time
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, Response, jsonify, request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("KW_DATA", BASE)  # dossier de stockage (volume en Docker)
os.makedirs(DATA, exist_ok=True)
CONF_FILE = os.path.join(DATA, "config.json")
HIST_FILE = os.path.join(DATA, "history.json")
API = "https://eu.api.ovh.com/v1/dedicated/server/datacenter/availabilities"
CATALOG = "https://eu.api.ovh.com/v1/order/catalog/public/eco?ovhSubsidiary=FR"
ORDER_URL = "https://eco.ovhcloud.com"

UI_USER = os.environ.get("KW_USER", "admin")
UI_PASS = os.environ.get("KW_PASS", "changeme")

DEFAULT_CONF = {
    "webhook": "",
    "interval": 30,
    "mention": True,
    "rules": [
        {"plan": "27skle03-v1", "memory": "ram-32g", "storage": "x4000", "enabled": True}
    ],
}

app = Flask(__name__)
lock = threading.RLock()
state = {"data": [], "last": None, "error": None}
alerted = set()
names = {}        # planCode -> nom commercial (KS-LE-3...)
names_ts = 0.0    # dernière tentative de chargement du catalogue
plan_prices = {}  # planCode -> {"month": prix HT/mois, "setup": frais d'installation HT}
addon_prices = {}  # code d'option -> {"month": prix HT/mois, "setup": frais d'installation HT}
raw_pricings = {}  # code -> pricings bruts du catalogue (pour le debug)
TVA = 1.20        # TVA française
plan_addons = {}  # planCode -> ensemble des options réellement commandables


# ---------- persistance ----------
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


conf = {**DEFAULT_CONF, **load_json(CONF_FILE, {})}
history = load_json(HIST_FILE, [])


# ---------- logique de surveillance ----------
def matches(rule, s):
    return (
        rule.get("enabled", True)
        and rule.get("plan") == s.get("planCode")
        and rule.get("memory", "") in s.get("memory", "")
        and rule.get("storage", "") in s.get("storage", "")
    )


def send_discord(text):
    with lock:
        url = conf.get("webhook", "")
    if not url:
        return False, "Aucun webhook configuré"
    try:
        r = requests.post(url, json={"content": text}, timeout=10)
        r.raise_for_status()
        return True, "ok"
    except Exception as e:
        return False, str(e)


def check(data):
    """Compare l'état actuel aux règles et envoie les nouvelles alertes."""
    global alerted
    with lock:
        rules = list(conf["rules"])
        mention = conf.get("mention", True)
    current = {}
    for s in data:
        if not any(matches(r, s) for r in rules):
            continue
        if not orderable(s["planCode"], s.get("memory"), s.get("storage")):
            continue  # variante listée par l'API mais non vendue : fausse alerte
        for d in s.get("datacenters", []):
            if d["availability"] not in ("unavailable", "unknown"):
                current[(s["fqn"], d["datacenter"])] = (s, d)
    for key in current.keys() - alerted:
        s, d = current[key]
        pr, _ = fmt_price(s["planCode"], s.get("memory"), s.get("storage"))
        pr_line = f"{pr}\n" if pr else ""
        msg = (
            f"{'@everyone ' if mention else ''}{name_of(s['planCode'])} DISPONIBLE ! "
            f"\n{fmt_memory(s.get('memory'))} · {fmt_storage(s.get('storage'))}\n"
            f"{dc_name(d['datacenter'])} : {fmt_avail(d['availability'])}\n{pr_line}{ORDER_URL}"
        )
        send_discord(msg)
        nm = name_of(s["planCode"])
        with lock:
            history.insert(0, {
                "name": nm,
                "time": datetime.now().strftime("%d/%m %H:%M:%S"),
                "plan": s["planCode"], "memory": s.get("memory"),
                "storage": s.get("storage"), "dc": d["datacenter"],
                "availability": d["availability"],
            })
            del history[200:]
            save_json(HIST_FILE, history)
    alerted = set(current.keys())


DC_NAMES = {
    "bhs": "Beauharnois (Canada)", "fra": "Francfort (Allemagne)", "gra": "Gravelines (France)",
    "lon": "Londres (Royaume-Uni)", "rbx": "Roubaix (France)", "sbg": "Strasbourg (France)",
    "waw": "Varsovie (Pologne)", "lim": "Limbourg (Allemagne)", "par": "Paris (France)",
    "sgp": "Singapour", "syd": "Sydney (Australie)", "mum": "Mumbai (Inde)",
}


def dc_name(code):
    return DC_NAMES.get(code, str(code).upper())


def fmt_memory(m):
    """ram-32g-ddr4-ecc-2666 -> 32 Go DDR4 ECC 2666 MHz"""
    out = []
    for t in (m or "").split("-"):
        if t == "ram":
            continue
        x = re.fullmatch(r"(\d+)g", t)
        if x:
            out.append(f"{x.group(1)} Go")
        elif t == "noecc":
            out.append("sans ECC")
        elif re.fullmatch(r"\d{3,4}", t):
            out.append(f"{t} MHz")
        else:
            out.append(t.upper())
    return " ".join(out) or (m or "")


def _size(gb):
    return f"{gb} Go" if gb < 1000 else f"{gb / 1000:g} To".replace(".", ",")


def fmt_storage(s):
    """softraid-3x4000sa -> 3 × 4 To HDD · SoftRAID"""
    s = s or ""
    parts = s.split("-")
    modes = {"softraid": "SoftRAID", "hybridsoftraid": "SoftRAID hybride",
             "hardraid": "RAID matériel", "noraid": "sans RAID"}
    mode = modes.get(parts[0])
    disks = []
    for p in (parts[1:] if mode else parts):
        m = re.fullmatch(r"(\d+)x(\d+)(sa|ssd|nvme)", p)
        if not m:
            return s
        kind = {"sa": "HDD", "ssd": "SSD", "nvme": "NVMe"}[m.group(3)]
        disks.append(f"{m.group(1)} × {_size(int(m.group(2)))} {kind}")
    if not disks:
        return s
    return " + ".join(disks) + (f" · {mode}" if mode else "")


def fmt_avail(a):
    """1H-low -> livraison sous 1 h (stock faible)"""
    if str(a).lower() == "unknown":
        return "état inconnu"
    m = re.fullmatch(r"(\d+)H(?:-(low|high))?", str(a), re.I)
    if not m:
        return str(a)
    h = int(m.group(1))
    delay = f"{h} h" if h < 48 else f"{round(h / 24)} j"
    stock = {"low": " (stock faible)", "high": " (stock élevé)"}.get((m.group(2) or "").lower(), "")
    return f"livraison sous {delay}{stock}"


def name_of(code):
    with lock:
        return names.get(code, code)


def _price(pricings, cap):
    """Prix HT en euros d'une capacité ('renew' = mensuel, 'installation') ou None."""
    cands = []
    for p in pricings or []:
        if cap not in (p.get("capacities") or []):
            continue
        if cap == "renew" and not (p.get("intervalUnit") == "month" and p.get("interval") == 1):
            continue
        v = p.get("price")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        v = v / 1e8  # le catalogue OVH exprime les prix en 10^-8 euro
        if 0 <= v < 1000:
            cands.append((bool(p.get("commitment")), p.get("mode") != "default", v))
    return min(cands)[2] if cands else None


def eur(v):
    return f"{v:.2f}".replace(".", ",") + " €"


def orderable(plan, memory, storage):
    """False si la RAM ou le stockage ne figure pas parmi les options vendues dans le catalogue."""
    with lock:
        fam = plan_addons.get(plan)
    if not fam:
        return True  # catalogue pas encore chargé ou plan inconnu : on ne filtre pas
    return f"{memory}-{plan}" in fam and f"{storage}-{plan}" in fam
def refresh_catalog():
    """Charge noms et prix depuis le catalogue (toutes les 6 h, retry 10 min si échec)."""
    global names_ts
    with lock:
        age = time.time() - names_ts
        wait = 600 if not names else 6 * 3600
    if age < wait:
        return
    with lock:
        names_ts = time.time()
    try:
        r = requests.get(CATALOG, timeout=30)
        r.raise_for_status()
        cat = r.json()
        new_names, new_plans, new_addons, new_pa, new_raw = {}, {}, {}, {}, {}
        for p in cat.get("plans", []):
            code = p.get("planCode")
            nm = (p.get("invoiceName") or "").split("|")[0].strip()
            if code and nm:
                new_names[code] = nm
            fam = set()
            for f in p.get("addonFamilies") or []:
                fam.update(f.get("addons") or [])
            if code and fam:
                new_pa[code] = fam
            if code:
                new_raw[code] = p.get("pricings")
            month = _price(p.get("pricings"), "renew")
            setup = _price(p.get("pricings"), "installation")
            if code and (month is not None or setup is not None):
                new_plans[code] = {"month": month, "setup": setup}
        for a in cat.get("addons", []):
            code = a.get("planCode")
            if not code:
                continue
            m = _price(a.get("pricings"), "renew")
            s = _price(a.get("pricings"), "installation")
            new_raw[code] = a.get("pricings")
            if m is not None or s is not None:
                new_addons[code] = {"month": m, "setup": s}
        with lock:
            if new_names:
                names.update(new_names)
            plan_prices.update(new_plans)
            addon_prices.update(new_addons)
            plan_addons.update(new_pa)
            raw_pricings.update(new_raw)
    except Exception as e:
        with lock:
            state["error"] = f"catalogue : {e}"


def price_parts(plan, memory, storage):
    """Prix découpé en morceaux (mensuel TTC, installation HT, total 1er mois TTC)."""
    with lock:
        base = plan_prices.get(plan)
        if not base or base.get("month") is None:
            return None
        total = base["month"]
        setup = base.get("setup") or 0.0
        setup_known = base.get("setup") is not None
        missing = []
        for part in (memory, storage):
            a = addon_prices.get(f"{part}-{plan}")
            if a is None or a.get("month") is None:
                missing.append(part)
                continue
            total += a["month"]
            setup += a.get("setup") or 0.0
    complete = not missing
    parts = {
        "month": f"{'' if complete else 'dès '}{eur(round(total * TVA, 2))} TTC/mois",
        "setup": "",
        "first": "",
        "tip": "",
    }
    if setup > 0:
        parts["setup"] = f"installation {eur(setup)} HT"
        parts["first"] = f"1er mois : {eur(round((total + setup) * TVA, 2))} TTC"
    elif setup_known and complete:
        parts["setup"] = "installation offerte"
    else:
        parts["setup"] = "installation : non trouvée"
    if missing:
        parts["tip"] = "Prix d'option introuvable dans le catalogue : " + ", ".join(missing)
    return parts


def fmt_price(plan, memory, storage):
    """Texte simple (utilisé pour Discord). Retourne (texte, infobulle)."""
    p = price_parts(plan, memory, storage)
    if not p:
        return "", ""
    text = " · ".join(x for x in (p["month"], p["setup"], p["first"]) if x)
    return text, p["tip"]
        
def poll_loop():
    while True:
        refresh_catalog()
        try:
            r = requests.get(API, timeout=15)
            r.raise_for_status()
            data = r.json()
            check(data)
            with lock:
                state.update(data=data, last=datetime.now().strftime("%H:%M:%S"), error=None)
        except Exception as e:
            with lock:
                state["error"] = f"{datetime.now().strftime('%H:%M:%S')} - {e}"
        with lock:
            interval = max(10, int(conf.get("interval", 30)))
        time.sleep(interval)


_started = False


def start_poller():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=poll_loop, daemon=True).start()


start_poller()


# ---------- authentification ----------
def requires_auth(f):
    @wraps(f)
    def wrapper(*a, **kw):
        auth = request.authorization
        ok = (
            auth
            and hmac.compare_digest(auth.username or "", UI_USER)
            and hmac.compare_digest(auth.password or "", UI_PASS)
        )
        if not ok:
            return Response("Authentification requise", 401,
                            {"WWW-Authenticate": 'Basic realm="Kimsufi watcher"'})
        return f(*a, **kw)
    return wrapper


# ---------- routes ----------
@app.get("/")
@requires_auth
def index():
    return Response(PAGE, mimetype="text/html")


@app.get("/api/state")
@requires_auth
def api_state():
    with lock:
        rules = list(conf["rules"])
        configs = []
        for s in state["data"]:
            if any(r.get("plan") == s.get("planCode") for r in rules):
                ok = orderable(s["planCode"], s.get("memory"), s.get("storage"))
                price_h, price_tip = fmt_price(s["planCode"], s.get("memory"), s.get("storage")) if ok else ("", "")
                price_p = price_parts(s["planCode"], s.get("memory"), s.get("storage")) if ok else None
                configs.append({
                    "price_h": price_h, "price_tip": price_tip, "price_p": price_p,
                    "plan": s["planCode"], "name": names.get(s["planCode"], s["planCode"]),
                    "memory": s.get("memory"), "storage": s.get("storage"),
                    "memory_h": fmt_memory(s.get("memory")),
                    "storage_h": fmt_storage(s.get("storage")),
                    "datacenters": [
                        {**d, "label": dc_name(d["datacenter"]),
                         "avail_h": fmt_avail(d["availability"])}
                        for d in s.get("datacenters", [])
                    ],
                    "orderable": ok, "watched": ok and any(matches(r, s) for r in rules),
                })
        plans = [{"code": c, "name": names.get(c, c)}
                 for c in sorted({s["planCode"] for s in state["data"]})]
        return jsonify({
            "last": state["last"], "error": state["error"],
            "configs": configs, "plans": plans,
            "history": [
                {**h, "mem_h": fmt_memory(h.get("memory")), "sto_h": fmt_storage(h.get("storage")),
                 "dc_h": dc_name(h.get("dc", "")), "avail_h": fmt_avail(h.get("availability", ""))}
                for h in history[:50]
            ],
            "conf": {
                "interval": conf["interval"], "mention": conf["mention"],
                "webhook_set": bool(conf["webhook"]), "rules": rules,
            },
        })


@app.post("/api/config")
@requires_auth
def api_config():
    body = request.get_json(force=True, silent=True) or {}
    rules = []
    for r in body.get("rules", []):
        plan = str(r.get("plan", "")).strip()
        if plan:
            rules.append({
                "plan": plan,
                "memory": str(r.get("memory", "")).strip(),
                "storage": str(r.get("storage", "")).strip(),
                "enabled": bool(r.get("enabled", True)),
            })
    try:
        interval = max(10, min(3600, int(body.get("interval", 30))))
    except (TypeError, ValueError):
        interval = 30
    with lock:
        conf["rules"] = rules
        conf["interval"] = interval
        conf["mention"] = bool(body.get("mention", True))
        wh = str(body.get("webhook", "")).strip()
        if wh:
            conf["webhook"] = wh  # n'écrase que si une nouvelle valeur est fournie
        save_json(CONF_FILE, conf)
    return jsonify(ok=True)


@app.post("/api/test")
@requires_auth
def api_test():
    ok, info = send_discord("Test : le Kimsufi watcher fonctionne.")
    return jsonify(ok=ok, info=info)


@app.post("/api/clear_history")
@requires_auth
def api_clear():
    with lock:
        history.clear()
        save_json(HIST_FILE, history)
    return jsonify(ok=True)
@app.get("/api/debug/<plan>")
@requires_auth
def api_debug(plan):
    with lock:
        return jsonify({
            "plan": plan,
            "computed": plan_prices.get(plan),
            "pricings": raw_pricings.get(plan),
            "addons": {
                c: {"computed": addon_prices.get(c), "pricings": raw_pricings.get(c)}
                for c in sorted(plan_addons.get(plan, []))
            },
        })

PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kimsufi watcher</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--txt:#1b2330;--mut:#6b7686;--bd:#dde2ea;--ok:#1a8f4c;--okbg:#dff5e8;--off:#8a93a1;--offbg:#eceff3;--acc:#1f6feb;--unk:#9a6700;--unkbg:#fdf1d6}
@media (prefers-color-scheme:dark){:root{--bg:#14181f;--card:#1c222c;--txt:#e6e9ef;--mut:#98a2b3;--bd:#2c3441;--ok:#5fd38d;--okbg:#17382a;--off:#7d8794;--offbg:#252c37;--acc:#5b9dff;--unk:#e3b341;--unkbg:#3b3017}}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--txt)}
main{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:0 0 10px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px;margin:12px 0}
.pm{color:#e8a317}.pf{color:var(--txt)}.mut{color:var(--mut)}.price{color:var(--txt)}.cfg.na{opacity:.55}.bad{color:#d1343c}
.cfg{padding:8px 0;border-top:1px solid var(--bd)}.cfg:first-of-type{border-top:0}
.cfg.w{border-left:3px solid var(--acc);padding-left:10px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{padding:2px 8px;border-radius:99px;font-size:12px;background:var(--offbg);color:var(--off)}
.chip.ok{background:var(--okbg);color:var(--ok);font-weight:600}.chip.unk{background:var(--unkbg);color:var(--unk)}
table{width:100%;border-collapse:collapse}td,th{padding:4px 6px;text-align:left;vertical-align:middle}
th{font-size:12px;color:var(--mut);font-weight:500}
input[type=text],input[type=number],input[type=password]{width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:6px;background:var(--bg);color:var(--txt)}
button{padding:6px 12px;border:1px solid var(--bd);border-radius:6px;background:var(--card);color:var(--txt);cursor:pointer}
button.p{background:var(--acc);border-color:var(--acc);color:#fff}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:8px 0}.row>div{flex:1;min-width:150px}
label{font-size:12px;color:var(--mut);display:block;margin-bottom:2px}
.scroll{overflow-x:auto}
</style></head><body><main>
<h1>Kimsufi watcher</h1>
<div class="mut" id="status">Chargement…</div>

<div class="card"><h2>Disponibilités en direct</h2><div id="configs" class="mut">…</div></div>

<div class="card"><h2>Règles de surveillance</h2>
<p class="mut" style="margin-top:0">Alerte si le planCode correspond et si la RAM et le stockage <b>contiennent</b> le texte indiqué (vide = tout). Ex. : <code>ram-32g</code> et <code>x4000</code>. Ces filtres portent sur les noms techniques, visibles en survolant une config.</p>
<div class="scroll"><table><thead><tr><th>Actif</th><th>planCode</th><th>RAM contient</th><th>Stockage contient</th><th></th></tr></thead><tbody id="rules"></tbody></table></div>
<datalist id="plans"></datalist>
<div class="row"><button onclick="addRule()">+ Ajouter une règle</button></div></div>

<div class="card"><h2>Réglages</h2>
<div class="row">
<div style="flex:3"><label>Webhook Discord <span id="whstate" class="mut"></span></label><input type="password" id="webhook" placeholder="Laisser vide pour conserver l'actuel" autocomplete="off"></div>
<div><label>Intervalle (secondes, min 10)</label><input type="number" id="interval" min="10"></div>
</div>
<div class="row"><label style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="mention"> Mentionner @everyone</label></div>
<div class="row"><button class="p" onclick="save()">Enregistrer</button><button onclick="testHook()">Envoyer un message de test</button><span id="msg" class="mut"></span></div></div>

<div class="card"><h2>Historique des alertes <button style="float:right" onclick="clearHist()">Vider</button></h2><div id="hist" class="mut">Aucune alerte</div></div>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let rules=[],first=true;

async function load(){
  try{
    const r=await fetch('/api/state');const s=await r.json();
    $('#status').innerHTML='Dernière vérification : '+esc(s.last||'—')+(s.error?' · <span class="bad">Erreur : '+esc(s.error)+'</span>':'');
    $('#plans').innerHTML=s.plans.map(p=>'<option value="'+esc(p.code)+'" label="'+esc(p.name)+'">').join('');
    $('#configs').innerHTML=s.configs.length?s.configs.map(c=>
      '<div class="cfg'+(c.watched?' w':'')+(c.orderable?'':' na')+'" title="'+esc(c.plan+' · '+c.memory+' · '+c.storage)+'"><b>'+esc(c.name)+'</b> <span class="mut">'+esc(c.memory_h)+' · '+esc(c.storage_h)+(c.price_p?' · <span title="'+esc(c.price_p.tip)+'"><b class="pm">'+esc(c.price_p.month)+'</b> · '+esc(c.price_p.setup)+(c.price_p.first?' · <b class="pf">'+esc(c.price_p.first)+'</b>':'')+'</span>':'')+(c.watched?' · surveillé':'')+(c.orderable?'':' · non proposé à la commande')+'</span><div class="chips">'+
      c.datacenters.map(d=>'<span class="chip'+chipCls(d,c)+'" title="'+esc(d.datacenter)+'">'+esc(d.label)+(chipCls(d,c)?' · '+esc(d.avail_h):'')+'</span>').join('')+'</div></div>').join('')
      :'Aucune config à afficher (ajoutez une règle ou attendez la première vérification).';
    $('#hist').innerHTML=s.history.length?'<table><tbody>'+s.history.map(h=>'<tr><td class="mut">'+esc(h.time)+'</td><td>'+esc(h.name||h.plan)+'</td><td>'+esc(h.mem_h)+' · '+esc(h.sto_h)+'</td><td>'+esc(h.dc_h)+' · '+esc(h.avail_h)+'</td></tr>').join('')+'</tbody></table>':'Aucune alerte';
    if(first){first=false;rules=s.conf.rules;$('#interval').value=s.conf.interval;$('#mention').checked=s.conf.mention;
      $('#whstate').textContent=s.conf.webhook_set?'(configuré)':'(non configuré)';drawRules();}
  }catch(e){$('#status').innerHTML='<span class="bad">Connexion impossible : '+esc(e)+'</span>';}
}
function chipCls(d,c){
  if(!c.orderable||d.availability==='unavailable')return'';
  return d.availability==='unknown'?' unk':' ok';
}
function drawRules(){
  $('#rules').innerHTML=rules.map((r,i)=>'<tr><td><input type="checkbox" '+(r.enabled?'checked':'')+' onchange="rules['+i+'].enabled=this.checked"></td>'+
  '<td><input type="text" list="plans" value="'+esc(r.plan)+'" oninput="rules['+i+'].plan=this.value"></td>'+
  '<td><input type="text" value="'+esc(r.memory)+'" oninput="rules['+i+'].memory=this.value"></td>'+
  '<td><input type="text" value="'+esc(r.storage)+'" oninput="rules['+i+'].storage=this.value"></td>'+
  '<td><button onclick="rules.splice('+i+',1);drawRules()">Supprimer</button></td></tr>').join('');
}
function addRule(){rules.push({plan:'',memory:'',storage:'',enabled:true});drawRules();}
async function save(){
  const body={rules,interval:+$('#interval').value,mention:$('#mention').checked,webhook:$('#webhook').value};
  const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  $('#msg').textContent=r.ok?'Enregistré.':'Erreur à l\'enregistrement';
  if(r.ok&&body.webhook){$('#webhook').value='';$('#whstate').textContent='(configuré)';}
  load();
}
async function testHook(){
  $('#msg').textContent='Envoi…';
  const r=await fetch('/api/test',{method:'POST'});const j=await r.json();
  $('#msg').textContent=j.ok?'Message envoyé, vérifiez Discord.':'Échec : '+j.info;
}
async function clearHist(){await fetch('/api/clear_history',{method:'POST'});load();}
load();setInterval(load,5000);
</script></body></html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)