"""glossary.py — the baked-in LEGIBILITY layer.

Builds a plain-language gloss for EVERY machine token the living document surfaces —
card_ids, rule_ids, verdict tokens, gates, measurement_types, and the status/severity/gap
enums. Most glosses are AUTO-DERIVED from content that already exists (a card's `question`,
a rule's signals, the measurement-type vocab descriptions); `glossary.yaml` supplies only
hand-authored enum glosses + overrides.

The living doc renders human labels via `_gloss()`; a coverage test walks the generated JSON
and fails the build if any surfaced token is not in the glossary — so "easy to understand"
cannot silently drift.

Exhaustive-by-construction: `build_glossary(graph, roots)` indexes the FULL token sets from
the graph (all cards/rules/verdicts/gates/measurement_types), so coverage is total and the
test verifies completeness against those same graph-derived sets.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


def _load_yaml(p: Path):
    try:
        with open(p) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def humanize(token: str) -> str:
    """Turn a kebab/snake machine token into a readable label."""
    if not token:
        return ""
    t = str(token).replace("_", " ").replace("-", " ").strip()
    # keep short all-caps acronyms as-is, else Title-ish (first word capitalized)
    return t[:1].upper() + t[1:] if t else t


def _first_sentence(text: str, limit: int = 200) -> str:
    text = " ".join(str(text or "").split())
    m = re.search(r"^(.{15,200}?[.?!])(\s|$)", text)
    return (m.group(1) if m else text[:limit]).strip()


def _measurement_type_descriptions(tc: Path) -> dict:
    """Pull any human description carried in the measurement_types registry."""
    d = _load_yaml(tc / "vocabularies" / "measurement_types.yaml")
    out = {}
    types = d.get("measurement_types") or d.get("types") or d
    if isinstance(types, dict):
        for k, v in types.items():
            if isinstance(v, dict):
                desc = v.get("description") or v.get("note") or v.get("what") or v.get("claim")
                if desc:
                    out[k] = _first_sentence(desc)
    elif isinstance(types, list):
        for v in types:
            if isinstance(v, dict) and v.get("id"):
                desc = v.get("description") or v.get("note") or v.get("what") or v.get("claim")
                if desc:
                    out[v["id"]] = _first_sentence(desc)
    return out


def _rule_plain(rule: dict) -> str:
    """Synthesize a plain-language sentence for a rule from the graph's parsed rule dict
    (card_id + field + condition + signals). Drift-free — reads what the graph already has."""
    field = rule.get("field") or "the label"
    cond = rule.get("condition") or {}
    cond_txt = ""
    if "equals" in cond:
        cond_txt = f"is `{cond['equals']}`"
    elif "in" in cond and isinstance(cond["in"], list):
        cond_txt = "is one of " + ", ".join(f"`{x}`" for x in cond["in"][:4])
    elif cond:
        k = next(iter(cond))
        cond_txt = f"{k} `{cond[k]}`"
    sigs = rule.get("signals") or {}
    sig_txt = ""
    if isinstance(sigs, dict) and sigs:
        uniq = sorted({str(v) for v in sigs.values()})
        sig_txt = " -> signals " + "/".join(uniq)
    killer = " (a KILLER — vetoes the program)" if rule.get("is_killer") else ""
    card = rule.get("card_id") or "a card"
    return f"When {card}'s {field} {cond_txt}{sig_txt}{killer}.".replace("  ", " ")


def build_glossary(graph: dict, roots: dict) -> dict:
    """Return {kind: {token: {label, plain_english, source}}} covering every token the doc
    surfaces. kind ∈ {card, rule, verdict, gate, measurement_type, severity, gap_type,
    status, component_type}."""
    tc = Path(roots.get("target_contracts") or graph.get("roots", {}).get("target_contracts") or ".")
    here = Path(__file__).resolve().parent
    hand = _load_yaml(here / "glossary.yaml")

    g: dict[str, dict] = {
        k: {}
        for k in (
            "card",
            "rule",
            "verdict",
            "gate",
            "measurement_type",
            "severity",
            "gap_type",
            "status",
            "component_type",
        )
    }

    # ---- hand-authored enums (severity / gap_type / status / component_type / gate seeds)
    for kind in ("severity", "gap_type", "status", "component_type", "gate"):
        for token, rec in (hand.get(kind) or {}).items():
            g[kind][token] = {
                "label": rec.get("label") or humanize(token),
                "plain_english": rec.get("plain_english") or "",
                "source": "glossary.yaml",
            }

    # ---- cards: gloss from the card `question`
    for cid, c in (graph.get("cards") or {}).items():
        q = c.get("question")
        g["card"][cid] = {
            "label": humanize(cid),
            "plain_english": _first_sentence(q) if q else humanize(cid),
            "source": "card.question" if q else "humanize",
        }

    # ---- measurement_types: from registry description, else humanize
    mt_desc = _measurement_type_descriptions(tc)
    mtypes = set()
    for c in (graph.get("cards") or {}).values():
        if c.get("measurement_type"):
            mtypes.add(c["measurement_type"])
    for mt in mtypes:
        g["measurement_type"][mt] = {
            "label": humanize(mt),
            "plain_english": mt_desc.get(mt, humanize(mt)),
            "source": "measurement_types.yaml" if mt in mt_desc else "humanize",
        }

    # ---- gates + verdicts: from resolvers
    for gate, r in (graph.get("resolvers") or {}).items():
        if gate not in g["gate"]:
            g["gate"][gate] = {"label": humanize(gate), "plain_english": humanize(gate), "source": "humanize"}
        for v in r.get("verdicts") or []:
            tok = v.get("verdict")
            if tok and tok not in g["verdict"]:
                g["verdict"][tok] = {"label": humanize(tok), "plain_english": _verdict_plain(tok), "source": "derived"}

    # ---- rules: synthesize from the graph's parsed rule dicts
    for c in (graph.get("cards") or {}).values():
        for rule in c.get("rules") or []:
            rid = rule.get("rule_id")
            if rid and rid not in g["rule"]:
                g["rule"][rid] = {"label": humanize(rid), "plain_english": _rule_plain(rule), "source": "rule"}

    # ---- overrides last (hand-authored verdict/measurement_type/card win over derived)
    for kind in ("verdict", "measurement_type", "card", "rule"):
        for token, rec in (hand.get(kind) or {}).items():
            g[kind][token] = {
                "label": rec.get("label") or humanize(token),
                "plain_english": rec.get("plain_english") or "",
                "source": "glossary.yaml",
            }
    return g


_VERDICT_HINTS = {
    "killer": "A kill — vetoes the program on this axis.",
    "veto": "A veto on this axis.",
    "non_dependent": "Not a dependency — vetoes the dependency axis.",
    "insufficient": "Not enough data to call — honest abstention.",
    "concordant": "Multiple orthogonal assays agree.",
    "selective": "A selective (context-restricted) positive signal.",
    "confirmed": "Independently confirmed positive.",
    "partner_conditional": "Required only in a partner-deficient subset (synthetic-lethal rescue).",
    "buffered": "A pooled negative rescued by a buffering explanation.",
    "discordant": "Orthogonal assays disagree.",
}


def _verdict_plain(token: str) -> str:
    t = str(token).lower()
    for key, hint in _VERDICT_HINTS.items():
        if key in t:
            return hint
    return humanize(token)
