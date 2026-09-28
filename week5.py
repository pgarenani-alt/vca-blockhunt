"""VCA Week 5 · Pool Party.

In-class, self-paced build for DeFi Primitives (Mon 28 Sep 2026).
Students run an x*y=k calculator and an LP calculator, answer checks that lock per
section, and write one line. Presenter view: QR, live counts, leaderboard,
per-question accuracy, one-liners, CSV export on the 60-100 scale.

Only dependency: streamlit. Storage: local SQLite (ephemeral on Streamlit Cloud),
so download the CSV before leaving the room.

Presenter view:  <app-url>/?p=present&k=<PRESENTER_KEY>   (default key: vca5)
Optional secrets: PRESENTER_KEY, APP_URL
"""

import csv
import io
import json
import math
import sqlite3
import sys
import threading
import time
import types
from urllib.parse import quote

import streamlit as st

st.set_page_config(page_title="VCA Week 5 · Pool Party", page_icon="🌊", layout="centered")


# ------------------------------------------------------------------ config
def secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


PRESENTER_KEY = str(secret("PRESENTER_KEY", "vca5"))
APP_URL = str(secret("APP_URL", "") or "")
DB_PATH = "vca_week5.db"
TOTAL = 1000

# Pools used in the activity (fees ignored in the swap math, as in the lecture)
POOLS = {
    "Standard pool: 1,000 ETH + 2,500,000 USDC": (1000.0, 2_500_000.0),
    "Deep pool: 10,000 ETH + 25,000,000 USDC": (10_000.0, 25_000_000.0),
}


# ------------------------------------------------------------------ math
def swap(x, y, usdc_in):
    """Buy ETH with USDC against x*y=k. Returns dict of results."""
    k = x * y
    y2 = y + usdc_in
    x2 = k / y2
    eth_out = x - x2
    p0 = y / x
    avg = usdc_in / eth_out if eth_out > 0 else p0
    p1 = y2 / x2
    return dict(k=k, y2=y2, x2=x2, eth_out=eth_out, p0=p0, avg=avg, p1=p1,
                slip=(avg / p0 - 1) * 100, impact=(p1 / p0 - 1) * 100)


def lp(deposit, r):
    held = deposit / 2 * r + deposit / 2
    pool = deposit * math.sqrt(r)
    return dict(held=held, pool=pool, il_usd=held - pool, il_pct=(pool / held - 1) * 100)


def fees(deposit, tvl, vol, fee_pct, days):
    share = deposit / tvl if tvl > 0 else 0
    per_day = vol * fee_pct / 100 * share
    return dict(share=share * 100, per_day=per_day, total=per_day * days)


# ------------------------------------------------------------------ questions
Q = [
    # ---- Part 1 · The Swap
    dict(id="q1", sec=0, kind="num", pts=200, ans=swap(1000, 2.5e6, 50_000)["eth_out"], unit="ETH",
         prompt="Type 50,000 into the calculator. How much ETH do you get?",
         hint="Read the box that says \"ETH you receive\".",
         key_txt="19.61 ETH",
         why="19.61 ETH, not 50,000 ÷ 2,500 = 20. Your own trade pushed the price up as you bought."),
    dict(id="q2", sec=0, kind="num", pts=150, ans=2.0, pct=True, unit="%",
         prompt="Same trade. What slippage does it show?",
         hint="Read the box that says \"Slippage\". Type it like 2 or 2%.",
         key_txt="2%",
         why="2%. You paid about $2,550 per ETH instead of $2,500 because your trade moved the price."),
    dict(id="q3", sec=0, kind="num", pts=150, ans=0.2, pct=True, unit="%",
         prompt="Now click \"Deep pool\" and keep 50,000. What slippage does it show now?",
         hint="Same \"Slippage\" box.",
         key_txt="0.2%",
         why="0.2%, ten times less. A pool 10x bigger barely notices your trade."),
    # ---- Part 2 · The LP
    dict(id="q4", sec=1, kind="num", pts=200, ans=abs(lp(1, 2)["il_pct"]), pct=True, absval=True, unit="%",
         prompt="Set Price change to 2 (ETH doubles). What % impermanent loss does it show?",
         hint="The small % under \"Impermanent loss\". The minus sign is optional.",
         key_txt="5.7%",
         why="5.7%. If ETH doubles, being in the pool leaves you 5.7% behind just holding."),
    dict(id="q5", sec=1, kind="mcq", pts=150, ans=0,
         options=["Lots of trading, and a price that barely moves",
                  "Little trading, and a price that swings a lot"],
         prompt="Which pool is the better deal for an LP?",
         hint="More trading = more fees. Bigger price moves = more impermanent loss.",
         why="Lots of trading brings fees, and a calm price keeps impermanent loss small."),
    dict(id="q6", sec=1, kind="text", pts=150,
         prompt="In one sentence: what is slippage OR impermanent loss?",
         hint="Your own words. Any honest sentence gets full credit.",
         key_txt="(written)",
         why="Example: slippage is paying a worse price because your own trade moves the pool's price."),
]
QBY = {q["id"]: q for q in Q}
SECTIONS = ["The Swap", "The LP"]
NS = len(SECTIONS)


