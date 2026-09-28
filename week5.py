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
    dict(id="q1", sec=0, kind="num", pts=100, ans=swap(1000, 2.5e6, 50_000)["eth_out"], unit="ETH",
         prompt="Standard pool. You buy ETH with 50,000 USDC. How much ETH do you receive?",
         key_txt="19.61 ETH",
         why="k = 1,000 × 2,500,000 = 2.5 billion. The pool now holds 2,550,000 USDC, so ETH left = 2.5B ÷ 2.55M = 980.39. You receive 1,000 − 980.39 = 19.61 ETH."),
    dict(id="q2", sec=0, kind="num", pts=100, ans=2.0, pct=True, unit="%",
         prompt="Same trade. What is your slippage, in %?",
         key_txt="2.0%",
         why="Your average price is 50,000 ÷ 19.61 = $2,550 against $2,500 before the trade. 2,550 ÷ 2,500 − 1 = 2.0%. Shortcut: 50,000 ÷ 2,500,000 = 2%."),
    dict(id="q3", sec=0, kind="mcq", pts=100, ans=1,
         options=["Stays about the same", "Roughly doubles, to about 4%", "Roughly quadruples", "Roughly halves"],
         prompt="Now double the trade to 100,000 USDC in the same pool. Your slippage...",
         why="Slippage ≈ your trade ÷ the USDC in the pool. Double the trade, double the slippage: 100,000 ÷ 2,500,000 = 4%."),
    dict(id="q4", sec=1, kind="num", pts=100, ans=0.4, pct=True, unit="%",
         prompt="Switch to the deep pool. You buy ETH with 100,000 USDC. What is your slippage, in %?",
         key_txt="0.4%",
         why="100,000 ÷ 25,000,000 = 0.4%. Same trade as Monday's example, ten times the liquidity, one tenth the slippage."),
    dict(id="q5", sec=1, kind="num", pts=75, ans=swap(1000, 2.5e6, 100_000)["p1"], unit="USDC",
         prompt="Back in the standard pool, after a 100,000 USDC buy: what price (USDC per ETH) does the pool quote to the next trader?",
         key_txt="$2,704",
         why="The pool holds 2,600,000 USDC and 961.54 ETH. 2,600,000 ÷ 961.54 = $2,704. That is 8.2% above where it started: your price impact."),
    dict(id="q6", sec=1, kind="mcq", pts=75, ans=0,
         options=["Your trade is a much smaller fraction of what is in the pool",
                  "Deep pools charge lower fees",
                  "Arbitrage traders pay part of your bill",
                  "The price comes from Coinbase instead of the formula"],
         prompt="Why does the deep pool give you a better price?",
         why="The formula is identical. Your 100,000 USDC is 4% of the standard pool's USDC but only 0.4% of the deep pool's, so it moves the ratio ten times less."),
    dict(id="q7", sec=2, kind="num", pts=75, ans=abs(lp(1, 2)["il_pct"]), pct=True, absval=True, unit="%",
         prompt="You LP and then ETH doubles (price change = 2). What is your impermanent loss, in %?",
         key_txt="5.7%",
         why="Held: $7,500 per $5,000 deposited. In the pool: $7,071. 7,071 ÷ 7,500 − 1 = −5.7%. The deposit size does not matter; only how far the price moved."),
    dict(id="q8", sec=2, kind="num", pts=75, ans=fees(10_000, 20e6, 4e6, 0.30, 60)["total"], unit="USD",
         prompt="You LP $10,000 into a pool holding $20,000,000 that does $4,000,000 of trading a day at a 0.30% fee. Fees earned over 60 days, in dollars?",
         key_txt="$360",
         why="You own 10,000 ÷ 20,000,000 = 0.05% of the pool. The pool earns 4,000,000 × 0.30% = $12,000 a day, so you get $6 a day. × 60 days = $360."),
    dict(id="q9", sec=2, kind="num", pts=75, ans=lp(10_000, 2)["il_usd"], absval=True, unit="USD",
         prompt="Same $10,000 position. ETH doubles over those 60 days. Your impermanent loss, in dollars?",
         key_txt="$858",
         why="Held: $5,000 of ETH becomes $10,000, plus $5,000 USDC = $15,000. In the pool: $10,000 × √2 = $14,142. Difference: $858."),
    dict(id="q10", sec=2, kind="mcq", pts=75, ans=1,
         options=["Ahead: fees beat the loss", "Behind by about $500", "Exactly even", "Behind by about $860"],
         prompt="So after those 60 days, compared with just holding the two tokens, the LP is...",
         why="+$360 in fees − $858 of impermanent loss = about −$498. Fee income was outrun by impermanent loss, exactly like Monday's example."),
    dict(id="q11", sec=3, kind="text", pts=150,
         prompt="In one sentence: when is being an LP a good deal, and when is it not?",
         key_txt="(written)",
         why="Model answer: when the fees you earn over the period are bigger than the impermanent loss, which means a lot of trading volume relative to the pool's size and a price that does not wander far from where you deposited. A big trending move makes it a bad deal."),
]
QBY = {q["id"]: q for q in Q}
SECTIONS = ["The Swap", "The Depth", "The LP", "One Line"]


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
    if err <= 0.015:
        return q["pts"], "full"
    if err <= 0.03:
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
    """**Key idea.** An AMM pool holds two tokens and follows one rule: ETH in the pool × USDC in the pool = k, and every trade must leave k where it was. The pool's price is just USDC ÷ ETH.

**Monday's example.** Pool: 1,000 ETH and 2,500,000 USDC, so ETH costs $2,500. Put in 100,000 USDC: the pool now has 2,600,000 USDC, so ETH left = 2,500,000,000 ÷ 2,600,000 = 961.54. You get 38.46 ETH at an average of $2,600. Slippage 4.0%, price impact 8.2%.

**Your turn.** Set the calculator to the numbers in each question and read the answer off it.""",
    """**Key idea.** Your slippage is roughly your trade ÷ the USDC already sitting in the pool. Ten times the liquidity means about one tenth the slippage. That is the AMM's version of the bid-ask spread.

**Your turn.** Use the pool switch on the calculator.""",
    """**Key idea.** LPs earn a share of every trade's fee. But when ETH's price moves, arbitrage traders rebalance the pool against them. Impermanent loss = how much worse you did in the pool than if you had just held the two tokens.

**Monday's example.** $5,000 in, ETH doubles. Just held: $7,500. In the pool: $7,071. Impermanent loss: $429 (5.7%). Fees in a $5M pool doing $1M a day at 0.30% for 90 days: $270. Net: $159 behind just holding.

**Your turn.** The calculator starts on Monday's numbers. Change them to match each question.""",
]


