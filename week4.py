"""
VCA Week 4 · Ethereum, Solana & Tokenomics · interactive learning module

Student link:   https://<app>.streamlit.app
Presenter view: https://<app>.streamlit.app/?p=present&k=<PRESENTER_KEY>

Only dependency is streamlit. Everything else is standard library (Week 3 lesson:
every extra package is a failure mode). Figures are locked (21 Sep 2026) so grading
never depends on a live API during class.

Secrets (Streamlit app -> Settings -> Secrets), both optional:
    SHEET_URL     = "https://script.google.com/macros/s/.../exec"   # Apps Script collector
    PRESENTER_KEY = "pick-something"                               # default below if unset
"""
import csv
import html
import io
import json
import sqlite3
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import streamlit as st

# ─── Settings you might change ──────────────────────────────────────────────────
WEEK = 4
TITLE = "Ethereum, Solana & Tokenomics"
ET = timezone(timedelta(hours=-4), "ET")              # EDT, valid until 1 Nov
DUE = datetime(2026, 9, 27, 23, 59, tzinfo=ET)        # module closes after this
DEFAULT_KEY = "vca4"                                  # presenter key if no secret set
DB = "w4.db"


def secret(name, default=""):
    """st.secrets raises when no secrets file exists. Never let that kill the page."""
    try:
        v = st.secrets.get(name, default)
        return str(v).strip() if v is not None else default
    except Exception:
        return default


SHEET_URL = secret("SHEET_URL")
PRESENTER_KEY = secret("PRESENTER_KEY") or DEFAULT_KEY
SOL_RPC = secret("SOL_RPC")      # optional private RPC (e.g. from the Solana sponsor); public ones are the fallback

# ─── Locked reference figures · Mon 21 Sep 2026 ────────────────────────────────
ETH_PRICE = 2668.16          # CoinGecko
ETH_SUPPLY = 122.07e6        # CoinGecko / ultrasound.money (122,068,xxx)
ETH_MERGE_SUPPLY = 120.52e6  # 15 Sep 2022
ETH_STAKED = 43.2e6          # validatorqueue.com, 35.4% of supply
ETH_APR = 2.58               # validatorqueue.com consensus-layer APR, %
SOL_PRICE = 111.31           # CoinGecko
SOL_TOTAL = 634.45e6         # CoinGecko total supply
SOL_CIRC = 587.44e6          # CoinGecko circulating supply
SOL_INFL = 3.65              # % a year, 15 Sep 2026
SOL_STAKED_PCT = 69          # % of supply staked
BTC_ISSUANCE_PCT = 0.82      # Week 3 figure

# Derived (every number printed twice must reconcile)
GAS_USD = 21000 * 2 * 1e-9 * ETH_PRICE                   # 0.1121
SOL_FEE_USD = 5000 / 1e9 * SOL_PRICE                     # 0.000557
TX_PER_DOLLAR = 1 / SOL_FEE_USD                          # 1,796.8
ETH_NEW = ETH_STAKED * ETH_APR / 100                     # 1,114,560
ETH_NEW_PCT = ETH_NEW / ETH_SUPPLY * 100                 # 0.913
SOL_NEW = SOL_TOTAL * SOL_INFL / 100                     # 23.16M
SOL_NEW_USD_B = SOL_NEW * SOL_PRICE / 1e9                # 2.578
SOL_STAKE_YIELD = SOL_INFL / (SOL_STAKED_PCT / 100)      # 5.29
CAT_PRICE, CAT_CIRC, CAT_TOTAL, CAT_LOCKED, CAT_MONTHS, CAT_VOL = 2.0, 200e6, 1000e6, 480e6, 24, 5e6
CAT_FDV_M = CAT_TOTAL * CAT_PRICE / 1e6                  # 2,000
CAT_MONTHLY = CAT_LOCKED / CAT_MONTHS                    # 20M
CAT_MONTH_PCT = CAT_MONTHLY / CAT_CIRC * 100             # 10.0
CAT_DAYS = CAT_MONTHLY * CAT_PRICE / CAT_VOL             # 8.0


# ─── Number parsing and unit normalising ───────────────────────────────────────
def parse_num(raw):
    if raw is None:
        return None
    s = str(raw).strip().lower().replace(",", "").replace("$", "").replace("%", "")
    s = s.replace("usd", "").replace("sol", "").replace("eth", "").replace("days", "").strip()
    mult = 1.0
    for suf, m in (("billion", 1e9), ("million", 1e6), ("thousand", 1e3),
                   ("bn", 1e9), ("b", 1e9), ("mm", 1e6), ("m", 1e6), ("k", 1e3)):
        if s.endswith(suf):
            s, mult = s[: -len(suf)].strip(), m
            break
    try:
        return float(s) * mult
    except Exception:
        return None


def to_units_from_millions(v):      # 1.11 -> 1,110,000 ; 1110000 stays
    return v * 1e6 if v is not None and abs(v) < 1000 else v


def to_billions(v):                 # 2578000000 -> 2.578 ; 2578 (millions) -> 2.578
    if v is None:
        return v
    if abs(v) >= 1e6:
        return v / 1e9
    if abs(v) >= 100:
        return v / 1e3
    return v


def to_millions(v):                 # 2,000,000,000 -> 2000 ; 2 (billions) -> 2000
    if v is None:
        return v
    if abs(v) >= 1e6:
        return v / 1e6
    if abs(v) < 20:
        return v * 1000
    return v


def pct_from_fraction(limit):
    def f(v):
        return v * 100 if v is not None and abs(v) < limit else v
    return f


