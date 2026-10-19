"""VCA Week 7 · Price the Perps. Only dependency: streamlit.
Presenter view: ?p=present&k=vca7
"""
import sqlite3, datetime, csv, io
import streamlit as st

st.set_page_config(page_title="VCA Week 7 · Price the Perps", page_icon="📊", layout="centered")
DB = "week7.db"
con = sqlite3.connect(DB, check_same_thread=False)
con.execute("""CREATE TABLE IF NOT EXISTS r (ts TEXT, name TEXT, email TEXT, q1 TEXT, q2 TEXT, q3 TEXT,
               q4 TEXT, q5 TEXT, score INT, grade REAL)""")

# DeFiLlama 30d revenue × 12, market caps; pulled 10/19/2026
TABLE = [
    ("dYdX", "$97M", "$3.3M"),
    ("Lighter", "$762M", "$32.5M"),
    ("Hyperliquid", "$17.15B", "$839M"),
    ("Jupiter", "$968M", "$59.8M"),
    ("GMX", "$89M", "$51.7M"),
]
NAMES = [t[0] for t in TABLE]
KEY = {"q1": "GMX", "q2": "dYdX", "q3": "16x",
       "q4": "One huge month × 12 makes its yearly revenue look too big"}
Q4_OPTS = ["The market is wrong. GMX is a steal",
           "One huge month × 12 makes its yearly revenue look too big",
           "GMX has no token"]

qp = st.query_params
if qp.get("p") == "present" and qp.get("k") == "vca7":
    st.title("Presenter · Week 7")
    rows = con.execute("SELECT * FROM r ORDER BY ts").fetchall()
    st.metric("Responses", len(rows))
    if rows:
        st.metric("Average score", f"{sum(r[8] for r in rows)/len(rows):.0f} / 1000")
        for q, i in [("Q1 cheapest", 3), ("Q2 most expensive", 4), ("Q3 Jupiter", 5), ("Q4 GMX", 6)]:
            counts = {}
            for r in rows:
                counts[r[i]] = counts.get(r[i], 0) + 1
            st.write(f"**{q}**", counts)
        st.subheader("Defend the outlier")
        for r in rows:
            st.write(f"**{r[1]}**: {r[7]}")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "name", "email", "q1", "q2", "q3", "q4", "q5", "score", "participation"])
        w.writerows(rows)
        st.download_button("Download CSV", buf.getvalue(), "vca_week7.csv", "text/csv")
    if st.button("Refresh"):
        st.rerun()
    st.stop()

st.title("Price the Perps")
st.caption("VCA Week 7 · 1,000 pts · about 7 minutes")
name = st.text_input("Name")
email = st.text_input("Villanova email")

st.subheader("The comp table")
st.caption("Market cap ÷ yearly revenue = the multiple. Smaller multiple = cheaper.")
st.table({"Protocol": NAMES, "Market cap": [t[1] for t in TABLE], "Revenue, 1 yr": [t[2] for t in TABLE]})

st.subheader("Part 1 · Rank them")
q1 = st.radio("1. Which one is the CHEAPEST (lowest multiple)?", NAMES, index=None)
q2 = st.radio("2. Which one is the MOST EXPENSIVE (highest multiple)?", NAMES, index=None)
q3 = st.radio("3. What is Jupiter's multiple? ($968M ÷ $59.8M)", ["5x", "16x", "33x"], index=None)

st.subheader("Part 2 · Defend the outlier")
st.caption("GMX looks like 2x. Its revenue over the full past year was only about $18M.")
q4 = st.radio("4. Why does GMX look so cheap?", Q4_OPTS, index=None)
q5 = st.text_area("5. One sentence: is your outlier mispriced, or is its revenue number misleading?")

if st.button("Submit", type="primary"):
    if not name or "@" not in email:
        st.error("Add your name and Villanova email.")
    elif None in (q1, q2, q3, q4) or len(q5.strip()) < 10:
        st.error("Answer all five questions.")
    else:
        score = 200 * sum([q1 == KEY["q1"], q2 == KEY["q2"], q3 == KEY["q3"], q4 == KEY["q4"]]) + 200
        grade = 60 + 40 * score / 1000
        con.execute("INSERT INTO r VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(timespec="seconds"), name, email.strip().lower(),
                     q1, q2, q3, q4, q5.strip(), score, grade))
        con.commit()
        st.success(f"Submitted. Score: {score} / 1000")
        st.write("**Answers:** cheapest GMX (2x) · most expensive dYdX (29x) · Jupiter 16x · "
                 "GMX had one huge month, so 30 days × 12 overstates its revenue (full year: about 5x).")
