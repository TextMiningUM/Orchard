"""Sectie "Middel opzoeken" (ontwerp G.31): het officiele Ctgb-voorschrift voor kers + het eigen gebruik uit het logboek + de praktijkcontrole.
Gedeeld door de pagina Gebruik van Middelen. De getallen van het voorschrift komen letterlijk uit de Ctgb-API (``pipeline/orchard_ctgb.py``) en worden hier
alleen getoond; het taalmodel is er niet bij betrokken."""
from __future__ import annotations

from collections import Counter
from datetime import date

import pandas as pd
import streamlit as st

from pipeline.orchard_ctgb import CtgbUnavailable, format_card, lookup, use_rows
from pipeline.orchard_middel_lookup import PRACTICE_CAVEAT, build_advies
from pipeline.orchard_middelen import canonicalize_middel
from pipeline.orchard_patterns import LogEntry

PPP_CATEGORIES = {"fungicide_bactericide", "insecticide_acaricide", "herbicide"}
PICK_PLACEHOLDER = "(kies een middel uit je logboek)"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _cached_lookup(query: str):
    try:
        return lookup(query), None
    except CtgbUnavailable as exc:
        return None, str(exc)


def own_plant_protection_products(entries: list[LogEntry]) -> list[str]:
    """De gewasbeschermingsmiddelen uit het eigen logboek, meest gebruikte eerst (meststoffen vallen niet onder het Ctgb)."""
    counts: Counter = Counter()
    for e in entries:
        for raw, _h in e.toepassingen:
            name, cat = canonicalize_middel(raw)
            if cat in PPP_CATEGORIES:
                counts[name] += 1
    return [n for n, _ in counts.most_common()]


def render_ctgb_lookup(entries: list[LogEntry], today: date | None = None) -> None:
    today = today or date.today()
    st.subheader("Middel opzoeken: Ctgb-voorschrift voor kers + je eigen gebruik")
    st.caption("Kies een middel uit je logboek of typ een merknaam. Je ziet het **officiële Ctgb-voorschrift voor kers** (maximale dosis, aantal toepassingen, interval, "
               "veiligheidstermijn, periode, opmerkingen en links naar de gebruiksaanwijzing), wat je zelf met dit middel deed volgens je logboek, en waar dat "
               "afwijkt van het voorschrift. De getallen komen letterlijk uit de Ctgb-databank (gratis open API) en zijn geen advies.")
    own = own_plant_protection_products(entries)
    c1, c2, c3 = st.columns([2, 2, 1])
    pick = c1.selectbox("Middel uit je logboek", [PICK_PLACEHOLDER, *own], key="ctgb_pick")
    typed = c2.text_input("Of typ een merknaam", key="ctgb_typed", placeholder="bijv. Syllit")
    query = typed.strip() or ("" if pick == PICK_PLACEHOLDER else pick)
    if c3.button("Zoek op", key="ctgb_go", disabled=not query, width="stretch"):
        st.session_state["ctgb_query"] = query
    q = st.session_state.get("ctgb_query")
    if not q:
        return

    with st.spinner(f"'{q}' opzoeken in de Ctgb-databank..."):
        lk, error = _cached_lookup(q)
    advies = build_advies(entries, q, today, lk, error)
    st.markdown(f"#### Resultaat voor '{q}'")
    if error:
        st.error(f"De Ctgb-databank is nu niet te bereiken ({error}). Er wordt geen dosering of toelatingsstatus getoond zonder die bron; probeer het later nog eens.")
    elif not lk.products:
        st.info(format_card(lk))
    else:
        rows = use_rows(lk)
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if not lk.valid_cherry_uses:
            st.warning("Er is geen geldig gebruiksvoorschrift voor kers gevonden voor dit middel; controleer in de Ctgb-databank of het nog gebruikt mag worden.")
        with st.expander("Volledig Ctgb-voorschrift (opmerkingen, doelorganismen, documenten)", expanded=False):
            st.markdown(format_card(lk))
        for n in lk.notes:
            st.caption(n)

    st.markdown("#### Je eigen gebruik (uit je logboek)")
    h = advies.history
    if h is None:
        st.info(f"Geen toepassingen van '{q}' gevonden in je logboek (meststoffen en bladvoeding staan er wel in, maar vallen niet onder het Ctgb).")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toepassingen", h.applications)
    m2.metric("Jaren gebruikt", len(h.per_year))
    m3.metric("Laatst gebruikt", h.last.isoformat())
    m4.metric("Rond deze tijd", f"{h.near_ref_years} van {h.covered_years} jaar" if h.covered_years else "n.v.t.", help="Toepassing binnen ±15 dagen van vandaag")
    st.bar_chart(pd.Series({str(y): c for y, c in h.per_year}, name="Toepassingen per jaar"))
    if h.purposes:
        st.caption("Doel volgens je opmerkingen: " + ", ".join(f"{p} ({n} jaar)" for p, n in h.purposes))
    if advies.flags:
        st.warning("**Eigen praktijk tegenover het Ctgb-voorschrift**\n\n" + "\n".join(f"- {f.text}" for f in advies.flags) + f"\n\n*{PRACTICE_CAVEAT}*")
    elif advies.compare_note:
        (st.success if lk is not None and lk.valid_cherry_uses else st.info)(advies.compare_note)
