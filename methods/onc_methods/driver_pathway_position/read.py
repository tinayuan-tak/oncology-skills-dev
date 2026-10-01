"""driver_pathway_position.read — library entry for the driver-pathway-position card.

The deterministic, target-CONDITIONED, indication-CONDITIONED positional read the framework
previously lacked: "does the target sit IN / UPSTREAM of / DOWNSTREAM of the frequently-altered
driver pathway in THIS indication?" It is the CROSS-READ of three otherwise-disconnected sources:

  1. target pathway MEMBERSHIP — Sanchez-Vega per-gene oncogenic-pathway membership
     (`sanchez-vega-oncogenic-pathway-membership-per-gene-v1`, the F1 product); which of the 10
     canonical oncogenic signaling pathways is the target a curated member of, and OG/TSG role.
  2. indication pathway-alteration FREQUENCY — the per-(pathway x indication) alteration-frequency
     rollup (`oncogenic-pathway-alteration-per-indication-v1`), reused via the sibling
     oncogenic_pathway_alteration reader; which pathways are "frequently altered" (>= the reader's
     50% cohort bar) in THIS indication. These are the indication's driver pathways.
  3. SIGNOR directed EDGES — the per-gene mechanism network
     (`signor-mechanism-network-per-gene-v1`, reused via the signor_mechanism_network reader),
     intersected with the member set of the frequently-altered pathway(s) to place the target
     up/downstream of the driver pathway when it is not itself a member.

Reactome (`reactome-pathway-per-uniprot-v1`, fail-soft) distinguishes the honest null
`no_pathway_assignment` (the target has NO pathway annotation anywhere) from
`pathway_not_frequently_altered` (the target HAS a pathway, it just is not a frequently-altered one).

VERDICT-INERT at birth (card evidence_tier: inferred; rules fire only on the soft axis_fit channel;
NOT wired into any resolver) — exactly the pathway-node-leverage pattern. This reports POSITION, not
desirability: membership of a frequently-altered pathway is NOT leverage (the MARK2->YAP/TAZ
membership-lens verdict was rejected as overfit; see CROSS_EVIDENCE_INTEGRATION_ROADMAP.md WS3).
"""

from __future__ import annotations

from typing import Optional

METHOD_VERSION = "0.1.0"
DEFAULT_AWS_PROFILE = "cbg"

# The F1 per-gene oncogenic-pathway membership fact table (data-catalog derived product).
MEMBERSHIP_MANIFEST_ID = "sanchez-vega-oncogenic-pathway-membership-per-gene-v1"

# The 6 output classes (card summary_fields_vocabulary mirror). See the card YAML.
_CLASSES = (
    "member_of_frequently_altered_pathway",
    "downstream_of_frequently_altered_pathway",
    "upstream_of_frequently_altered_pathway",
    "pathway_not_frequently_altered",
    "no_pathway_assignment",
    "data_unavailable",
)


def _load_membership_table(membership_path: Optional[str] = None):
    """The full F1 per-gene membership table (gene_symbol, pathway, og_tsg_role, mutsig_driver).

    Small (~335 rows / 10 pathways), so loaded whole — the per-target slice AND the altered-pathway
    member set are both derived from it. Returns a pandas DataFrame, or None on a GENUINE product
    absence (manifest unregistered / NoSuchKey / 404 / missing local file) so the caller emits an
    honest `data_unavailable`. A TRANSIENT / creds / parse fault RE-RAISES (honest-loud absence
    discipline, #822): else every target silently reads as "no membership", indistinguishable from a
    real absence. `membership_path` overrides S3 (test fixtures / warm cache)."""
    import pandas as pd

    cols = ["gene_symbol", "pathway", "og_tsg_role", "mutsig_driver"]
    if membership_path is not None:
        try:
            return pd.read_parquet(membership_path, columns=cols)
        except (FileNotFoundError, OSError):
            return None
    try:
        from onc_methods.catalog_query.read import s3_uri_for

        uri = s3_uri_for(MEMBERSHIP_MANIFEST_ID)
    except Exception:  # absence-discipline: exempt -- resolves a LOCAL data-catalog manifest (not an S3 read); an unregistered/unreadable manifest => product not available => honest data_unavailable (the S3 read below enforces its own 404-vs-transient discipline)
        return None
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from onc_methods.target_id_sidecar import ensure_aws_profile

        ensure_aws_profile()
        tbl = pq.read_table(uri.replace("s3://", "", 1), filesystem=fs.S3FileSystem(), columns=cols)
    except Exception as e:  # noqa: BLE001
        from onc_methods.target_id_sidecar import is_definitively_absent

        if isinstance(e, FileNotFoundError) or is_definitively_absent(e):
            return None  # genuinely absent product -> honest data_unavailable
        raise  # transient / creds -> honest-loud
    return tbl.to_pandas()


