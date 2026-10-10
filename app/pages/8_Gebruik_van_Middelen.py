"""Gebruik van Middelen (design doc Sec A.6/B.4 vervolg, 2026-10-09): telt alle toepassingen
(middel + hoeveelheid) uit het logboek bij elkaar op, gecategoriseerd (gewasbescherming
schimmel/bacterie, insect/mijt, onkruid; meststof/bladvoeding; hulpstof; bestuiving; overig),
per week/maand/kwartaal/jaar -- en laat vanuit elk product/elke periode doorklikken naar de
onderliggende logboek-regels.

Alle canonicalisatie-/categoriseringslogica zit in `pipeline/orchard_middelen.py` (puur, los
getest) -- deze pagina doet alleen het ophalen/cachen/tonen. Puur lezend, geschikt voor de
publieke read-only pod-deployment.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import PATHS, render_sidebar  # noqa: E402

import pandas as pd
import plotly.express as px
import streamlit as st

from pipeline.orchard_middelen import (  # noqa: E402
    CATEGORY_LABELS,
    GRANULARITIES,
    ToepassingRecord,
    _ONZEKER_OVERIG,
    aggregate_middelen,
    build_toepassing_records,
)
from pipeline.orchard_logbook_calendar import load_calendar_data  # noqa: E402
from logbook_calendar_view import render_logbook_calendar  # noqa: E402

st.set_page_config(page_title="Gebruik van Middelen", layout="wide")
st.title("Gebruik van Middelen")
st.caption(
    "Telt alle toegepaste middelen (gewasbeschermingsmiddelen, meststoffen/bladvoeding) "
    "uit het logboek bij elkaar op, gecategoriseerd en per gekozen periode. Namen met "
    "verschillende schrijfwijzen/OCR-afwijkingen (bv. 'Zinc'/'Zink', 'Roval'/'Rovral') zijn "
    "samengevoegd tot één product -- zie onderaan welke namen bewust NIET geclassificeerd "
    "zijn (categorie 'overig') omdat de identiteit niet met zekerheid vaststond."
)

ctx = render_sidebar(st)

DB_PATH = PATHS.logbooks_dir / "orchard_logbook.db"
if not DB_PATH.exists():
    st.error(
        f"Database niet gevonden op `{DB_PATH}`. Bouw 'm eerst met:\n\n"
        "`.venv\\Scripts\\python.exe -m pipeline.ingest.build_logbook_database`"
    )
    st.stop()


@st.cache_data(show_spinner=False)
def _cached_records(db_path: str, mtime: float) -> list[ToepassingRecord]:
    # dubbel ingescande regels (2020 staat in twee scans) tellen één keer, anders lijkt het gebruik verdubbeld
    return build_toepassing_records(load_calendar_data(Path(db_path)).entries)


def _fetch_entry_rows(entry_ids: list[int]) -> pd.DataFrame:
    if not entry_ids:
        return pd.DataFrame()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(entry_ids))
    rows = conn.execute(
        f"""SELECT e.id AS entry_id, p.jaar, p.bestand, p.pagina, e.datum_iso, e.datum_ruw,
                   e.opmerkingen, e.onzeker
            FROM entries e JOIN pages p ON e.page_id = p.id
            WHERE e.id IN ({placeholders})
            ORDER BY e.datum_iso IS NULL, e.datum_iso DESC""",
        entry_ids,
    ).fetchall()
    toep_by_entry: dict[int, list[str]] = {}
    for t in conn.execute(
        f"SELECT entry_id, middel, hoeveelheid FROM toepassingen WHERE entry_id IN ({placeholders}) ORDER BY entry_id, volgorde",
        entry_ids,
    ):
        toep_by_entry.setdefault(t["entry_id"], []).append(f"{t['middel']} ({t['hoeveelheid']})")
    conn.close()
    return pd.DataFrame([
        {
            "Datum": r["datum_iso"] or r["datum_ruw"], "Jaar": r["jaar"],
            "Toepassingen": ", ".join(toep_by_entry.get(r["entry_id"], [])) or "—",
            "Opmerkingen": r["opmerkingen"], "Onzeker": "ja" if r["onzeker"] else "",
            "Bron": f"{r['bestand']} p.{r['pagina']}",
        }
        for r in rows
    ])


records = _cached_records(str(DB_PATH), DB_PATH.stat().st_mtime)
entry_ids_by_middel: dict[str, list[int]] = {}
for r in records:
    entry_ids_by_middel.setdefault(r.canonical_middel, []).append(r.entry_id)

render_logbook_calendar(DB_PATH)
st.divider()

col_a, col_b = st.columns([1, 3])
granulariteit = col_a.selectbox(
    "Periode", GRANULARITIES, index=GRANULARITIES.index("maand"),
    format_func=lambda g: {"week": "Per week", "maand": "Per maand", "kwartaal": "Per kwartaal", "jaar": "Per jaar"}[g],
)
categorie_filter = col_b.multiselect(
    "Categorie (laat leeg voor alles)", list(CATEGORY_LABELS), format_func=lambda c: CATEGORY_LABELS[c],
)

gefilterde_records = [r for r in records if not categorie_filter or r.category in categorie_filter]
rows = aggregate_middelen(gefilterde_records, granulariteit)
if not rows:
    st.info("Geen toepassingen gevonden voor deze filter.")
    st.stop()

df = pd.DataFrame(rows)
df["Categorie"] = df["categorie"].map(CATEGORY_LABELS)

st.subheader("Aantal toepassingen per periode (gestapeld per categorie)")
telling = df.groupby(["periode", "Categorie"], as_index=False)["aantal"].sum()
fig = px.bar(telling, x="periode", y="aantal", color="Categorie", barmode="stack")
fig.update_layout(height=420, xaxis_title="Periode", yaxis_title="Aantal toepassingen",
                   legend=dict(orientation="h", yanchor="bottom", y=1.02))
st.plotly_chart(fig, width="stretch")

st.subheader("Totale hoeveelheid per periode (vloeibaar / vast nooit gemengd)")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Vloeibaar (ml)**")
    vloeibaar = df[df["totaal_ml"] > 0].groupby(["periode", "Categorie"], as_index=False)["totaal_ml"].sum()
    if vloeibaar.empty:
        st.caption("Geen vloeibare producten in deze selectie.")
    else:
        fig_ml = px.bar(vloeibaar, x="periode", y="totaal_ml", color="Categorie", barmode="stack")
        fig_ml.update_layout(height=360, xaxis_title="Periode", yaxis_title="Totaal (ml)",
                              legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig_ml, width="stretch")
with c2:
    st.markdown("**Vast (gram)**")
    vast = df[df["totaal_g"] > 0].groupby(["periode", "Categorie"], as_index=False)["totaal_g"].sum()
    if vast.empty:
        st.caption("Geen vaste producten in deze selectie.")
    else:
        fig_g = px.bar(vast, x="periode", y="totaal_g", color="Categorie", barmode="stack")
        fig_g.update_layout(height=360, xaxis_title="Periode", yaxis_title="Totaal (gram)",
                             legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig_g, width="stretch")

st.divider()
st.subheader("Per-product detailtabel")
detail = df[["periode", "middel", "Categorie", "aantal", "totaal_ml", "totaal_g"]].rename(columns={
    "periode": "Periode", "middel": "Middel", "aantal": "Aantal toepassingen",
    "totaal_ml": "Totaal (ml)", "totaal_g": "Totaal (g)",
})
st.dataframe(
    detail.sort_values(["Periode", "Aantal toepassingen"], ascending=[True, False]),
    width="stretch", hide_index=True, height=380,
    column_config={
        "Totaal (ml)": st.column_config.NumberColumn(format="%.0f"),
        "Totaal (g)": st.column_config.NumberColumn(format="%.0f"),
    },
)

st.markdown("**Drill-down: onderliggende logboek-regels voor één product**")
alle_middelen = sorted(entry_ids_by_middel)
gekozen_middel = st.selectbox("Kies een product", alle_middelen)
if gekozen_middel:
    st.dataframe(
        _fetch_entry_rows(sorted(set(entry_ids_by_middel[gekozen_middel]))),
        width="stretch", hide_index=True,
    )

with st.expander("Welke namen zijn (bewust) niet geclassificeerd ('overig')?"):
    st.caption(
        "Deze ruwe productnamen kwamen in het logboek voor maar konden niet met voldoende "
        "zekerheid aan een bestaand product/categorie gekoppeld worden -- liever eerlijk "
        "'overig' dan een gok. Zie `pipeline/orchard_middelen.py` (`_ONZEKER_OVERIG`) voor "
        "de volledige, aanpasbare lijst."
    )
    st.write(sorted(_ONZEKER_OVERIG))
