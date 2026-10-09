"""Instellingen -- boomgaard-locatie, ras en fenologische fase (design doc Sec B.9/G.15).

Deze invoervelden stonden vroeger rechtstreeks in de zijbalk van ELKE pagina (zie
`orchard_common.render_sidebar()`), maar namen daar zo veel ruimte in dat bijvoorbeeld de
"Chats"-lijst op Vraag de Adviseur bij een lager browservenster niet meer zichtbaar was
zonder te scrollen. De zijbalk toont nu alleen nog een compacte samenvatting + een link
hierheen; deze pagina bevat de daadwerkelijke invoervelden, ongewijzigd qua gedrag.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import (  # noqa: E402
    DEFAULT_LAT,
    DEFAULT_LON,
    KNOWN_VARIETIES,
    default_stage_for_month,
    load_settings,
    render_sidebar,
    save_settings,
)

import pandas as pd
import streamlit as st

from pipeline.ingest.orchard_qc import (  # noqa: E402
    ISSUE_LABELS,
    failing_chunks_table,
    per_document_table,
    qc_rag_index,
)
from pipeline.orchard_phenology_spec import PHENOLOGY_STAGES  # noqa: E402
from pipeline.orchard_tools import geocode_address  # noqa: E402

st.set_page_config(page_title="Instellingen", layout="wide")
st.title("Instellingen")
st.caption("Boomgaard-locatie, ras en fenologische fase -- gebruikt door alle andere pagina's.")

render_sidebar(st)

st.subheader("Locatie")
with st.expander("Locatie via adres zoeken", expanded=not st.session_state.get("orchard_address")):
    address_input = st.text_input(
        "Adres (straat, postcode, plaats)", value=st.session_state.get("orchard_address", ""),
        key="orchard_address_input",
    )
    if st.button("Zoek & onthoud coördinaten"):
        if not address_input.strip():
            st.warning("Vul eerst een adres in.")
        else:
            try:
                result = geocode_address(address_input.strip())
            except Exception as exc:
                result = None
                st.error(f"Geocoding mislukt: {exc}")
            if result is None:
                st.error("Geen resultaat gevonden voor dit adres.")
            else:
                st.session_state["orchard_lat"] = result["lat"]
                st.session_state["orchard_lon"] = result["lon"]
                st.session_state["orchard_address"] = address_input.strip()
                save_settings({
                    "lat": result["lat"], "lon": result["lon"], "address": address_input.strip(),
                })
                st.success(f"Gevonden: {result['display_name']} ({result['lat']:.4f}, {result['lon']:.4f}) — onthouden.")
                st.rerun()
    st.caption("Of vul hieronder handmatig breedte-/lengtegraad in.")

col_lat, col_lon = st.columns(2)
lat = col_lat.number_input("Breedtegraad (lat)", value=st.session_state.get("orchard_lat", DEFAULT_LAT), format="%.4f")
lon = col_lon.number_input("Lengtegraad (lon)", value=st.session_state.get("orchard_lon", DEFAULT_LON), format="%.4f")

st.subheader("Ras en fenologische fase")
col_variety, col_stage = st.columns(2)
variety = col_variety.selectbox(
    "Ras", KNOWN_VARIETIES,
    index=KNOWN_VARIETIES.index(st.session_state.get("orchard_variety", "Kordia")),
)
stage_default = st.session_state.get("orchard_stage", default_stage_for_month(date.today().month))
stage = col_stage.selectbox(
    "Huidige fenologische fase (handmatig, zie open vraag in ontwerp)",
    PHENOLOGY_STAGES, index=PHENOLOGY_STAGES.index(stage_default),
)

st.session_state["orchard_lat"] = lat
st.session_state["orchard_lon"] = lon
st.session_state["orchard_variety"] = variety
st.session_state["orchard_stage"] = stage

st.caption(
    "Fase-detectie is nu nog handmatig. Een echt bloeidatum-voorspelmodel o.b.v. "
    "koude-uren + graaddagen staat op de roadmap (design doc Deel E, stap 2)."
)
st.info(
    "Deze instellingen gelden voor alle pagina's in deze browser-sessie. Alleen de "
    "locatie (via adreszoeken) wordt ook blijvend onthouden na een herstart van de app; "
    "ras en fase moet je elke nieuwe sessie opnieuw controleren."
)

st.divider()
st.subheader("Kennisbank-kwaliteit")
st.caption(
    "Controleert ALLE chunks in de RAG-index op de regel: alleen complete, afgemaakte zinnen -- "
    "geen afgebroken zinnen, losse tekstfragmenten, tabellen/figuurtekst, OCR-ruis of "
    "pagina-/kolomresten. Chunks met oordeel 'fail' of 'bibliografie' horen niet in de index."
)
use_lm = st.checkbox(
    "Ook taalmodel-controle (GPT-2 per taal; langzamer, spoort door elkaar lopende kolommen op)",
    value=False, key="rag_qc_use_lm",
)
if st.button("Controleer RAG Chunks", type="primary", key="rag_qc_run"):
    with st.spinner("RAG-chunks controleren ..."):
        try:
            st.session_state["rag_qc_result"] = qc_rag_index(use_lm=use_lm)
            st.session_state["rag_qc_missing"] = st.session_state["rag_qc_result"] is None
        except ImportError as exc:
            st.session_state["rag_qc_result"] = None
            st.error(f"Ontbrekend pakket voor de controle: {exc}. Installeer `pyspellchecker` (zie requirements.txt).")

qc_result = st.session_state.get("rag_qc_result")
if st.session_state.get("rag_qc_missing") and qc_result is None:
    st.warning("Er is nog geen RAG-index gebouwd (draai `pipeline/ingest/build_orchard_rag.py`).")
if qc_result:
    summary = qc_result["summary"]
    counts = summary["counts"]
    cols = st.columns(5)
    cols[0].metric("Chunks", summary["n_chunks"])
    cols[1].metric("Goed (ok)", counts.get("ok", 0))
    cols[2].metric("Let op (warn)", counts.get("warn", 0))
    cols[3].metric("Afgekeurd (fail)", counts.get("fail", 0))
    cols[4].metric("Bibliografie", counts.get("references", 0))

    st.markdown("**Soort probleem** (een chunk kan er meerdere hebben)")
    st.dataframe(
        pd.DataFrame([{"Probleemtype": label, "Chunks": summary["issues"].get(key, 0)}
                      for key, label in ISSUE_LABELS.items()]),
        hide_index=True, width="content",
    )
    st.markdown("**Per document**")
    st.dataframe(pd.DataFrame(per_document_table(qc_result["docs"])), hide_index=True, width="stretch")

    problem_rows = failing_chunks_table(qc_result["docs"])
    st.markdown(f"**Chunks met een probleem ({len(problem_rows)})** -- begin en einde van de chunk zijn zichtbaar, "
                "zodat je afgebroken zinnen direct ziet")
    problems_df = pd.DataFrame(problem_rows)
    st.dataframe(problems_df, hide_index=True, width="stretch")

    download_cols = st.columns(2)
    download_cols[0].download_button(
        "Download rapport (.md)", qc_result["report"], file_name="orchard_rag_qc_rapport.md",
        mime="text/markdown", key="rag_qc_dl_md",
    )
    download_cols[1].download_button(
        "Download problemen (.csv)", problems_df.to_csv(index=False), file_name="orchard_rag_qc_problemen.csv",
        mime="text/csv", key="rag_qc_dl_csv",
    )
    with st.expander("Volledig rapport"):
        st.markdown(qc_result["report"])