def _frequently_altered(target: str, indication: str) -> dict:
    """The indication's oncogenic-pathway-alteration rollup (reuses the sibling reader). Returns the
    reader's dict; a module-level seam so tests can monkeypatch it without S3."""
    from onc_methods.oncogenic_pathway_alteration.read import read_oncogenic_pathway_alteration

    return read_oncogenic_pathway_alteration(target=target, indication=indication)


def _signor_summary(target: str) -> dict:
    """The target's SIGNOR mechanism-network summary (reuses the sibling reader). Module-level seam."""
    from onc_methods.signor_mechanism_network.read import read_target_summary

    return read_target_summary(target)


def _reactome_summary(target: str) -> dict:
    """The target's Reactome pathway-context summary (reuses the sibling reader). Fail-soft seam —
    used only to tell `no_pathway_assignment` (no annotation anywhere) from
    `pathway_not_frequently_altered`."""
    from onc_methods.reactome_pathway_context.read import read_target_summary

    return read_target_summary(target)


def _empty(note: str, **extra) -> dict:
    out = {
        "driver_pathway_position_class": "data_unavailable",
        "target_pathways": [],
        "frequently_altered_pathways": [],
        "member_altered_pathways": [],
        "upstream_altered_members": [],
        "downstream_altered_members": [],
        "n_upstream_altered_members": 0,
        "n_downstream_altered_members": 0,
        "target_og_tsg_role": None,
        "_data_note": note,
        "_method_version": METHOD_VERSION,
    }
    out.update(extra)
    return out


def _norm_pathway(p: str) -> str:
    """Canonicalize a Sanchez-Vega pathway token for SET comparison across the two products.

    The per-GENE membership product (F1) and the per-(pathway x indication) alteration-frequency
    product disagree on punctuation for the SAME 10 pathways: membership emits 'RTK-RAS' / 'TGF-Beta'
    (hyphen), the alteration rollup emits 'RTK RAS' / 'TGF Beta' (space). Compared verbatim, the
    intersection is empty and KRAS/RTK-RAS reads a false position. Normalize to uppercase with hyphens
    folded to spaces so the tokens match; DISPLAY fields keep each product's original spelling."""
    return (p or "").strip().upper().replace("-", " ")


def _partner_symbols(edges) -> set[str]:
    out: set[str] = set()
    for e in edges or []:
        s = (e.get("partner_gene_symbol") or "").strip().upper()
        if s:
            out.add(s)
    return out


