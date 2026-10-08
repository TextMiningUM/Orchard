"""Logboek & Geschiedenis (design doc Sec B.9 / C.1 / C.7).

De 14 jaar handgeschreven logboeken (`Data/Data Log Books/jaar 2013.pdf` .. `jaar
2026.pdf`, 91 pagina's) zijn visueel getranscribeerd (vision-based transcriptie, niet een
klassieke OCR-engine -- zie `pipeline/ingest/build_logbook_database.py` en de
`_transcripts/`-map) en geladen in een genormaliseerde SQLite-database
(`Data/Orchard/OrchardLogbooks/orchard_logbook.db`): 487 entries, 1063 toepassingen, 14
jaargangen (2013-05-08 t/m 2025-11-07). Deze pagina is daarmee de eerste echte, werkende
implementatie van het episodische Track-2-geheugen uit ontwerp Sec B.4.

Elke entry draagt een `onzeker`-vlag (handschrift dat niet met zekerheid te lezen was) --
dit wordt hier altijd zichtbaar getoond, nooit verborgen, conform het "nooit verzinnen"-
principe (ontwerp Sec B.1/B.11).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import PATHS, get_logbook_conn, render_sidebar, render_weather_dialog_button  # noqa: E402

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Logboek & Geschiedenis", layout="wide")
st.title("Logboek & Geschiedenis")

ctx = render_sidebar(st)

DB_PATH = PATHS.logbooks_dir / "orchard_logbook.db"

conn = get_logbook_conn(st)
if conn is None:
    st.error(
        f"Database niet gevonden op `{DB_PATH}`. Bouw 'm eerst met:\n\n"
        "`.venv\\Scripts\\python.exe -m pipeline.ingest.build_logbook_database`"
    )
    st.stop()

n_pages, n_entries, n_toep, n_onzeker = conn.execute(
    "SELECT (SELECT COUNT(*) FROM pages), (SELECT COUNT(*) FROM entries), "
    "(SELECT COUNT(*) FROM toepassingen), (SELECT COUNT(*) FROM entries WHERE onzeker=1)"
).fetchone()
date_min, date_max = conn.execute(
    "SELECT MIN(datum_iso), MAX(datum_iso) FROM entries WHERE datum_iso IS NOT NULL"
).fetchone()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pagina's getranscribeerd", n_pages)
c2.metric("Ingrepen (entries)", n_entries)
c3.metric("Toepassingen (middel+dosering)", n_toep)
c4.metric("Onzeker gemarkeerd", f"{n_onzeker} ({n_onzeker/n_entries*100:.0f}%)")
st.caption(
    f"Periode: {date_min} t/m {date_max} · bron: visuele transcriptie van "
    f"`Data/Data Log Books/jaar <jaar>.pdf`, database op `{DB_PATH}`."
)

st.divider()
st.subheader("Doorzoeken")

jaren = [r[0] for r in conn.execute("SELECT DISTINCT jaar FROM pages ORDER BY jaar")]
col_a, col_b, col_c = st.columns([1, 1, 2])
jaar_filter = col_a.selectbox("Jaar", ["Alle jaren"] + jaren)
alleen_zeker = col_b.checkbox("Verberg onzekere entries", value=False)
middel_zoek = col_c.text_input("Zoek op middel (bijv. 'Ureum', 'Koper')", "")

query = """
SELECT p.jaar, p.bestand, p.pagina, e.datum_iso, e.datum_ruw, e.tijd, e.opmerkingen,
       e.onzeker, e.raw_transcript, e.id AS entry_id