# ─── Content ───────────────────────────────────────────────────────────────────
SECTIONS = [
    dict(
        title="Ethereum: the world computer",
        mins=5,
        learn=f"""
Bitcoin is a ledger that records who owns bitcoin. **Ethereum is a ledger that can also run programs.**

- **Smart contract**: code that lives on the blockchain and moves money by fixed rules. Think of a vending machine: put in $2, get a soda. No cashier, and nobody can change the rules halfway through. Lending apps, exchanges and stablecoins are all smart contracts.
- **Gas**: every action costs a fee, because thousands of computers must re-run your code. **Fee = gas used × gas price.** Gas price is quoted in **gwei**, one-billionth of an ETH.
- **Proof of stake**: since 2022 ("the Merge") Ethereum has no miners. **Validators** lock up ETH as a security deposit, called **stake**. Do the job honestly and earn new ETH. Cheat and lose part of the deposit (**slashing**).
- **Layer 2s**: Ethereum itself is slow and expensive on purpose, because it prioritises being hard to shut down. Most everyday activity now runs on **Layer 2s** such as Base and Arbitrum, which bundle thousands of transactions and post a summary back to Ethereum. Carpooling for transactions.
""",
        talk="The one idea: Ethereum is programmable money, and everything in DeFi is a smart contract. "
             "Stake replaced electricity as the thing validators put at risk.",
    ),
    dict(
        title="Solana: one very fast chain",
        mins=4,
        learn="""
Solana makes the opposite bet. Instead of a careful base layer plus Layer 2s, it runs everything on **one chain built for speed**. That design is called **monolithic**; Ethereum's layered design is **modular**.

- A new block (a **slot**) every **0.4 seconds**. Ethereum: 12 seconds. Bitcoin: about 10 minutes.
- Fees are tiny: a flat **base fee of 5,000 lamports** per signature, where **1 SOL = 1,000,000,000 lamports**. Half the base fee is burned. Users can add a **priority fee** to jump the line, and that goes to the validator.
- Also proof of stake. About **69% of all SOL** is staked.
- **The trade-off**: that speed needs powerful, expensive validator hardware, so fewer people can run one. Solana also had several network outages between 2021 and 2024. Fast and cheap, in exchange for being harder to run.
""",
        talk="Monolithic vs modular is the core L1 design debate. Neither is 'better': each buys "
             "something (speed, or decentralisation) and pays for it somewhere else.",
    ),
    dict(
        title="Tokenomics: where new tokens come from",
        mins=6,
        learn=f"""
**Tokenomics** is the rulebook for a token's supply: how many exist, how many get created, and who receives them. Three levers:

1. **Issuance**: new tokens created to pay validators for securing the network. This is the network's **security budget**.
2. **Burn**: tokens destroyed forever, usually part of the fees users pay.
3. **Unlocks**: tokens that already exist but were locked for the team and early investors, released on a schedule (Section 5).

**Net supply change = issuance − burn.**

**ETH** has no max supply. New ETH goes to stakers, and the base fee of every transaction is burned. In 2022–23 the network was so busy that burn beat issuance and supply *shrank* ("ultrasound money"). Then the 2024 Dencun upgrade gave Layer 2s a cheap data lane called **blobs**. Fees collapsed, burn collapsed, and supply is growing again: **{ETH_MERGE_SUPPLY/1e6:.2f}M at the Merge → {ETH_SUPPLY/1e6:.2f}M today.**

**SOL** has no max supply either. Inflation started at 8% in 2021 and falls 15% every year toward a 1.5% floor. Today it is **{SOL_INFL}%**. In August 2026 stakers voted (67% yes) to make it fall **30%** a year instead (SIMD-0550). It is not live yet. Once it is, SOL reaches 1.5% in about 3 years instead of about 6.
""",
        card=True,
        talk=f"Ultrasound money broke: scaling success collapsed the burn. ETH now issues ~{ETH_NEW_PCT:.2f}% a year, "
             f"about Bitcoin's {BTC_ISSUANCE_PCT}%. Solana spends ~${SOL_NEW_USD_B:.2f}B a year on security; "
             "SIMD-0550 halves the path to the 1.5% floor.",
    ),
    dict(
        title="Who pays? Inflation, staking and dilution",
        mins=4,
        learn="""
New tokens are not free money. Picture a pizza being cut into more slices. If you get some of the new slices, your share of the pizza stays about the same. If you don't, your share shrinks.

- **Stakers** receive the new tokens, so they roughly keep their share of the network.
- **Non-stakers** get **diluted**: same number of tokens, smaller slice of the total.
- Only part of the supply is staked, so stakers split *all* the new tokens among themselves: **staking yield ≈ inflation ÷ share of supply staked** (ignoring fees and validator commissions).
- The number that matters is **real yield ≈ staking yield − inflation**. That is how much your *share* of the network actually grows.
- Equity parallel: stock-based compensation. New shares go to employees, and every other shareholder is diluted.
""",
        talk=f"Staking yield is mostly anti-dilution, not income. Real yield ≈ {SOL_STAKE_YIELD - SOL_INFL:.1f}% on SOL, "
             f"≈ {ETH_APR - ETH_NEW_PCT:.1f}% on ETH. Same logic as share-based comp.",
    ),
    dict(
        title="Unlocks: the supply you can't see yet",
        mins=5,
        learn="""
Week 2 recap: **market cap = price × circulating supply**. **FDV = price × total supply.** The gap is tokens that exist on paper but aren't trading yet.

Most new tokens launch with a **low float**: only a small slice circulates. The rest belongs to the team and early investors, locked on a **vesting schedule**:

- **Cliff**: nothing unlocks for a set period, often 12 months.
- **Linear vesting**: after the cliff, equal chunks unlock every month.

Insiders often paid a fraction of today's price, so when their tokens unlock, many sell. A quick test of unlock pressure: **dollar value unlocking ÷ daily trading volume.**

**Case: WILDCAT (CAT)**, a made-up token

| | |
|---|---|
| Price | $2.00 |
| Circulating supply | 200M |
| Total supply | 1,000M |
| Team + investors (locked) | 480M. Cliff just ended; unlocks evenly over the next 24 months |
| Daily trading volume | $5M |
""",
        talk="Low float / high FDV is the #1 retail trap. Unlock $ ÷ daily volume is the 10-second screen. "
             "This comes back in Week 7 comps.",
    ),
]