def read_driver_pathway_position(
    target: Optional[str] = None,
    indication: Optional[str] = None,
    *,
    membership_path: Optional[str] = None,
    **_ignored,
) -> dict:
    """Return the driver-pathway-position card summary_fields for (target, indication).

    The positional read is indication-CONDITIONED (the frequently-altered set is per-indication), so
    both target and indication are required — absent either, the honest `data_unavailable`.
    """
    if not target or not indication:
        return _empty("target and indication both required (indication-conditioned positional read).")

    tgt = target.strip().upper()  # mmc3 / SIGNOR symbols are native HGNC uppercase

    # --- leg 1: target's Sanchez-Vega oncogenic-pathway membership (F1 per-gene product) ----------
    mdf = _load_membership_table(membership_path)
    if mdf is None:
        return _empty("Sanchez-Vega per-gene membership product unavailable.")
    gene_col = mdf["gene_symbol"].astype(str).str.upper()
    target_rows = mdf[gene_col == tgt]
    target_pathways = sorted(target_rows["pathway"].astype(str).unique().tolist())
    target_role = None
    if not target_rows.empty:
        roles = [r for r in target_rows["og_tsg_role"].astype(str).tolist() if r and r.lower() not in ("nan", "none")]
        target_role = roles[0] if roles else None

    # --- leg 2: the indication's frequently-altered oncogenic (driver) pathways -------------------
    alt = _frequently_altered(target, indication)
    if (alt or {}).get("oncogenic_pathway_class") == "data_unavailable":
        return _empty(
            f"indication {indication!r} not in the oncogenic-pathway-alteration product.",
            target_pathways=target_pathways,
            target_og_tsg_role=target_role,
        )
    frequently_altered = sorted(set(alt.get("frequently_altered_pathways") or []))
    freq_norm = {_norm_pathway(p) for p in frequently_altered}

    # membership of a frequently-altered pathway? (the KRAS x COADREAD / RTK-RAS case). Compare on the
    # normalized token (the two products punctuate the pathway names differently); report the
    # membership product's original spelling in member_altered_pathways.
    member_altered = sorted(p for p in target_pathways if _norm_pathway(p) in freq_norm)
    base = {
        "target_pathways": target_pathways,
        "frequently_altered_pathways": frequently_altered,
        "member_altered_pathways": member_altered,
        "target_og_tsg_role": target_role,
        "_method_version": METHOD_VERSION,
        "_source": "SIGNOR directed edges x Sanchez-Vega per-gene membership x per-indication alteration freq; verdict-inert positional read",
    }
    if member_altered:
        return _result("member_of_frequently_altered_pathway", base)

    # --- leg 3: SIGNOR directed position relative to members of the frequently-altered pathway ----
    altered_members: set[str] = set()
    if frequently_altered:
        amask = mdf["pathway"].astype(str).map(_norm_pathway).isin(freq_norm)
        altered_members = set(mdf[amask]["gene_symbol"].astype(str).str.upper().tolist()) - {tgt}

    up_members: list[str] = []  # altered-pathway members that REGULATE the target -> target is DOWNSTREAM
    down_members: list[str] = []  # altered-pathway members the target REGULATES    -> target is UPSTREAM
    if altered_members:
        sig = _signor_summary(tgt) or {}
        regulators = _partner_symbols(sig.get("upstream_regulators"))  # partner -> target
        effectors = _partner_symbols(sig.get("downstream_effectors"))  # target -> partner
        up_members = sorted(regulators & altered_members)
        down_members = sorted(effectors & altered_members)

    if up_members or down_members:
        # Target sits adjacent to the driver pathway. If it is BOTH up- and downstream (feedback /
        # embedded node), pick the direction with more supporting edges; tie -> downstream (being an
        # effector of an altered driver is the more decision-relevant framing). Both lists carried.
        if len(up_members) > len(down_members):
            cls = "downstream_of_frequently_altered_pathway"
        elif len(down_members) > len(up_members):
            cls = "upstream_of_frequently_altered_pathway"
        else:
            cls = "downstream_of_frequently_altered_pathway"
        return _result(
            cls,
            base,
            upstream_altered_members=up_members,
            downstream_altered_members=down_members,
        )

    # --- no membership, no directed link: has-a-pathway vs honest null ----------------------------
    has_pathway_assignment = bool(target_pathways)
    if not has_pathway_assignment:
        # Reactome fail-soft: only to tell "no annotation anywhere" from "has a (non-oncogenic) pathway".
        try:
            rx = _reactome_summary(tgt) or {}
            if int(rx.get("pathway_count") or 0) > 0:
                has_pathway_assignment = True
        except Exception:  # noqa: BLE001 — Reactome is a fail-soft discriminator; its absence must not fabricate a position
            pass

    cls = "pathway_not_frequently_altered" if has_pathway_assignment else "no_pathway_assignment"
    return _result(cls, base)


def _result(cls: str, base: dict, **extra) -> dict:
    assert cls in _CLASSES, f"unknown driver_pathway_position_class {cls!r}"
    out = {
        "driver_pathway_position_class": cls,
        "upstream_altered_members": [],
        "downstream_altered_members": [],
    }
    out.update(base)
    out.update(extra)
    out["n_upstream_altered_members"] = len(out.get("upstream_altered_members") or [])
    out["n_downstream_altered_members"] = len(out.get("downstream_altered_members") or [])
    return out