def esc(s):
    """Escape Streamlit markdown specials: $ renders LaTeX, ~ strikethrough."""
    return str(s).replace("$", "\\$").replace("~", "\\~")


def parse_num(raw):
    if raw is None:
        return None
    t = str(raw).strip().lower().replace("−", "-")
    for junk in ("$", ",", "usdc", "usd", "eth", "days", "day", "%", " ", "dollars"):
        t = t.replace(junk, "")
    if t in ("", "-", ".", "+"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def grade(q, raw):
    """Return (points, status) where status in full/half/wrong/invalid."""
    if q["kind"] == "mcq":
        return (q["pts"], "full") if raw == q["ans"] else (0, "wrong")
    if q["kind"] == "text":
        return (q["pts"], "full") if raw and len(str(raw).strip()) >= 15 else (0, "wrong")
    v = parse_num(raw)
    if v is None:
        return 0, "invalid"
    cands = [v]
    if q.get("pct") and abs(v) < 1:
        cands.append(v * 100)
    if q.get("absval"):
        cands = [abs(c) for c in cands]
    ans = q["ans"]
    err = min(abs(c - ans) / abs(ans) for c in cands)
    if err <= 0.03:
        return q["pts"], "full"
    if err <= 0.08:
        return q["pts"] // 2, "half"
    return 0, "wrong"


# ------------------------------------------------------------------ storage
# Shared connection + lock parked in sys.modules: Streamlit re-executes this
# script on every interaction, which would reset ordinary module globals.
_SH = "_vca_week5_shared"
if _SH not in sys.modules:
    _m = types.ModuleType(_SH)
    _m.lock = threading.RLock()
    _m.conn = None
    sys.modules[_SH] = _m
SH = sys.modules[_SH]


def db():
    if SH.conn is None:
        with SH.lock:
            if SH.conn is None:
                c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("""CREATE TABLE IF NOT EXISTS students(
                    email TEXT PRIMARY KEY, name TEXT, answers TEXT, score INTEGER,
                    section INTEGER, complete INTEGER, line TEXT, created REAL, updated REAL)""")
                c.commit()
                SH.conn = c
    return SH.conn


COLS = ["email", "name", "answers", "score", "section", "complete", "line", "created", "updated"]


def load(email):
    with SH.lock:
        row = db().execute("SELECT * FROM students WHERE email=?", (email,)).fetchone()
    if not row:
        return None
    d = dict(zip(COLS, row))
    d["answers"] = json.loads(d["answers"] or "{}")
    return d


def save(d):
    d["updated"] = time.time()
    d["score"] = sum(a["pts"] for a in d["answers"].values())
    with SH.lock:
        c = db()
        c.execute("""INSERT INTO students(email,name,answers,score,section,complete,line,created,updated)
                     VALUES(?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(email) DO UPDATE SET name=excluded.name, answers=excluded.answers,
                     score=excluded.score, section=excluded.section, complete=excluded.complete,
                     line=excluded.line, updated=excluded.updated""",
                  (d["email"], d["name"], json.dumps(d["answers"]), d["score"], d["section"],
                   d["complete"], d.get("line") or "", d["created"], d["updated"]))
        c.commit()


def everyone():
    with SH.lock:
        rows = db().execute("SELECT * FROM students ORDER BY score DESC, updated ASC").fetchall()
    out = []
    for r in rows:
        d = dict(zip(COLS, r))
        d["answers"] = json.loads(d["answers"] or "{}")
        out.append(d)
    return out


def clear_all():
    with SH.lock:
        db().execute("DELETE FROM students")
        db().commit()


def participation(score):
    return round(60 + 40 * score / TOTAL, 1)


# ------------------------------------------------------------------ ui bits
def banner(sub):
    st.markdown(
        f"""<div style="background:#0A2C5E;border-bottom:5px solid #2E86DE;padding:14px 18px;border-radius:6px;margin-bottom:10px">
        <div style="color:#AFC6E4;font-size:11px;font-weight:700;letter-spacing:1.2px">VILLANOVA CRYPTO ACADEMY · WEEK 5</div>
        <div style="color:white;font-size:26px;font-weight:800;line-height:1.2">Pool Party</div>
        <div style="color:#C9DCF2;font-size:14px">{sub}</div></div>""",
        unsafe_allow_html=True)


def swap_calculator(tag, default_pool=0):
    with st.container(border=True):
        st.markdown("**x × y = k calculator** · buy ETH with USDC (the 0.30% fee is left out, like Monday)")
        names = list(POOLS)
        pool = st.radio("Pool", names, index=default_pool, key=f"pool_{tag}")
        usdc = st.number_input("USDC you put in", min_value=0.0, max_value=1e9, value=10_000.0,
                               step=10_000.0, format="%.0f", key=f"usdc_{tag}")
        x, y = POOLS[pool]
        r = swap(x, y, usdc)
        c1, c2, c3 = st.columns(3)
        c1.metric("ETH you receive", f"{r['eth_out']:,.2f}")
        c2.metric("Your average price", f"{r['avg']:,.2f} USDC")
        c3.metric("Pool price after", f"{r['p1']:,.2f} USDC")
        c4, c5, c6 = st.columns(3)
        c4.metric("Pool price before", f"{r['p0']:,.2f} USDC")
        c5.metric("Slippage", f"{r['slip']:.2f}%")
        c6.metric("Price impact", f"{r['impact']:.2f}%")
        st.caption(esc(
            f"k = {x:,.0f} × {y:,.0f} = {r['k']:,.0f}. Pool USDC after = {r['y2']:,.0f}. "
            f"ETH left = k ÷ {r['y2']:,.0f} = {r['x2']:,.2f}. "
            "Slippage = average price ÷ price before − 1. Price impact = price after ÷ price before − 1."))


def lp_calculator(tag):
    with st.container(border=True):
        st.markdown("**LP calculator** · starts on Monday's numbers. Change them to match each question.")
        c1, c2 = st.columns(2)
        dep = c1.number_input("Your deposit (USD, half ETH and half USDC)", min_value=0.0, value=5_000.0,
                              step=1_000.0, format="%.0f", key=f"dep_{tag}")
        r = c2.number_input("Price change (new ETH price ÷ old). 2 = doubled, 0.5 = halved", min_value=0.01,
                            max_value=100.0, value=1.0, step=0.25, format="%.2f", key=f"r_{tag}")
        L = lp(dep, r)
        m1, m2, m3 = st.columns(3)
        m1.metric("If you just held", f"{L['held']:,.2f} USD")
        m2.metric("In the pool", f"{L['pool']:,.2f} USD")
        m3.metric("Impermanent loss", f"{L['il_usd']:,.2f} USD", f"{L['il_pct']:.2f}%", delta_color="normal")
        st.markdown("**Fees**")
        f1, f2, f3, f4 = st.columns(4)
        tvl = f1.number_input("Pool size (USD)", min_value=1.0, value=5_000_000.0, step=1_000_000.0,
                              format="%.0f", key=f"tvl_{tag}")
        vol = f2.number_input("Trading a day (USD)", min_value=0.0, value=1_000_000.0, step=500_000.0,
                              format="%.0f", key=f"vol_{tag}")
        fee = f3.number_input("Fee (%)", min_value=0.0, max_value=5.0, value=0.30, step=0.05,
                              format="%.2f", key=f"fee_{tag}")
        days = f4.number_input("Days", min_value=0.0, value=90.0, step=10.0, format="%.0f", key=f"days_{tag}")
        F = fees(dep, tvl, vol, fee, days)
        n1, n2, n3 = st.columns(3)
        n1.metric("Your share of the pool", f"{F['share']:.4f}%")
        n2.metric("Your fees a day", f"{F['per_day']:,.2f} USD")
        n3.metric("Your fees, total", f"{F['total']:,.2f} USD")
        net = F["total"] - L["il_usd"]
        st.metric("Fees minus impermanent loss (versus just holding)", f"{net:,.2f} USD")


def show_results(d, sec):
    for q in [q for q in Q if q["sec"] == sec]:
        a = d["answers"].get(q["id"], {})
        mark = {"full": "✅", "half": "🟡 half credit", "wrong": "❌", "invalid": "❌ numbers only"}.get(a.get("status"), "❌")
        given = a.get("given", "")
        if q["kind"] == "mcq":
            given = q["options"][given] if isinstance(given, int) else "(none)"
            right = q["options"][q["ans"]]
        else:
            right = q["key_txt"]
        with st.container(border=True):
            st.markdown(f"{mark} **{esc(q['prompt'])}**")
            st.markdown(esc(f"Your answer: {given}  ·  Correct: {right}  ·  {a.get('pts', 0)}/{q['pts']} pts"))
            st.caption(esc(q["why"]))


LESSONS = [
    """When you buy from a pool, your own trade pushes the price up. The extra you pay is **slippage**. Type into the calculator and read the answers off it.""",
    """LPs earn a cut of every trade's fee, but when ETH's price moves they end up behind someone who just held. That gap is **impermanent loss**. Only change **Price change**.""",
]


# ------------------------------------------------------------------ student view
def student_view():
    email = st.session_state.get("email")
    if not email:
        banner("DeFi Primitives · self-paced · 1,000 points")
        st.markdown("Two short parts, about 5 minutes. Every answer comes straight off the calculator. "
                    "Once you check a part it locks and shows you the answer.")
        with st.form("login"):
            name = st.text_input("Your name (first and last)", key="name_in")
            em = st.text_input("Your Villanova email", key="email_in", placeholder="you@villanova.edu")
            go = st.form_submit_button("Start", type="primary")
        if go:
            em = (em or "").strip().lower()
            if not name.strip() or "@" not in em:
                st.error("Enter your name and your email.")
                return
            d = load(em)
            if d is None:
                d = dict(email=em, name=name.strip(), answers={}, score=0, section=0, complete=0,
                         line="", created=time.time(), updated=time.time())
                save(d)
            st.session_state["email"] = em
            st.rerun()
        return

    d = load(email)
    if d is None:
        st.session_state.pop("email", None)
        st.rerun()
        return
    sec = d["section"]
    banner(f"{esc(d['name'])} · {d['score']} of {TOTAL} points")

    if d["complete"]:
        st.success(f"Done. Score: {d['score']} / {TOTAL}  ·  In-session grade: {participation(d['score'])}")
        st.markdown("Keep this screen open if an officer asks to see it. **Kahoot is next.**")
        for s_i in range(NS):
            with st.expander(f"Part {s_i + 1} · {SECTIONS[s_i]}"):
                show_results(d, s_i)
        return

    st.progress(sec / NS, text=f"Part {sec + 1} of {NS} · {SECTIONS[sec]}")
    qs = [q for q in Q if q["sec"] == sec]
    answered = all(q["id"] in d["answers"] for q in qs)

    st.markdown(esc(LESSONS[sec]))
    if sec == 0:
        swap_calculator("s0", default_pool=0)
    else:
        lp_calculator("s1")

    if answered:
        show_results(d, sec)
        if st.button("Continue →" if sec < NS - 1 else "Finish", type="primary", key=f"cont{sec}"):
            d["section"] = sec + 1
            if sec == NS - 1:
                d["complete"] = 1
            save(d)
            st.rerun()
        return

    with st.form(f"checks{sec}"):
        raw = {}
        for i, q in enumerate(qs):
            label = f"{i + 1}. {q['prompt']}"
            if q["kind"] == "num":
                raw[q["id"]] = st.text_input(esc(label), key=f"in_{q['id']}",
                                             help="Numbers only. For % you can type 2, 2% or 0.02.")
            elif q["kind"] == "mcq":
                raw[q["id"]] = st.radio(esc(label), list(range(len(q["options"]))), index=None,
                                        format_func=lambda j, q=q: q["options"][j], key=f"in_{q['id']}")
            else:
                raw[q["id"]] = st.text_area(esc(label), key=f"in_{q['id']}", max_chars=400)
            if q.get("hint"):
                st.caption("💡 " + esc(q["hint"]))
        sub = st.form_submit_button("Check my answers (locks this part)", type="primary")
    if sub:
        missing = [q for q in qs if raw[q["id"]] is None or (isinstance(raw[q["id"]], str) and not raw[q["id"]].strip())]
        if missing:
            st.error("Answer every question before checking. This part locks once you check it.")
            return
        bad = [q for q in qs if q["kind"] == "num" and parse_num(raw[q["id"]]) is None]
        if bad:
            st.error("Numbers only in the number boxes (you can include $, commas or %).")
            return
        txt = [q for q in qs if q["kind"] == "text"]
        if txt and len(raw[txt[0]["id"]].strip()) < 15:
            st.error("Write a full sentence (at least 15 characters).")
            return
        for q in qs:
            pts, status = grade(q, raw[q["id"]])
            d["answers"][q["id"]] = dict(given=raw[q["id"]], pts=pts, status=status)
        if txt:
            d["line"] = raw[txt[0]["id"]].strip()
        save(d)
        st.rerun()


# ------------------------------------------------------------------ presenter view
def presenter_view():
    banner("Presenter view")
    url = st.text_input("Student link (this app's address, without ?p=present)", value=APP_URL,
                        key="p_url", placeholder="https://vca-week5.streamlit.app")
    if url.strip():
        c1, c2 = st.columns([1, 1.3])
        try:
            c1.image("https://api.qrserver.com/v1/create-qr-code/?size=420x420&margin=12&data=" + quote(url.strip(), safe=""),
                     width=300)
        except Exception:
            c1.warning("QR service unreachable. Read the link out instead.")
        c2.markdown(f"<div style='font-size:28px;font-weight:800;color:#0A2C5E;word-break:break-all'>{url.strip()}</div>",
                    unsafe_allow_html=True)
        c2.caption("If the QR does not load, students can type the link.")

    def live():
        rows = everyone()
        started = len(rows)
        done = sum(1 for r in rows if r["complete"])
        avg = round(sum(r["score"] for r in rows) / started) if started else 0
        m1, m2, m3 = st.columns(3)
        m1.metric("Started", started)
        m2.metric("Completed", done)
        m3.metric("Average score", avg)
        st.markdown("**Leaderboard**")
        st.dataframe([{"#": i + 1, "Name": r["name"], "Score": r["score"],
                       "Part": min(r["section"] + 1, NS), "Done": "✓" if r["complete"] else ""}
                      for i, r in enumerate(rows[:15])], hide_index=True, width="stretch")
        st.markdown("**Per question** (re-teach anything under 60%)")
        stats = []
        for q in Q:
            got = [r["answers"][q["id"]] for r in rows if q["id"] in r["answers"]]
            if not got:
                continue
            full = sum(1 for a in got if a["status"] == "full")
            pct = round(100 * full / len(got))
            stats.append({"Q": q["id"], "Part": SECTIONS[q["sec"]], "Answered": len(got),
                          "% correct": pct, "Flag": "RE-TEACH" if pct < 60 else "",
                          "Question": q["prompt"][:70]})
        if stats:
            st.dataframe(stats, hide_index=True, width="stretch")
        lines = [r for r in rows if r.get("line")]
        if lines:
            st.markdown("**One-liners**")
            for r in lines[-12:]:
                st.markdown(f"- **{esc(r['name'])}:** {esc(r['line'])}")

    frag = getattr(st, "fragment", None)
    if frag is not None:
        try:
            frag(run_every=5)(live)()
        except TypeError:
            live()
    else:
        live()
        st.button("Refresh")

    st.divider()
    rows = everyone()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "name", "score", "participation_60_100", "complete", "part_reached", "line"]
               + [q["id"] for q in Q] + ["last_update"])
    for r in rows:
        w.writerow([r["email"], r["name"], r["score"], participation(r["score"]), r["complete"],
                    min(r["section"] + 1, NS), r.get("line", "")]
                   + [r["answers"].get(q["id"], {}).get("pts", "") for q in Q]
                   + [time.strftime("%Y-%m-%d %H:%M", time.localtime(r["updated"]))])
    st.download_button("Download CSV for the gradebook", buf.getvalue().encode("utf-8"),
                       file_name="VCA_Week5_PoolParty.csv", mime="text/csv", type="primary")
    st.caption("Storage is wiped whenever the app restarts. Download before you leave the room.")
    with st.expander("Answer key"):
        for q in Q:
            right = q["options"][q["ans"]] if q["kind"] == "mcq" else q["key_txt"]
            st.markdown(esc(f"**{q['id']}** ({q['pts']} pts) {q['prompt']}  →  **{right}**"))
    with st.expander("Danger zone"):
        ok = st.checkbox("I already downloaded the CSV")
        if st.button("Clear all responses", disabled=not ok):
            clear_all()
            st.rerun()


# ------------------------------------------------------------------ router
try:
    qp = st.query_params
    mode, key = qp.get("p", ""), qp.get("k", "")
except Exception:
    mode, key = "", ""

if mode == "present":
    if key == PRESENTER_KEY:
        presenter_view()
    else:
        banner("Presenter view")
        st.error("Wrong or missing presenter key. Add &k=<key> to the address.")
else:
    student_view()
    if st.session_state.get("email"):
        st.divider()
        if st.button("Not you? Switch student", key="switch"):
            st.session_state.pop("email", None)
            st.rerun()