Q = [
    # Section 1 · Ethereum (180)
    dict(id="q1", sec=0, kind="mcq", pts=50,
         prompt="What is a smart contract?",
         options=["A legal agreement signed with a crypto wallet",
                  "Code on a blockchain that automatically executes rules and can hold and move money",
                  "A contract between a validator and the Ethereum Foundation",
                  "An agreement to buy ETH at a future price"],
         answer=1,
         why="It is a program, not a legal document. Once deployed, anyone can use it and nobody can quietly change the rules."),
    dict(id="q2", sec=0, kind="mcq", pts=50,
         prompt="What does an Ethereum validator put at risk to earn rewards?",
         options=["Electricity and mining machines",
                  "Its own ETH, locked up as a security deposit",
                  "A monthly fee paid to Ethereum",
                  "Nothing: validators are chosen by vote"],
         answer=1,
         why="Mining machines were Bitcoin (Week 3). Ethereum swapped energy for collateral: misbehave and your stake is slashed."),
    dict(id="q3", sec=0, kind="num", pts=80,
         prompt=f"Sending ETH uses **21,000 gas**. On a busy day the gas price is **2 gwei** "
                f"(1 gwei = 0.000000001 ETH). ETH is **${ETH_PRICE:,.2f}**. What does the transfer cost in US dollars?",
         hint="21,000 × 2 = gwei  →  × 0.000000001 = ETH  →  × price = $",
         target=GAS_USD, tol=0.008,
         show=f"${GAS_USD:.2f}  (21,000 × 2 = 42,000 gwei = 0.000042 ETH × ${ETH_PRICE:,.2f})",
         why="On a quiet day gas is closer to 0.1–0.5 gwei, so a transfer usually costs a few cents or less. On a Layer 2 it's a fraction of a cent."),

    # Section 2 · Solana (200)
    dict(id="q4", sec=1, kind="num", pts=60,
         prompt="How many Solana slots happen in the time Bitcoin produces one block (about **600 seconds**)?",
         hint="600 ÷ 0.4",
         target=1500, tol=15,
         show="1,500 slots  (600 ÷ 0.4)",
         why="Ethereum produces 50 blocks in the same time (600 ÷ 12). Speed is Solana's whole pitch."),
    dict(id="q5", sec=1, kind="mcq", pts=60,
         prompt="What is the main trade-off in Solana's design?",
         options=["Faster and cheaper, but validators need expensive hardware, so fewer people can run one",
                  "Slower, but more secure than Bitcoin",
                  "No fees, but no smart contracts",
                  "Faster, but every transaction must be approved by the Solana Foundation"],
         answer=0,
         why="Nothing is free in blockchain design. Solana buys speed with hardware requirements; Ethereum buys decentralisation with a slower base layer."),
    dict(id="q6", sec=1, kind="num", pts=80,
         prompt=f"The base fee is **5,000 lamports** and SOL is **${SOL_PRICE:,.2f}**. "
                f"About how many basic Solana transactions could you pay for with **$1**?",
         hint="5,000 ÷ 1,000,000,000 = SOL per tx  →  × price = $ per tx  →  $1 ÷ that",
         target=TX_PER_DOLLAR, tol=TX_PER_DOLLAR * 0.05,
         show=f"≈{TX_PER_DOLLAR:,.0f} transactions  (each costs 0.000005 SOL ≈ ${SOL_FEE_USD:.5f})",
         why="Blockspace on Solana is priced near zero. Great for users; it also means fees pay very little of the network's security bill (Section 4)."),

    # Section 3 · Supply (280)
    dict(id="q7", sec=2, kind="num", pts=70,
         prompt=f"**{ETH_STAKED/1e6:.1f}M ETH** is staked, earning about **{ETH_APR}%** a year, paid in newly issued ETH. "
                f"About how much new ETH is created per year?",
         hint="staked × yield  (you can type 1.11M or 1110000)",
         target=ETH_NEW, tol=ETH_NEW * 0.03, norm=to_units_from_millions,
         show=f"≈{ETH_NEW/1e6:.2f}M ETH  ({ETH_STAKED/1e6:.1f}M × {ETH_APR}%)",
         why="That is Ethereum's security budget, paid in new ETH."),
    dict(id="q8", sec=2, kind="num", pts=70,
         prompt=f"That new ETH as a **% of total supply** ({ETH_SUPPLY/1e6:.2f}M)?",
         hint="new ETH ÷ supply × 100",
         target=ETH_NEW_PCT, tol=0.03, norm=pct_from_fraction(0.05),
         show=f"≈{ETH_NEW_PCT:.2f}% a year",
         why=f"Bitcoin's is {BTC_ISSUANCE_PCT}% (Week 3). Right now ETH issues new supply at about Bitcoin's pace, and the burn only takes back a sliver of it."),
    dict(id="q9", sec=2, kind="num", pts=80,
         prompt=f"SOL inflation is **{SOL_INFL}%** a year, paid on the **total supply of {SOL_TOTAL/1e6:.2f}M SOL**. "
                f"At **${SOL_PRICE:,.2f}**, what is the dollar value of the new SOL created in a year, **in $ billions**?",
         hint=f"{SOL_TOTAL/1e6:.2f}M × {SOL_INFL}% = new SOL  →  × price  →  ÷ 1,000,000,000",
         target=SOL_NEW_USD_B, tol=SOL_NEW_USD_B * 0.03, norm=to_billions,
         show=f"≈${SOL_NEW_USD_B:.2f}B a year  ({SOL_NEW/1e6:.2f}M new SOL × ${SOL_PRICE:,.2f})",
         why="That is Solana's yearly security budget. Somebody pays for it: that's Section 4."),
    dict(id="q10", sec=2, kind="mcq", pts=60,
         prompt="Why did ETH's supply start growing again after 2024?",
         options=["Ethereum doubled the reward paid to validators",
                  "Layer 2s moved to cheap 'blob' space, fees collapsed, so far less ETH gets burned",
                  "The Merge was reversed and mining came back",
                  "The Ethereum Foundation minted new ETH to fund development"],
         answer=1,
         why="Issuance barely changed; the burn collapsed. Scaling success made ETH less scarce, a real tension in the ETH bull case."),

    # Section 4 · Dilution (140)
    dict(id="q11", sec=3, kind="num", pts=80,
         prompt=f"SOL inflation is **{SOL_INFL}%** and **{SOL_STAKED_PCT}%** of SOL is staked. "
                f"Roughly what yield do stakers earn, in %?",
         hint=f"{SOL_INFL} ÷ 0.{SOL_STAKED_PCT}",
         target=SOL_STAKE_YIELD, tol=0.15, norm=pct_from_fraction(0.5),
         show=f"≈{SOL_STAKE_YIELD:.1f}%  ({SOL_INFL} ÷ 0.{SOL_STAKED_PCT}). Real yield ≈ {SOL_STAKE_YIELD:.1f}% − {SOL_INFL}% ≈ {SOL_STAKE_YIELD - SOL_INFL:.1f}%",
         why="Most of the headline yield just offsets inflation. Your share of the network grows only by the real yield."),
    dict(id="q12", sec=3, kind="mcq", pts=60,
         prompt="Who ultimately pays for SOL's staking rewards?",
         options=["The Solana Foundation, out of its treasury",
                  "Users, through transaction fees",
                  "Holders who don't stake, through dilution",
                  "Nobody: the new tokens are free"],
         answer=2,
         why=f"About 650 SOL a day is burned in fees versus ~{SOL_NEW/365:,.0f} SOL a day issued. "
             f"The security budget is paid by diluting non-stakers. Same idea as Bitcoin in Week 3."),

    # Section 5 · Unlocks (200)
    dict(id="q13", sec=4, kind="num", pts=50,
         prompt="What is CAT's **FDV**, in **$ millions**?",
         hint="price × total supply",
         target=CAT_FDV_M, tol=20, norm=to_millions,
         show=f"${CAT_FDV_M:,.0f}M. Market cap is only ${CAT_CIRC*CAT_PRICE/1e6:,.0f}M, so 80% of the value is supply that isn't trading yet.",
         why="Always look at FDV next to market cap. A big gap means a lot of supply is still coming."),
    dict(id="q14", sec=4, kind="num", pts=70,
         prompt="By how much does CAT's **circulating supply grow next month**, in %?",
         hint="480M ÷ 24 months = monthly unlock  →  ÷ 200M circulating × 100",
         target=CAT_MONTH_PCT, tol=0.2, norm=pct_from_fraction(0.5),
         show=f"{CAT_MONTH_PCT:.0f}% in one month  ({CAT_MONTHLY/1e6:.0f}M new tokens on {CAT_CIRC/1e6:.0f}M)",
         why=f"ETH's supply grows ~{ETH_NEW_PCT:.1f}% in a *year*. CAT's grows 10% in a *month*."),
    dict(id="q15", sec=4, kind="num", pts=50,
         prompt="One month's unlock is worth how many **days of CAT's entire trading volume**?",
         hint="20M tokens × $2  →  ÷ $5M a day",
         target=CAT_DAYS, tol=0.2,
         show=f"{CAT_DAYS:.0f} days  (${CAT_MONTHLY*CAT_PRICE/1e6:.0f}M ÷ $5M)",
         why="If even half the insiders sell, the market has to absorb four full days of volume in new supply, every month for two years."),
    dict(id="q16", sec=4, kind="mcq", pts=30,
         prompt="Why do big unlocks often push a token's price down?",
         options=["Unlocked tokens are worth less than circulating tokens",
                  "Insiders who got in cheap tend to sell, and new supply arrives faster than new buyers",
                  "Exchanges must delist a token during an unlock",
                  "Unlocks raise transaction fees"],
         answer=1,
         why="Supply and demand. Before you buy any token, check its unlock schedule (Tokenomist and CoinGecko both show them)."),
]
QID = {q["id"]: q for q in Q}
TOTAL_PTS = sum(q["pts"] for q in Q)
assert TOTAL_PTS == 1000, TOTAL_PTS
NSEC = len(SECTIONS)
FINAL_PROMPT = ("You have to hold either **ETH or SOL** for the next five years. Which one, and which "
                "tokenomics fact from today drives your pick? One line.")


