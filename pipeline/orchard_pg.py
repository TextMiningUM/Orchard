"""Procedural graph (PG) of "what to do" knowledge -- port of Auto Pilot's ``build_pg.py`` (Lu et al. 2026 style).

Where the KG ([orchard_kg.py]) organises *what-is* knowledge, the PG holds *what-to-do*: ``(step, NEXT, step)`` edges
mined from the ordered procedure steps of the reasoning traces (``orchard_reasoning_traces.jsonl``, written by
``extract_orchard_oac.py`` from the problem cards -- and later also from LLM-extracted prose chunks), with the paper's
three edge attributes mapped onto what the Orchard cards already contain:

    condition  <- the card's OBSERVATION    (when does this transition apply)
    guidance   <- the card's WAAROM         (how / why to proceed)
    pitfalls   <- the card's SLECHTSTE REACTIE (what to avoid)

Fully deterministic (no LLM): step actions are canonicalised across traces by embedding similarity (greedy clustering,
cosine >= ``CANON_THRESH``), consecutive steps become NEXT edges, and identical transitions from several cards merge with
a support count -- a step order attested by several sources outweighs a one-off. Steps that differ in a number
("25 cm" vs "35 cm") or in polarity ("wel" vs "geen") NEVER merge: they embed almost identically but are
operationally opposite (Auto Pilot's channel/port-starboard guard, translated).

Built from the QC-passed chunks only (the traces are derived from them).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

CANON_THRESH = 0.893     # Auto Pilot's value; the distribution is printed at build time to check it
MAX_ATTR = 3             # attribute strings kept per edge (most frequent first)
MAX_SOURCES = 5
PG_FILENAME = "orchard_pg.json"

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_NEGATION_RE = re.compile(r"\b(geen|niet|nooit|zonder|niet meer|no|not|never|without)\b", re.I)


def merge_guard(action: str) -> tuple[frozenset, bool]:
    """Safety-critical tokens that must be IDENTICAL for two steps to merge: the numbers (doses, depths, dates) and
    the presence of a negation."""
    return frozenset(_NUMBER_RE.findall(action)), bool(_NEGATION_RE.search(action))


def collect_steps(trace_rows: list[dict]) -> list[dict]:
    """One record per usable trace: family, ordered steps, constraints, warnings, source."""
    out = []
    for r in trace_rows:
        t = r.get("trace") or {}
        steps = []
        for p in sorted(t.get("procedures") or [], key=lambda p: p.get("step", 0)):
            action = (p.get("action") or "").strip()
            if len(action) >= 5:
                steps.append({"action": action, "why": (p.get("why") or "").strip()})
        if len(steps) < 2:
            continue
        out.append({"family": r.get("family") or "general", "steps": steps,
                    "constraints": [c for c in t.get("constraints") or [] if c],
                    "warnings": [w for w in t.get("warnings") or [] if w],
                    "consequence": t.get("consequence", ""), "source_file": r.get("source_file", "")})
    return out


def canonicalize(actions: list[str], embeddings: np.ndarray, thresh: float = CANON_THRESH) -> tuple[list[int], list[str]]:
    """Greedy embedding clustering: action index -> canonical node index. Node label = most frequent exact action string
    in the cluster."""
    guards = [merge_guard(a) for a in actions]
    node_of = [-1] * len(actions)
    centroids: list[np.ndarray] = []
    members: list[list[int]] = []
    cluster_guard: list[tuple] = []
    for i, e in enumerate(embeddings):
        assigned = False
        if centroids:
            sims = np.vstack(centroids) @ e
            for j in np.argsort(-sims)[:5]:
                if float(sims[j]) < thresh:
                    break
                if cluster_guard[j] != guards[i]:
                    continue
                node_of[i] = int(j)
                members[j].append(i)
                centroids[j] = centroids[j] + (e - centroids[j]) / len(members[j])
                centroids[j] /= np.linalg.norm(centroids[j])
                assigned = True
                break
        if not assigned:
            node_of[i] = len(centroids)
            centroids.append(np.array(e, dtype=float))
            members.append([i])
            cluster_guard.append(guards[i])
    labels = [Counter(actions[i] for i in mem).most_common(1)[0][0] for mem in members]
    return node_of, labels


def _top(counter: Counter, n: int) -> list[str]:
    return [s for s, _ in counter.most_common(n)]


def build_pg(records: list[dict], embed_fn, thresh: float = CANON_THRESH) -> dict:
    """``embed_fn(list[str]) -> np.ndarray`` (normalised rows)."""
    all_actions = [s["action"] for r in records for s in r["steps"]]
    embeddings = embed_fn(all_actions)
    node_of, labels = canonicalize(all_actions, embeddings, thresh)

    node_families: dict[int, Counter] = defaultdict(Counter)
    node_count: Counter = Counter()
    edge_support: Counter = Counter()
    edge_attr = {name: defaultdict(Counter) for name in ("guidance", "condition", "pitfalls", "families", "sources")}
    start_count: Counter = Counter()
    end_count: Counter = Counter()

    idx = 0
    for r in records:
        ids = []
        for _ in r["steps"]:
            ids.append(node_of[idx])
            idx += 1
        for nid in ids:
            node_families[nid][r["family"]] += 1
            node_count[nid] += 1
        start_count[ids[0]] += 1
        end_count[ids[-1]] += 1
        for k in range(len(ids) - 1):
            u, v = ids[k], ids[k + 1]
            if u == v:
                continue  # canonicalisation collapsed two consecutive steps
            key = (u, v)
            edge_support[key] += 1
            why = r["steps"][k + 1]["why"] or r["steps"][0]["why"]
            if why:
                edge_attr["guidance"][key][why] += 1
            for c in r["constraints"]:
                edge_attr["condition"][key][c] += 1
            for w in r["warnings"]:
                edge_attr["pitfalls"][key][w] += 1
            edge_attr["families"][key][r["family"]] += 1
            edge_attr["sources"][key][r["source_file"]] += 1

    nodes = {f"pg_{nid:04d}": {"label": label, "n_occurrences": node_count[nid], "families": dict(node_families[nid]),
                               "n_starts": start_count.get(nid, 0), "n_ends": end_count.get(nid, 0)}
             for nid, label in enumerate(labels) if node_count[nid]}
    edges = [{"u": f"pg_{u:04d}", "rel": "NEXT", "v": f"pg_{v:04d}", "support": sup,
              "condition": _top(edge_attr["condition"][(u, v)], MAX_ATTR),
              "guidance": _top(edge_attr["guidance"][(u, v)], MAX_ATTR),
              "pitfalls": _top(edge_attr["pitfalls"][(u, v)], MAX_ATTR),
              "families": dict(edge_attr["families"][(u, v)]),
              "sources": _top(edge_attr["sources"][(u, v)], MAX_SOURCES)}
             for (u, v), sup in sorted(edge_support.items(), key=lambda kv: -kv[1])]
    return {
        "nodes": nodes, "edges": edges, "params": {"canon_thresh": thresh},
        "stats": {"n_traces": len(records), "n_steps": len(all_actions), "n_nodes": len(nodes), "n_edges": len(edges),
                  "merged_nodes": len(all_actions) - len(nodes),
                  "edges_with_support_gt1": sum(1 for e in edges if e["support"] > 1),
                  "families": dict(Counter(r["family"] for r in records).most_common())},
    }


def sample_path(pg: dict, family: str, max_len: int = 8) -> list[str]:
    """Greedy highest-support walk within one family, from its most-attested start node."""
    fam_edges = [e for e in pg["edges"] if family in e["families"]]
    starts = Counter({nid: n["n_starts"] * n["families"][family] for nid, n in pg["nodes"].items()
                      if family in n["families"] and n["n_starts"] > 0})
    if not fam_edges or not starts:
        return []
    cur = starts.most_common(1)[0][0]
    path, seen = [cur], {cur}
    for _ in range(max_len - 1):
        nxt = [e for e in fam_edges if e["u"] == cur and e["v"] not in seen]
        if not nxt:
            break
        cur = max(nxt, key=lambda e: e["support"])["v"]
        path.append(cur)
        seen.add(cur)
    return path


def next_steps(pg: dict, node_id: str, limit: int = 3) -> list[dict]:
    """Outgoing NEXT edges of a node, strongest first, with the target label and the edge attributes."""
    out = [e for e in pg["edges"] if e["u"] == node_id]
    return [{**e, "label": pg["nodes"][e["v"]]["label"]} for e in sorted(out, key=lambda e: -e["support"])[:limit]]


def nearest_node(pg: dict, query: str, embed_fn, min_sim: float = 0.6) -> tuple[str, float] | None:
    """The PG node closest to a free-text step description (e.g. what the grower says they just did)."""
    ids = list(pg["nodes"])
    labels = [pg["nodes"][i]["label"] for i in ids]
    sims = embed_fn(labels) @ embed_fn([query])[0]
    best = int(np.argmax(sims))
    return (ids[best], float(sims[best])) if sims[best] >= min_sim else None


def save_pg(pg: dict, cache_dir: Path) -> Path:
    path = Path(cache_dir) / PG_FILENAME
    path.write_text(json.dumps(pg, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_pg(cache_dir: Path | None = None) -> dict | None:
    if cache_dir is None:
        from core.paths import AgentPaths
        cache_dir = AgentPaths.orchard().cache_dir
    path = Path(cache_dir) / PG_FILENAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