# ------------------------------------------------------------------ student view
def student_view():
    email = st.session_state.get("email")
    if not email:
        banner("DeFi Primitives · self-paced · 1,000 points")
        st.markdown("Four short parts. Each one has a key idea, a calculator, and a few checks. "
                    "Once you check a part it locks and shows you the reasoning.")
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
        for s_i in range(4):
            with st.expander(f"Part {s_i + 1} · {SECTIONS[s_i]}"):
                show_results(d, s_i)
        return

    st.progress(sec / 4, text=f"Part {sec + 1} of 4 · {SECTIONS[sec]}")
    qs = [q for q in Q if q["sec"] == sec]
    answered = all(q["id"] in d["answers"] for q in qs)

    if sec < 3:
        st.markdown(esc(LESSONS[sec]))
        if sec in (0, 1):
            swap_calculator(f"s{sec}", default_pool=0)
        else:
            lp_calculator("s2")

    if answered:
        show_results(d, sec)
        if st.button("Continue →" if sec < 3 else "Finish", type="primary", key=f"cont{sec}"):
            d["section"] = sec + 1
            if sec == 3:
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
        if sec == 3 and len(raw["q11"].strip()) < 15:
            st.error("Write a full sentence (at least 15 characters).")
            return
        for q in qs:
            pts, status = grade(q, raw[q["id"]])
            d["answers"][q["id"]] = dict(given=raw[q["id"]], pts=pts, status=status)
        if sec == 3:
            d["line"] = raw["q11"].strip()
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
                       "Part": min(r["section"] + 1, 4), "Done": "✓" if r["complete"] else ""}
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
                    min(r["section"] + 1, 4), r.get("line", "")]
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