def sec_questions(i):
    return [q for q in Q if q["sec"] == i]


def sec_max(i):
    return sum(q["pts"] for q in sec_questions(i))


def grade_q(q, raw):
    """Returns (points, verdict) with verdict in full/half/zero."""
    if raw is None or str(raw).strip() == "":
        return 0, "zero"
    if q["kind"] == "mcq":
        try:
            ok = int(raw) == q["answer"]
        except Exception:
            ok = False
        return (q["pts"], "full") if ok else (0, "zero")
    v = parse_num(raw)
    if v is None:
        return 0, "zero"
    if q.get("norm"):
        v = q["norm"](v)
    d = abs(v - q["target"])
    if d <= q["tol"]:
        return q["pts"], "full"
    if d <= q["tol"] * 2:
        return q["pts"] // 2, "half"
    return 0, "zero"


def participation(score):
    return round(60 + 40 * score / TOTAL_PTS, 1)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_closed():
    return datetime.now(timezone.utc) > DUE


def esc(s):
    """Streamlit markdown reads $...$ as LaTeX and ~...~ as strikethrough. Escape both."""
    return str(s).replace("$", "\\$").replace("~", "\\~")


def M(s, **kw):
    st.markdown(esc(s), **kw)


def H(s):
    """Raw HTML blocks: markdown escapes don't apply there, so use entities."""
    st.markdown(str(s).replace("$", "&#36;").replace("~", "&#126;"), unsafe_allow_html=True)


def scroll_top():
    """Jump the page back to the top after a section changes (Streamlit keeps the old scroll offset)."""
    try:
        import streamlit.components.v1 as components
        components.html("""<script>
        function up(){try{const d=window.parent.document;
          for(const sel of ['[data-testid="stMain"]','[data-testid="stAppViewContainer"]','section.main']){
            const el=d.querySelector(sel); if(el){el.scrollTo({top:0,behavior:'instant'});}}
          window.parent.scrollTo(0,0);}catch(e){}}
        up(); [60,250,600].forEach(t=>setTimeout(up,t));
        </script>""", height=0)
    except Exception:
        pass


def cell(s):
    return esc(str(s)).replace("|", "/").replace("\n", " ")


def safe_cell(s):
    """Stop spreadsheet formula injection from free-text answers."""
    s = "" if s is None else str(s)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


# ─── Process-wide state ────────────────────────────────────────────────────────
# Streamlit re-executes this file on every interaction, which resets module globals.
# Anything that must be shared by every student (one DB connection, one lock, one sync
# worker) lives on a module parked in sys.modules, which survives reruns.
_cand = types.ModuleType("_vca_w4_state")
_cand.lock = threading.Lock()
_cand.conn = None
_cand.pend = {}
_cand.pl = threading.Lock()
_cand.wake = threading.Event()
_cand.worker = None
_S = sys.modules.setdefault("_vca_w4_state", _cand)
_S.sheet_url = SHEET_URL
LK = _S.lock


# ─── Storage: SQLite, one shared connection, WAL ───────────────────────────────
def conn():
    if _S.conn is None:
        with LK:
            if _S.conn is None:
                c = sqlite3.connect(DB, check_same_thread=False, timeout=15)
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA busy_timeout=8000")
                c.execute("""CREATE TABLE IF NOT EXISTS r(
                    email TEXT PRIMARY KEY, name TEXT, status TEXT, secs INT, score INT,
                    answers TEXT, pts TEXT, written TEXT,
                    started TEXT, updated TEXT, completed TEXT,
                    synced TEXT, sync_err TEXT, onchain TEXT)""")
                c.execute("CREATE TABLE IF NOT EXISTS cfg(k TEXT PRIMARY KEY, v TEXT)")
                c.commit()
                _S.conn = c
    return _S.conn


def load(email):
    c = conn()
    with LK:
        row = c.execute("SELECT email,name,status,secs,score,answers,pts,written,started,updated,"
                        "completed,synced,sync_err,onchain FROM r WHERE email=?", (email,)).fetchone()
    if not row:
        return None
    keys = ["email", "name", "status", "secs", "score", "answers", "pts", "written", "started",
            "updated", "completed", "synced", "sync_err", "onchain"]
    d = dict(zip(keys, row))
    d["answers"] = json.loads(d["answers"] or "{}")
    d["pts"] = json.loads(d["pts"] or "{}")
    d["onchain"] = json.loads(d["onchain"] or "{}")
    return d


def upsert(d):
    c = conn()
    with LK:
        c.execute("""INSERT INTO r(email,name,status,secs,score,answers,pts,written,started,updated,completed,onchain)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(email) DO UPDATE SET name=excluded.name,status=excluded.status,
                     secs=excluded.secs,score=excluded.score,answers=excluded.answers,pts=excluded.pts,
                     written=excluded.written,updated=excluded.updated,completed=excluded.completed,
                     onchain=excluded.onchain""",
                  (d["email"], d["name"], d["status"], d["secs"], d["score"], json.dumps(d["answers"]),
                   json.dumps(d["pts"]), d.get("written", ""), d["started"], d["updated"],
                   d.get("completed", ""), json.dumps(d.get("onchain") or {})))
        c.commit()


def all_rows():
    c = conn()
    with LK:
        rs = c.execute("SELECT email FROM r ORDER BY score DESC, updated ASC").fetchall()
    return [load(x[0]) for x in rs]


def delete_row(email):
    c = conn()
    with LK:
        c.execute("DELETE FROM r WHERE email=?", (email,))
        c.commit()