FROM entries e JOIN pages p ON e.page_id = p.id
WHERE 1=1
"""
params: list = []
if jaar_filter != "Alle jaren":
    query += " AND p.jaar = ?"
    params.append(jaar_filter)
if alleen_zeker:
    query += " AND e.onzeker = 0"
if middel_zoek:
    query += " AND e.id IN (SELECT entry_id FROM toepassingen WHERE middel LIKE ?)"
    params.append(f"%{middel_zoek}%")
query += " ORDER BY p.jaar, e.datum_iso IS NULL, e.datum_iso, p.pagina"

rows = conn.execute(query, params).fetchall()
st.caption(f"{len(rows)} entries gevonden.")

toep_by_entry: dict[int, list[str]] = {}
if rows:
    ids = [r["entry_id"] for r in rows]
    placeholders = ",".join("?" * len(ids))
    for t in conn.execute(
        f"SELECT entry_id, middel, hoeveelheid FROM toepassingen WHERE entry_id IN ({placeholders}) ORDER BY entry_id, volgorde",
        ids,
    ):
        toep_by_entry.setdefault(t["entry_id"], []).append(f"{t['middel']} ({t['hoeveelheid']})")

display_rows = [
    {
        "Jaar": r["jaar"], "Datum": r["datum_iso"] or r["datum_ruw"], "Tijd": r["tijd"],
        "Toepassingen": ", ".join(toep_by_entry.get(r["entry_id"], [])) or "—",
        "Opmerkingen": r["opmerkingen"], "Onzeker": "ja" if r["onzeker"] else "",
        "Bron": f"{r['bestand']} p.{r['pagina']}",
    }
    for r in rows
]
st.dataframe(pd.DataFrame(display_rows), width="stretch", hide_index=True, height=420)

st.markdown("**Weer-context bij een entry**")
entries_met_datum = [(i, r) for i, r in enumerate(rows) if r["datum_iso"]]
if not entries_met_datum:
    st.caption("Geen van de getoonde entries heeft een (zekere) ISO-datum om weer bij op te zoeken.")
else:
    opties = {
        f"{r['datum_iso']} — {r['bestand']} p.{r['pagina']} ({', '.join(toep_by_entry.get(r['entry_id'], [])) or 'geen toepassing'})": i
        for i, r in entries_met_datum
    }
    gekozen_label = st.selectbox("Kies een entry om het weer er rondom te bekijken", list(opties.keys()))
    gekozen_idx = opties[gekozen_label]
    gekozen_entry = rows[gekozen_idx]
    render_weather_dialog_button(
        st, ctx.lat, ctx.lon, gekozen_entry["datum_iso"], key_suffix=f"logboek_{gekozen_entry['entry_id']}",
    )

with st.expander("Ruwe transcriptie bekijken (raw_transcript, incl. onzekerheden/doorhalingen)"):
    for r in rows[:50]:
        marker = "[onzeker] " if r["onzeker"] else ""
        st.text(f"{marker}[{r['bestand']} p.{r['pagina']}] {r['raw_transcript']}")
    if len(rows) > 50:
        st.caption(f"... en nog {len(rows) - 50} entries (gebruik het filter om te versmallen).")

st.divider()
st.subheader("Nieuwe ingreep loggen (sessie-only demo, NIET persistent in de database)")
st.caption(
    "Dit schrijft nog niet naar `orchard_logbook.db` — een echte 'nieuwe ingreep'-insert "
    "is vervolgwerk (ontwerp Sec B.4, episodisch geheugen bijwerken)."
)

if "logbook_entries" not in st.session_state:
    st.session_state["logbook_entries"] = []

with st.form("new_entry", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    entry_date = c1.date_input("Datum")
    middel = c2.text_input("Middel/ingreep")
    hoeveelheid = c3.text_input("Hoeveelheid/dosering")
    opmerking = st.text_area("Weer/opmerkingen")
    submitted = st.form_submit_button("Toevoegen")
    if submitted:
        st.session_state["logbook_entries"].append({
            "Datum": entry_date.isoformat(), "Middel/ingreep": middel,
            "Hoeveelheid": hoeveelheid, "Opmerkingen": opmerking,
        })

if st.session_state["logbook_entries"]:
    st.dataframe(pd.DataFrame(st.session_state["logbook_entries"]), width="stretch", hide_index=True)
