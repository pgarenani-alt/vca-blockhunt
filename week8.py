"""VCA Week 8 · Who's Paying the Yield? Only dependency: streamlit.
Presenter view: ?p=present&k=vca8
"""
import sqlite3, datetime, csv, io
import streamlit as st

st.set_page_config(page_title="VCA Week 8 · Who's Paying the Yield?", page_icon="💵", layout="centered")
DB = "week8.db"
con = sqlite3.connect(DB, check_same_thread=False)
con.execute("""CREATE TABLE IF NOT EXISTS r (ts TEXT, name TEXT, email TEXT, pool TEXT, apy REAL, base REAL,
               reward REAL, verdict TEXT, q6 TEXT, q7 TEXT, q8 TEXT, score INT, grade REAL)""")

KEY = {"q6": "Positive", "q7": "Longs pay shorts", "q8": "Longs"}


def num(x):
    try:
        return float(str(x).replace("%", "").replace(",", "").strip())
    except Exception:
        return None


qp = st.query_params
if qp.get("p") == "present" and qp.get("k") == "vca8":
    st.title("Presenter · Week 8")
    rows = con.execute("SELECT * FROM r ORDER BY ts").fetchall()
    st.metric("Responses", len(rows))
    if rows:
        st.metric("Average score", f"{sum(r[11] for r in rows)/len(rows):.0f} / 1000")
        st.subheader("Pools the room found (most subsidized first)")
        pools = []
        for r in rows:
            share = (r[6] / r[4] * 100) if r[4] else 0
            pools.append((share, r[3], r[4], r[5], r[6], r[7], r[1]))
        pools.sort(reverse=True)
        st.table({"Pool": [p[1] for p in pools], "APY %": [p[2] for p in pools],
                  "Base %": [p[3] for p in pools], "Reward %": [p[4] for p in pools],
                  "% from rewards": [f"{p[0]:.0f}%" for p in pools], "Their call": [p[5] for p in pools],
                  "Student": [p[6] for p in pools]})
        for q, i in [("Q6 BTC funding", 8), ("Q7 who pays", 9), ("Q8 liquidated first", 10)]:
            counts = {}
            for r in rows:
                counts[r[i]] = counts.get(r[i], 0) + 1
            st.write(f"**{q}**", counts)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "name", "email", "pool", "apy", "base", "reward", "verdict",
                    "q6", "q7", "q8", "score", "participation"])
        w.writerows(rows)
        st.download_button("Download CSV", buf.getvalue(), "vca_week8.csv", "text/csv")
    if st.button("Refresh"):
        st.rerun()
    st.stop()

st.title("Who's Paying the Yield?")
st.caption("VCA Week 8 · 1,000 pts · about 6 minutes")
name = st.text_input("Name")
email = st.text_input("Villanova email")

st.subheader("Part 1 · Find a pool")
st.markdown("Open **[defillama.com/yields](https://defillama.com/yields?token=USDC)**, search **USDC**, "
            "and pick any pool. Under APY you'll see the total, then Base and +Reward. "
            "No reward listed? Put 0.")
pool = st.text_input("1. Pool name (for example: Aave Ethereum USDC)")
c1, c2, c3 = st.columns(3)
apy = c1.text_input("2. Total APY %")
base = c2.text_input("3. Base APY %")
reward = c3.text_input("4. Reward APY %")
q5 = st.radio("5. Your call: is this yield real or a subsidy?",
              ["Real: mostly Base (users pay it)", "Subsidy: mostly Reward (printed tokens)"], index=None)

st.subheader("Part 2 · Read the crowd")
st.markdown("Open **[coinglass.com/FundingRate](https://www.coinglass.com/FundingRate)**. "
            "Close the cookie pop-up. BTC is the top row.")
q6 = st.radio("6. Is BTC funding positive or negative right now?", ["Positive", "Negative", "Exactly zero"], index=None)
q7 = st.radio("7. When funding is positive, who pays whom?", ["Longs pay shorts", "Shorts pay longs"], index=None)
q8 = st.radio("8. BTC drops 10% tomorrow. Who gets liquidated first?", ["Longs", "Shorts"], index=None)

if st.button("Submit", type="primary"):
    a, b, rw = num(apy), num(base), num(reward)
    if not name or "@" not in email:
        st.error("Add your name and Villanova email.")
    elif not pool.strip() or None in (a, b, rw):
        st.error("Fill in the pool name and all three numbers (use 0 if there's no reward).")
    elif None in (q5, q6, q7, q8):
        st.error("Answer all eight questions.")
    else:
        subsidy = a > 0 and rw / a > 0.5
        verdict = "Subsidy" if q5.startswith("Subsidy") else "Real"
        score = 0
        score += 200 if abs(b + rw - a) <= 0.15 else 100
        score += 200 if verdict == ("Subsidy" if subsidy else "Real") else 0
        score += 200 * sum([q6 == KEY["q6"], q7 == KEY["q7"], q8 == KEY["q8"]])
        grade = 60 + 40 * score / 1000
        con.execute("INSERT INTO r VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(timespec="seconds"), name, email.strip().lower(),
                     pool.strip(), a, b, rw, verdict, q6, q7, q8, score, grade))
        con.commit()
        share = rw / a * 100 if a else 0
        st.success(f"Submitted. Score: {score} / 1000")
        st.write(f"**Your pool:** {share:.0f}% of its APY comes from rewards, so it's "
                 f"**{'a subsidy' if subsidy else 'real yield'}**. If rewards end, you earn about **{b:.2f}%**.")
        st.write("**Part 2:** BTC funding is a small positive number, so longs pay shorts. "
                 "A drop hits the longs first. About 0.01% is the normal baseline: balanced, not crowded yet.")