def cfg_get(k, default=""):
    c = conn()
    with LK:
        r = c.execute("SELECT v FROM cfg WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def cfg_set(k, v):
    c = conn()
    with LK:
        c.execute("INSERT INTO cfg VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
        c.commit()


def mark_sync(email, updated, err):
    c = conn()
    with LK:
        if err:
            c.execute("UPDATE r SET sync_err=? WHERE email=?", (err[:200], email))
        else:
            c.execute("UPDATE r SET synced=?, sync_err='' WHERE email=?", (updated, email))
        c.commit()


# ─── Google Sheet sync: background worker, coalesced per student ───────────────
COLUMNS = (["week", "email", "name", "status", "sections_done", "score", "participation"]
           + [q["id"] for q in Q] + [q["id"] + "_pts" for q in Q]
           + ["written", "onchain_status", "onchain_network", "onchain_fee_lamports", "onchain_sig",
              "started_utc", "updated_utc", "completed_utc"])

def sheet_row(d):
    row = dict(week=WEEK, email=d["email"], name=safe_cell(d["name"]), status=d["status"],
               sections_done=d["secs"], score=d["score"], participation=participation(d["score"]),
               written=safe_cell(d.get("written", "")), started_utc=d["started"],
               updated_utc=d["updated"], completed_utc=d.get("completed", ""))
    oc = d.get("onchain") or {}
    row.update(onchain_status=oc.get("status", ""), onchain_network=oc.get("net", ""),
               onchain_fee_lamports=oc.get("fee", ""), onchain_sig=oc.get("sig", ""))
    for q in Q:
        raw = d["answers"].get(q["id"], "")
        if q["kind"] == "mcq" and raw != "":
            try:
                raw = "ABCD"[int(raw)]
            except Exception:
                pass
        row[q["id"]] = safe_cell(raw)
        row[q["id"] + "_pts"] = d["pts"].get(q["id"], "")
    return row


def post_sheet(d):
    body = json.dumps({"week": WEEK, "columns": COLUMNS, "row": sheet_row(d)}).encode()
    req = urllib.request.Request(_S.sheet_url, data=body, method="POST",
                                 headers={"Content-Type": "text/plain;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        txt = resp.read().decode("utf-8", "replace")
    try:
        out = json.loads(txt)
    except Exception:
        raise RuntimeError("Collector did not return JSON (check the Apps Script deployment access = Anyone)")
    if not out.get("ok"):
        raise RuntimeError(str(out.get("error", "collector error")))
    return out


def _worker():
    tries = {}
    while True:
        _S.wake.wait(2.0)
        _S.wake.clear()
        while True:
            with _S.pl:
                if not _S.pend:
                    break
                email = next(iter(_S.pend))
                _S.pend.pop(email)
            try:
                d = load(email)
                if d is None:
                    continue
                post_sheet(d)
                mark_sync(email, d["updated"], "")
                tries.pop(email, None)
            except Exception as e:  # keep the worker alive no matter what
                n = tries.get(email, 0) + 1
                tries[email] = n
                try:
                    mark_sync(email, "", f"try {n}: {e}")
                except Exception:
                    pass
                if n < 6:
                    time.sleep(min(2 * n, 8))
                    with _S.pl:
                        _S.pend.setdefault(email, time.time())


def enqueue(email):
    if not SHEET_URL:
        return
    with _S.pl:
        if _S.worker is None or not _S.worker.is_alive():
            _S.worker = threading.Thread(target=_worker, daemon=True, name="vca-w4-sync")
            _S.worker.start()
        _S.pend[email] = time.time()
    _S.wake.set()


def sheet_status(email):
    """Ask the collector whether this email already completed (survives app restarts). Fails open."""
    if not SHEET_URL:
        return None
    try:
        url = SHEET_URL + ("&" if "?" in SHEET_URL else "?") + urllib.parse.urlencode(
            {"week": WEEK, "email": email})
        with urllib.request.urlopen(url, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def from_sheet(email):
    """Rebuild a student's progress from the Sheet when this app's board was wiped by a restart."""
    r = sheet_status(email)
    if not r or not r.get("found"):
        return None
    row = r.get("row") or {}
    d = new_record(email, str(row.get("name", "")).lstrip("'"))
    try:
        d["status"] = str(row.get("status") or "started")
        d["secs"] = int(float(row.get("sections_done") or 0))
        for q in Q:
            raw = str(row.get(q["id"], "")).lstrip("'")
            if q["kind"] == "mcq" and raw in ("A", "B", "C", "D"):
                raw = str("ABCD".index(raw))
            if raw != "":
                d["answers"][q["id"]] = raw
            p = row.get(q["id"] + "_pts", "")
            if p not in ("", None):
                d["pts"][q["id"]] = int(float(p))
        d["score"] = sum(d["pts"].values())
        d["written"] = str(row.get("written", "")).lstrip("'")
        if row.get("onchain_sig"):
            d["onchain"] = dict(sig=str(row["onchain_sig"]), status=str(row.get("onchain_status", "")),
                                net=str(row.get("onchain_network", "")), fee=row.get("onchain_fee_lamports", ""))
        for k, src in (("started", "started_utc"), ("updated", "updated_utc"), ("completed", "completed_utc")):
            if row.get(src):
                d[k] = str(row[src])
    except Exception:
        return None
    upsert(d)
    mark_sync(email, d["updated"], "")
    return d


# ─── Look ──────────────────────────────────────────────────────────────────────
def css():
    st.markdown("""<style>
    .block-container{max-width:760px;padding-top:1.2rem;}
    header[data-testid="stHeader"]{display:none;}
    [data-testid="stToolbar"]{display:none;}
    .band{background:#0B1E3D;border-radius:12px;padding:18px 22px;margin-bottom:14px;}
    .band .k{color:#C6A15B;font-size:.78rem;font-weight:700;letter-spacing:.14em;}
    .band .t{color:#FFFFFF;font-size:1.55rem;font-weight:800;line-height:1.2;margin-top:4px;}
    .band .s{color:#C9D3E3;font-size:.9rem;margin-top:6px;}
    .sec{border-top:4px solid #1B8F8A;background:#F4F7FB;border-radius:10px;padding:4px 16px 2px;margin:8px 0 6px;}
    .sec h4{color:#0B1E3D;margin:10px 0 2px;font-size:1.05rem;letter-spacing:.02em;}
    .big{font-size:3.2rem;font-weight:800;color:#0B1E3D;line-height:1;}
    .gold{color:#A8843F;font-weight:700;}
    .ok{color:#137a55;font-weight:700;} .half{color:#a86b00;font-weight:700;} .no{color:#b3261e;font-weight:700;}
    .fb{background:#FFFFFF;border:1px solid #DCE3EE;border-left:4px solid #C6A15B;border-radius:8px;
        padding:10px 14px;margin:4px 0 12px;font-size:.93rem;}
    .mini{color:#5B6B82;font-size:.82rem;}
    .stButton>button[kind="primary"],button[data-testid="stBaseButton-primary"],
    button[data-testid="stBaseButton-primaryFormSubmit"],[data-testid="stFormSubmitButton"] button{
        background:#0B1E3D!important;border-color:#0B1E3D!important;color:#fff!important;}
    iframe[title="streamlit_components_v1.html"]{display:none;}
    </style>""", unsafe_allow_html=True)


def band(kicker, title, sub=""):
    st.markdown(f"<div class='band'><div class='k'>{kicker}</div><div class='t'>{title}</div>"
                f"{f'<div class=s>{sub}</div>' if sub else ''}</div>", unsafe_allow_html=True)


def data_card():
    M(f"""
**Data card** · locked Mon 21 Sep 2026 · CoinGecko, validatorqueue.com

| | ETH | SOL |
|---|---|---|
| Price | ${ETH_PRICE:,.2f} | ${SOL_PRICE:,.2f} |
| Supply | {ETH_SUPPLY/1e6:.2f}M | {SOL_TOTAL/1e6:.2f}M total · {SOL_CIRC/1e6:.2f}M circulating |
| Max supply | none | none |
| Staked | {ETH_STAKED/1e6:.1f}M ({ETH_STAKED/ETH_SUPPLY*100:.1f}%) | ~{SOL_STAKED_PCT}% |
| New supply rule | ~{ETH_APR}% a year paid to stakers | {SOL_INFL}% a year, falling 15% a year |
| What gets burned | base fee of every transaction | half of the base fee |
| Block time | 12 seconds | 0.4 seconds |
""")


def verdict_html(v):
    return {"full": "<span class='ok'>✓ Correct</span>",
            "half": "<span class='half'>½ Close (half credit)</span>",
            "zero": "<span class='no'>✗ Not quite</span>"}[v]


def show_feedback(q, raw, pts):
    _, v = grade_q(q, raw)
    if q["kind"] == "mcq":
        try:
            given = q["options"][int(raw)]
        except Exception:
            given = "—"
        right = q["options"][q["answer"]]
    else:
        given = raw or "—"
        right = q["show"]
    H(f"<div class='fb'>{verdict_html(v)} &nbsp;<span class='mini'>{pts}/{q['pts']} pts · "
      f"you said: {html.escape(str(given))}</span><br><b>Answer:</b> {html.escape(right)}<br>"
      f"{html.escape(q['why'])}</div>")


# ─── On-chain lab: verify a student's own Solana transaction ───────────────────
B58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def rpcs():
    out = [("sponsor RPC", SOL_RPC)] if SOL_RPC else []
    return out + [("mainnet", "https://api.mainnet-beta.solana.com"), ("devnet", "https://api.devnet.solana.com")]


def clean_sig(raw):
    s = (raw or "").strip()
    if "/tx/" in s:                                   # pasted an explorer link
        s = s.split("/tx/", 1)[1]
    return s.split("?")[0].split("#")[0].strip().strip("/")


def looks_like_phrase(raw):
    w = (raw or "").split()
    return len(w) >= 11 and all(x.isalpha() for x in w)


def verify_sig(sig):
    """Look the signature up on each network. Returns a dict; never raises."""
    errs, nets_checked = [], 0
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                       "params": [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                        "commitment": "confirmed"}]}).encode()
    for net, url in rpcs():
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                out = json.loads(resp.read().decode("utf-8", "replace"))
            nets_checked += 1
            res = out.get("result")
            if res:
                meta = res.get("meta") or {}
                return dict(sig=sig, status="verified", net=net, fee=meta.get("fee"),
                            slot=res.get("slot"), block_time=res.get("blockTime"),
                            success=meta.get("err") is None)
        except Exception as e:
            errs.append(f"{net}: {str(e)[:60]}")
    if nets_checked == 0:
        return dict(sig=sig, status="unverified", err="; ".join(errs))
    return dict(sig=sig, status="not_found")


def onchain_lab(d):
    oc = d.get("onchain") or {}
    done = oc.get("status") == "verified"
    label = "✓ On-chain lab · verified" if done else "🔗 On-chain lab · make your first Solana transaction"
    with st.expander(label, expanded=bool(st.session_state.get("lab_open"))):
        if done:
            fee = oc.get("fee") or 0
            M(f"Verified on **{oc.get('net')}** · slot {oc.get('slot', '—'):,} · fee **{fee:,} lamports** "
              f"= {fee/1e9:.6f} SOL ≈ ${fee/1e9*SOL_PRICE:.5f}"
              if isinstance(oc.get("slot"), int) else
              f"Verified on **{oc.get('net')}** · fee **{fee} lamports**")
            M("A plain transfer with one signature pays exactly the 5,000-lamport base fee. "
              "Anything above that is a priority fee your wallet added to get in faster.")
            return
        M("""
1. Install **Phantom** or **Solflare** and create a **new** wallet. Write the recovery phrase on paper. **Never type it into any website, including this one.**
2. Get SOL: use the SOL handed out in class, or free test SOL (switch the wallet to **Devnet**, then use faucet.solana.com).
3. Send a small amount (0.001 SOL is plenty) to a classmate or to your own second account.
4. In the wallet's activity, open the transaction on Solscan or Solana Explorer and copy the **transaction signature** (the long string after /tx/). Pasting the whole link works too.
""")
        if oc.get("status") == "unverified":
            st.info("Your signature is saved. The network lookup was down, so it will be checked by hand.")
        raw = st.text_input("Transaction signature or explorer link", key="in_sig")
        if st.button("Verify my transaction", key="btn_sig"):
            st.session_state["lab_open"] = True
            if looks_like_phrase(raw):
                st.error("That looks like a recovery phrase. Nothing was saved. Never share it with anyone or "
                         "any site. Treat that wallet as compromised: create a new one and move any funds.")
                return
            sig = clean_sig(raw)
            if 32 <= len(sig) <= 44 and set(sig) <= B58:
                st.warning("That's a wallet address, not a transaction. Open the transaction itself and copy its signature.")
                return
            if not (80 <= len(sig) <= 90 and set(sig) <= B58):
                st.warning("That doesn't look like a Solana transaction signature (about 88 letters and numbers).")
                return
            with st.spinner("Looking it up on Solana..."):
                res = verify_sig(sig)
            if res["status"] == "not_found":
                st.warning("Not found on mainnet or devnet yet. Wait 15 seconds and try again, "
                           "and check you copied the whole signature.")
                return
            if res["status"] == "verified" and not res.get("success", True):
                st.warning("Found it, but that transaction failed on-chain. Try sending again.")
            d["onchain"] = res
            d["updated"] = now_utc()
            upsert(d)
            enqueue(d["email"])
            st.rerun()


# ─── Student view ──────────────────────────────────────────────────────────────
def new_record(email, name):
    t = now_utc()
    return dict(email=email, name=name, status="started", secs=0, score=0, answers={}, pts={},
                written="", started=t, updated=t, completed="", onchain={})


def student():
    ss = st.session_state
    band(f"VILLANOVA CRYPTO ACADEMY · WEEK {WEEK}", TITLE,
         f"5 short sections · about 25 minutes · closes {DUE.strftime('%a %-m/%-d, %-I:%M %p')} ET")

    # Sign in
    if not ss.get("email"):
        st.markdown("Read each section, answer the checks, and see the explanation right away. "
                    "Your answers lock when you check a section, and your progress saves as you go. "
                    "If you lose the page, re-enter the same email to pick up where you left off.")
        if is_closed():
            st.error("This module is closed.")
            return
        with st.form("signin"):
            nm = st.text_input("Full name")
            em = st.text_input("Villanova email", placeholder="netid@villanova.edu")
            go = st.form_submit_button("Start →", type="primary")
        if go:
            nm, em = nm.strip(), em.strip().lower()
            if not nm or not em.endswith("villanova.edu") or "@" not in em:
                st.error("Enter your name and your @villanova.edu email. That is how completion is recorded.")
                return
            d = load(em) or from_sheet(em)
            if d is None:
                d = new_record(em, nm)
                upsert(d)
                enqueue(em)
            ss.email, ss.name = em, d["name"]
            st.rerun()
        return

    d = load(ss.email)
    if d is None:            # app restarted and the board was wiped mid-module
        d = from_sheet(ss.email)
    if d is None:
        d = new_record(ss.email, ss.get("name", ""))
        upsert(d)
        enqueue(ss.email)

    secs = d["secs"]
    done = d["status"] == "complete"
    st.progress(min(secs, NSEC) / NSEC,
                text=f"{d['name']} · {min(secs, NSEC)} of {NSEC} sections · {d['score']} pts so far")
    if not is_closed():
        onchain_lab(d)

    if st.session_state.pop("scroll", False):
        scroll_top()
    reviewing = st.session_state.get("review")
    if reviewing is not None and reviewing != secs - 1:
        reviewing = None

    # Completed sections: collapsed, feedback first, notes after
    for i in range(min(secs, NSEC)):
        if i == reviewing:
            continue
        got = sum(d["pts"].get(q["id"], 0) for q in sec_questions(i))
        with st.expander(f"✓ Section {i+1} · {SECTIONS[i]['title']}  ·  {got}/{sec_max(i)} pts"):
            for q in sec_questions(i):
                M(f"**{q['prompt']}**")
                show_feedback(q, d["answers"].get(q["id"], ""), d["pts"].get(q["id"], 0))
            st.markdown("---")
            M(SECTIONS[i]["learn"])
            if SECTIONS[i].get("card"):
                data_card()

    if reviewing is not None:
        review(d, reviewing)
        return

    if done:
        results(d)
        return
    if is_closed():
        st.error("This module closed before you finished. Your progress so far is recorded.")
        return

    if secs < NSEC:
        section(d, secs)
    else:
        final(d)


def section(d, i):
    S = SECTIONS[i]
    st.markdown(f"<div class='sec'><h4>SECTION {i+1} OF {NSEC} · {S['title'].upper()}</h4>"
                f"<p class='mini'>about {S['mins']} minutes</p></div>", unsafe_allow_html=True)
    M(S["learn"])
    if S.get("card"):
        data_card()
    st.markdown("---")
    st.markdown("#### Check yourself")

    vals = {}
    for q in sec_questions(i):
        n = Q.index(q) + 1
        M(f"**{n}. {q['prompt']}**")
        if q["kind"] == "mcq":
            labels = [f"{'ABCD'[k]}. {o}" for k, o in enumerate(q["options"])]
            pick = st.radio(q["id"], labels, index=None, key=f"in_{q['id']}", label_visibility="collapsed")
            vals[q["id"]] = "" if pick is None else str(labels.index(pick))
        else:
            vals[q["id"]] = st.text_input(q["id"], key=f"in_{q['id']}", label_visibility="collapsed",
                                          placeholder="your answer")
            H(f"<p class='mini'>How: {html.escape(q['hint'])}</p>")

    if st.button("Check my answers", type="primary", key=f"check_{i}"):
        missing = [k for k, v in vals.items() if str(v).strip() == ""]
        if missing:
            st.warning("Answer every question first. A best guess is fine; you'll see the explanation right after.")
            return
        fresh = load(d["email"])       # guard against double clicks / two tabs
        if fresh and fresh["secs"] > i:
            st.rerun()
        for qid, raw in vals.items():
            pts, _ = grade_q(QID[qid], raw)
            d["answers"][qid] = str(raw).strip()
            d["pts"][qid] = pts
        d["secs"] = i + 1
        d["score"] = sum(d["pts"].values())
        d["status"] = "in_progress"
        d["updated"] = now_utc()
        upsert(d)
        enqueue(d["email"])
        st.session_state["review"] = i
        st.session_state["scroll"] = True
        st.rerun()


def review(d, i):
    got = sum(d["pts"].get(q["id"], 0) for q in sec_questions(i))
    H(f"<div class='sec'><h4>SECTION {i+1} RESULTS · {got} / {sec_max(i)} PTS</h4>"
      f"<p class='mini'>Read why, then continue.</p></div>")
    for q in sec_questions(i):
        M(f"**{Q.index(q)+1}. {q['prompt']}**")
        show_feedback(q, d["answers"].get(q["id"], ""), d["pts"].get(q["id"], 0))
    nxt = f"Continue to Section {i+2} →" if i + 1 < NSEC else "Continue to the last step →"
    if st.button(nxt, type="primary", key=f"cont_{i}"):
        st.session_state.pop("review", None)
        st.session_state["scroll"] = True
        st.rerun()


def final(d):
    st.markdown(f"<div class='sec'><h4>LAST STEP · YOUR CALL</h4></div>", unsafe_allow_html=True)
    st.markdown(FINAL_PROMPT)
    line = st.text_area("One line", key="in_written", height=90, label_visibility="collapsed",
                        placeholder="e.g. SOL, because ... / ETH, because ...")
    if st.button("Submit and finish", type="primary"):
        if len(line.strip()) < 8:
            st.warning("Write one real sentence. This line is what completes the module.")
            return
        t = now_utc()
        d.update(written=line.strip()[:500], status="complete", updated=t, completed=t)
        upsert(d)
        enqueue(d["email"])
        st.session_state["celebrate"] = True
        st.rerun()


def results(d):
    if st.session_state.pop("celebrate", False):
        st.balloons()
    sc = d["score"]
    st.markdown(f"<div class='band' style='text-align:center'><div class='k'>WEEK {WEEK} COMPLETE</div>"
                f"<div class='t' style='font-size:3rem'>{sc} / {TOTAL_PTS}</div>"
                f"<div class='s'>{d['name']} · participation score {participation(sc)}</div></div>",
                unsafe_allow_html=True)
    rows = "| Section | Points |\n|---|---|\n"
    for i, S in enumerate(SECTIONS):
        got = sum(d["pts"].get(q["id"], 0) for q in sec_questions(i))
        rows += f"| {i+1}. {S['title']} | {got} / {sec_max(i)} |\n"
    M(rows)
    M(f"**Your call:** {cell(d.get('written', ''))}")
    st.success("Recorded. You're done for Week 4.")
    M(f"""
**Three things to remember**
1. ETH now issues new supply at about Bitcoin's pace (~{ETH_NEW_PCT:.1f}% a year). Cheap Layer 2 fees shrank the burn.
2. Solana pays ~${SOL_NEW_USD_B:.1f}B a year for security. Stakers are made whole; non-stakers are diluted.
3. Before buying any token, compare FDV to market cap and check the unlock schedule.
""")


# ─── Presenter view ────────────────────────────────────────────────────────────
def student_url():
    u = cfg_get("student_url", "")
    if u:
        return u
    try:
        host = st.context.headers.get("host", "")
        if host and "localhost" not in host:
            return f"https://{host}/"
    except Exception:
        pass
    return ""


def presenter():
    band(f"PRESENTER · WEEK {WEEK}", TITLE, f"closes {DUE.strftime('%a %-m/%-d %-I:%M %p')} ET")

    if PRESENTER_KEY == DEFAULT_KEY:
        st.caption("Using the default presenter key. Set PRESENTER_KEY in Secrets to change it.")
    if not SHEET_URL:
        st.error("SHEET_URL is not set. Responses are only on this app's board, which is wiped if the app "
                 "restarts. Download the CSV before you leave, or add the Apps Script URL in Secrets.")
    else:
        c1, c2 = st.columns([3, 1])
        c1.success("Google Sheet sync is on. Every section a student finishes is written to the Sheet.")
        if c2.button("Test sheet"):
            r = sheet_status("ping@villanova.edu")
            if r and r.get("ok"):
                c2.success("Reachable")
            else:
                c2.error("No reply")

    # Link + QR
    with st.expander("Student link & QR", expanded=True):
        url = student_url()
        new = st.text_input("Student link", value=url, help="Auto-detected. Paste the app URL if blank.")
        if new.strip() and new.strip() != url:
            cfg_set("student_url", new.strip())
            url = new.strip()
        if url:
            try:
                q = urllib.parse.quote(url, safe="")
                st.markdown(f"<div style='text-align:center'>"
                            f"<img src='https://api.qrserver.com/v1/create-qr-code/?size=340x340&margin=12&data={q}' "
                            f"width='340' alt='QR code'/><div class='big' style='font-size:1.3rem;margin-top:8px'>"
                            f"{url}</div></div>", unsafe_allow_html=True)
            except Exception:
                st.markdown(f"### {url}")

    board_block()

    with st.expander("Roster · paste the VCA send list to see who hasn't started"):
        roster_raw = cfg_get("roster", "")
        new = st.text_area("Emails (one per line, or comma separated)", value=roster_raw, height=120,
                           key="roster_box")
        if st.button("Save roster"):
            cfg_set("roster", new)
            st.rerun()

    with st.expander("Answer key & talking points"):
        for i, S in enumerate(SECTIONS):
            M(f"**Section {i+1} · {S['title']}**: {S['talk']}")
            for q in sec_questions(i):
                ans = q["options"][q["answer"]] if q["kind"] == "mcq" else q["show"]
                M(f"- Q{Q.index(q)+1} ({q['pts']} pts): {ans}")
        st.markdown("""
**Optional live Cowork extension (5 min).** Students paste into Claude:
> *Find one token with a scheduled unlock in the next 30 days (use Tokenomist or CoinGecko). Give the unlock size in tokens and dollars, the unlock as a % of circulating supply, and the unlock's dollar value divided by 24-hour trading volume. Cite your sources.*

Take two or three answers out loud and rank them by unlock $ ÷ volume.
""")

    with st.expander("Admin: remove a test submission"):
        em = st.text_input("Email to remove from this board").strip().lower()
        if st.button("Remove") and em:
            delete_row(em)
            st.success(f"Removed {em} from this board. If it synced, also delete its row in the Sheet.")


def board_block():
    try:
        frag = st.fragment(run_every=10)
    except Exception:
        frag = None
    if frag is not None:
        frag(board)()
    else:
        if st.button("Refresh"):
            st.rerun()
        board()


def board():
    rows = all_rows()
    roster_raw = cfg_get("roster", "")
    roster = sorted({x.strip().lower() for x in roster_raw.replace(",", "\n").replace(";", "\n").split()
                     if "@" in x})
    seen = {r["email"] for r in rows}
    complete = [r for r in rows if r["status"] == "complete"]

    c = st.columns(5)
    c[0].metric("Started", len(rows))
    c[1].metric("Completed", len(complete))
    c[2].metric("On-chain ✓", sum(1 for r in rows if (r.get("onchain") or {}).get("status") == "verified"))
    c[3].metric("Avg score", f"{sum(r['score'] for r in complete)/len(complete):.0f}" if complete else "—")
    c[4].metric("Roster not started", len([e for e in roster if e not in seen]) if roster else "—")
    st.caption(f"Auto-refreshes every 10 seconds · {datetime.now(ET).strftime('%-I:%M:%S %p')} ET")

    if rows:
        md = "| # | Name | Progress | Score | On-chain | Synced |\n|---|---|---|---|---|---|\n"
        for n, r in enumerate(rows, 1):
            prog = "✅ done" if r["status"] == "complete" else f"{min(r['secs'], NSEC)}/{NSEC}"
            if not SHEET_URL:
                sy = "—"
            elif r.get("synced") and r["synced"] == r["updated"]:
                sy = "✓"
            elif r.get("sync_err"):
                sy = "✗ retrying"
            else:
                sy = "…"
            ocs = (r.get("onchain") or {}).get("status", "")
            oc = {"verified": "✓", "unverified": "check by hand"}.get(ocs, "—")
            md += f"| {n} | {cell(r['name'])} | {prog} | {r['score']} | {oc} | {sy} |\n"
        st.markdown(md)

        # Where the room is struggling
        st.markdown("#### Question check · % of answers fully correct")
        line = ""
        for q in Q:
            got = [r["pts"][q["id"]] for r in rows if q["id"] in r["pts"]]
            if not got:
                continue
            p = 100 * sum(1 for g in got if g == q["pts"]) / len(got)
            flag = " ⚠️ re-teach" if p < 60 else ""
            line += f"- Q{Q.index(q)+1} · {p:.0f}% of {len(got)}{flag}: {q['prompt'][:70].replace('*', '')}…\n"
        M(line or "No checks yet.")

        lines = [r for r in complete if r.get("written")]
        if lines:
            st.markdown("#### Their calls · read a few out loud")
            for r in lines:
                st.markdown(f"- **{cell(r['name'])}**: {cell(r['written'])}")

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(COLUMNS)
        for r in rows:
            sr = sheet_row(r)
            w.writerow([sr.get(k, "") for k in COLUMNS])
        st.download_button("Download CSV for the gradebook", buf.getvalue(),
                           f"vca_week{WEEK}_{datetime.now(ET).strftime('%Y%m%d_%H%M')}.csv", "text/csv",
                           key=f"dl_{len(rows)}_{len(complete)}")
    else:
        st.info("No one has started yet.")

    if roster:
        missing = [e for e in roster if e not in seen]
        inprog = [r["email"] for r in rows if r["status"] != "complete" and r["email"] in roster]
        st.markdown(f"**Roster not started ({len(missing)}):** " + (", ".join(missing) or "none"))
        st.markdown(f"**Started, not finished ({len(inprog)}):** " + (", ".join(inprog) or "none"))



# ─── Route ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title=f"VCA Week {WEEK}", page_icon="🎓", layout="centered")
css()
conn()
qp = st.query_params
if qp.get("p") == "present":
    if qp.get("k") == PRESENTER_KEY or st.session_state.get("pk_ok"):
        st.session_state["pk_ok"] = True
        presenter()
    else:
        band(f"PRESENTER · WEEK {WEEK}", "Presenter key required")
        k = st.text_input("Key", type="password")
        if k:
            if k == PRESENTER_KEY:
                st.session_state["pk_ok"] = True
                st.rerun()
            else:
                st.error("Wrong key.")
else:
    student()
