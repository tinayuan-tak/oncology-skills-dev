"""literature_retrieval — multi-source grounding + PMID verification for the literature lane.

Best-effort, stdlib-only (urllib) helpers wired into `literature_synthesis`:

  * ``europe_pmc_retrieve`` / ``pubtator3_retrieve`` — return a compact GROUNDING CORPUS string
    (PMID + citation + snippet per paper) for a (target, indication, lens). LENS-AWARE + VARIED: the
    query is SPECIALISED to what the skill's lens measures (its ``axis_labels`` + a curated per-lens
    term map) and issued as VARIATIONS — a broad gene∧disease query AND a lens-specific query — whose
    hits are merged/deduped by PMID. So each subskill's grounding is specific to its own question
    (selectivity → therapeutic window / normal-tissue; dependency → CRISPR / essential; safety →
    loss-of-function / haploinsufficiency; …), not one generic string.
  * ``default_retrieve`` — the RECOMMENDED retriever: Europe PMC first, then PubTator3 on failure, so a
    transient outage of one source no longer collapses grounding to internal-knowledge/unverified.
  * ``verify_citations`` — reconcile every citation's ``verified`` flag against GROUND TRUTH (Europe PMC,
    with an NCBI E-utilities fallback), recording a ``_verification`` summary.

BEST-EFFORT / NEVER-BREAK: every network path has a short timeout (+ one retry) and degrades on ANY
failure (no network, DNS, non-200, parse error) — retrieval returns None (→ internal-knowledge mode),
verification leaves the model's flags and marks ``_verification: {"status": "unavailable"}``. The
literature lane itself is already optional + verdict-inert, so a retrieval/verification outage can never
touch the spine.
"""
from __future__ import annotations
import json
import re
import urllib.parse
import urllib.request
from typing import Optional

_EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PUBTATOR_SEARCH = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/"
_NCBI_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_UA = {"User-Agent": "onc-compbio-skills-literature-lane/1.0 (mailto:noreply@takeda.com)"}

# Minimal OncoTree-ish code → readable phrase for the query (best-effort; unknown codes fall back to the
# raw code + "cancer", which free-text still ranks usefully). Kept tiny + local on purpose — this is a
# query hint, not a canonical vocabulary.
_INDICATION_PHRASE = {
    "COADREAD": "colorectal cancer", "COAD": "colon cancer", "READ": "rectal cancer",
    "LUAD": "lung adenocarcinoma", "LUSC": "lung squamous carcinoma", "NSCLC": "non-small cell lung cancer",
    "BRCA": "breast cancer", "PAAD": "pancreatic cancer", "PDAC": "pancreatic ductal adenocarcinoma",
    "STAD": "gastric cancer", "OV": "ovarian cancer", "PRAD": "prostate cancer", "UCEC": "endometrial cancer",
    "SCLC": "small cell lung cancer", "HNSC": "head and neck squamous carcinoma", "SKCM": "melanoma",
    "GBM": "glioblastoma", "AML": "acute myeloid leukemia", "BLCA": "bladder cancer",
    # Added 2026-09-04: common OncoTree/TCGA codes that were falling back to the weak "<CODE> cancer"
    # free-text (observed live: FGFR2/CHOL literature grounding returned no PMID-bearing hits →
    # internal-knowledge mode). All are standard, well-established code→disease names.
    "CHOL": "cholangiocarcinoma", "LIHC": "hepatocellular carcinoma", "ESCA": "esophageal cancer",
    "KIRC": "clear cell renal cell carcinoma", "KIRP": "papillary renal cell carcinoma",
    "THCA": "thyroid carcinoma", "CESC": "cervical cancer", "MESO": "mesothelioma",
    "SARC": "sarcoma", "ACC": "adrenocortical carcinoma", "UVM": "uveal melanoma",
    "DLBC": "diffuse large B-cell lymphoma", "LAML": "acute myeloid leukemia",
    "MB": "medulloblastoma", "NBL": "neuroblastoma", "GIST": "gastrointestinal stromal tumor",
    "ESAD": "esophageal adenocarcinoma", "EGC": "esophagogastric cancer",
}

# Per-subskill query SPECIFICITY: curated domain terms keyed by LensConfig.name, ADDED to the lens's own
# axis_labels (which the skill already declares). Each subskill therefore queries the literature for what
# IT measures — not a generic gene∧disease string. Small + reviewable; unknown lenses fall back to
# axis_labels only (or bare gene∧disease when no lens is supplied).
_LENS_QUERY_TERMS = {
    "tumor-selectivity":          ["tumor versus normal expression", "therapeutic window",
                                   "normal tissue expression", "immunohistochemistry"],
    "tumor-presence":             ["immunohistochemistry", "protein abundance mass spectrometry",
                                   "single-cell RNA sequencing", "tumor microenvironment stromal expression",
                                   "RNA protein correlation", "cell of origin", "overexpression",
                                   "protein abundance"],
    "functional-requirement":     ["genetic dependency", "essential gene", "CRISPR knockout",
                                   "RNA interference", "oncogene addiction", "selective dependency"],
    "on-target-safety-liability": ["loss-of-function intolerance", "haploinsufficiency",
                                   "knockout phenotype", "germline"],
    "mechanism-and-pharmacology": ["signaling pathway", "mechanism of action", "signal transduction",
                                   "pathway activation", "pharmacodynamic biomarker", "mechanism of resistance",
                                   "driver pathway", "molecular glue degrader"],
    "genomic-alteration-profile": ["somatic mutation", "copy number amplification", "gene fusion",
                                   "driver mutation"],
    "surface-modality-fit":       ["cell surface protein", "cell surface proteomics", "antibody-drug conjugate",
                                    "receptor internalization", "shed antigen", "bispecific T-cell engager",
                                    "antigen escape"],
    "tractability-small-molecule": ["small molecule inhibitor", "druggability", "direct target engagement",
                                    "tool compound", "covalent inhibitor", "allosteric pocket"],
    # Front-loaded so the highest-value TRAP discriminators (TMB/MSI/subtype confound, patient-selection,
    # combination rationale) lead — a co-mutation / mutual-exclusivity ASSOCIATION over-calls a biological /
    # patient-selection relationship (the burden/lineage confound). The base gene∧disease query supplies
    # co-mutation recall; the precision query needs the confounder + actionability terms.
    "differentiation-landscape":  ["co-occurrence mutually exclusive mutations", "tumor mutational burden",
                                   "microsatellite instability", "patient stratification biomarker",
                                   "combination therapy rationale", "co-mutation", "mutual exclusivity",
                                   "molecular subtype"],
    # Front-loaded so the highest-value SPATIAL/FUNCTIONAL discriminators survive the _lens_terms cap
    # (max_terms=5: the axis_label "CD8 / immune infiltration" + the first 4 here). The base gene∧disease
    # query already supplies TIL/CD8 recall; the precision query needs the exclusion / phenotype /
    # exhaustion / spatial terms that separate an INFLAMED from an EXCLUDED/DESERT/EXHAUSTED read.
    "immune-context":             ["immune exclusion", "immune phenotype inflamed excluded desert",
                                   "T-cell exhaustion", "multiplex immunohistochemistry spatial",
                                   "immune checkpoint response", "tertiary lymphoid structure",
                                   "T-cell exclusion stroma", "tumor-infiltrating lymphocytes", "CD8 T cell"],
    # Front-loaded so the highest-value RELATIONAL-TRAP discriminators (statistical relational signal
    # OVER-CALLS a druggable/portable SL) lead: a curated SynLethDB edge / DepMap co-essentiality delta
    # / paralog GI / drug-anchor screen delta can be a cell-line artifact, a pan-essential co-fitness, or
    # a non-replicating single-screen hit — the precision query needs the SL-reproducibility, the
    # KO-vs-inhibition, and the clinical-validation (PARP/BRCA, WRN/MSI) terms, not a generic string. This
    # lens declares FIVE axis_labels (SL/CODEP/COMBO/SYNERGY/RESISTANCE), which alone would fill the default
    # 5-term cap — so it gets a per-lens cap bump (_LENS_MAX_TERMS below) to let the first ~4 discriminators
    # through alongside the axis labels.
    "combination-and-vulnerability": ["synthetic lethality", "drug combination therapy",
                                      "resistance mechanism",
                                      "genetic knockout versus pharmacological inhibition",
                                      "paralog buffering", "DepMap co-dependency screen",
                                      "PARP inhibitor BRCA", "WRN helicase microsatellite instability",
                                      "context dependence reproducibility"],
    # synthetic-lethal-partners is the STANDALONE curated-SynLethDB SL skill (single axis SL). The trap is a
    # CURATED SL edge OVER-CALLING a validated, portable, druggable SL — so the precision query front-loads the
    # SL-VALIDATION / reproducibility / evidence-tier / KO-vs-inhibition discriminators (the base gene query
    # supplies recall). One axis label → per-lens cap bump below.
    "synthetic-lethal-partners":  ["synthetic lethality validated", "synthetic lethal partner",
                                   "synthetic lethality reproducibility context dependence",
                                   "genetic knockout versus pharmacological inhibition",
                                   "PARP inhibitor BRCA", "WRN helicase microsatellite instability",
                                   "computational prediction synthetic lethality"],
    # combinatorial-dependency is the STANDALONE measured DepMap ParalogV2 paralog dual-KO skill (single axis
    # CODEP). The trap is a MEASURED GI OVER-CALLING a portable druggable SL, WHILE single-context screens
    # UNDER-call buffered paralogs — so the query front-loads the paralog-buffering / dual-KO / validation /
    # KO-vs-inhibition discriminators. One axis label → per-lens cap bump below.
    "combinatorial-dependency":   ["paralog synthetic lethality", "paralog buffering essentiality",
                                   "paralog dual knockout CRISPR screen",
                                   "SMARCA4 SMARCA2 synthetic lethal", "ARID1A ARID1B synthetic lethal",
                                   "genetic knockout versus pharmacological inhibition",
                                   "synthetic lethality context dependence reproducibility"],
    # Front-loaded so the highest-value FIDELITY/ATTRIBUTION discriminators lead: a model-availability /
    # genotype-matched / PDX-responder read OVER-CALLS faithful, on-target, adequately-powered preclinical
    # validatability. The base gene∧disease query supplies model recall; the precision query needs the
    # PDX/organoid FIDELITY + DRIFT + PDXE-attribution + co-clinical + cancer-model-fidelity discriminators
    # that separate a validated preclinical model precedent from an availability-only / small-cohort /
    # off-target-PDX over-call. The lens declares FOUR axis_labels (MODEL/GENOTYPE/ORGANOID/PDX), which alone
    # would leave only ~1 curated term under the default 5-cap — so it gets a per-lens cap bump (below).
    "translational-readiness":    ["patient-derived xenograft fidelity", "tumor organoid model",
                                   "PDX drug response", "preclinical model genomic fidelity",
                                   "patient-derived model drift", "co-clinical trial",
                                   "cancer model fidelity"],
    # target-intrinsic is the indication-INDEPENDENT dossier; the trap is a PREDICTION / HOMOLOGY
    # annotation OVER-CALLING an experimentally-confirmed actionable intrinsic property (an AlphaFold /
    # computational druggable pocket over-calling a co-crystal-confirmed pocket; a family/surfaceome-class
    # membership by homology over-calling function/druggability — a pseudokinase is catalytically dead; a
    # population-genetic / OT-composite meta-score read as actionability). The precision query front-loads
    # the EXPERIMENTAL-vs-PREDICTED structural discriminators. Only 2 axis_labels (modality routing /
    # tractability precedent), so the default 5-term cap admits the first ~3 curated terms — ordered
    # sharpest-first (co-crystal / fragment screen / AlphaFold) — no _LENS_MAX_TERMS bump needed.
    "target-intrinsic":           ["experimental co-crystal structure",
                                    "druggable pocket fragment screen",
                                    "AlphaFold predicted structure",
                                    "pseudokinase catalytically dead",
                                    "protein family homology",
                                    "subcellular localization proteomics",
                                    "gnomAD loss-of-function constraint"],
    # Front-loaded so the highest-value cis-CAUSALITY discriminators lead: the base gene∧disease query
    # supplies cis/CN-expression recall; the precision query needs the amplicon driver-vs-passenger,
    # focal-amplitude, protein-dosage-buffering, CIMP-lineage, and purity-confound terms that separate a
    # CAUSAL cis-driver / targeted silencing from a co-amplified passenger / dosage-buffered / CIMP-confounded
    # correlation. The lens declares 4 axis_labels, so a per-lens _LENS_MAX_TERMS bump (below) is needed to let
    # ~5 of these curated discriminators survive the default max_terms=5 cap.
    "cis-feature-coherence":      ["copy-number-driven expression", "amplicon driver versus passenger",
                                   "focal amplification", "promoter methylation silencing",
                                   "CpG island methylator phenotype", "oncogene addiction dosage",
                                   "protein abundance copy number", "tumor purity confound"],
    # target-archetype is the META cross-skill signature LANDSCAPE companion: it grounds the DOMINANT
    # phenotype_mixture component + the top nearest_analogs ANALOGY ("does the literature support that target X
    # is phenotype-P and most like reference-Y?"). Its 5 axis_labels (PHENOTYPE/ANALOG/PRECEDENT/NOVELTY/
    # READINESS) are FRAMEWORK-internal jargon that alone would fill the default 5-cap and admit ZERO curated
    # terms — so this lens gets a _LENS_MAX_TERMS bump (below) and these front-loaded PHENOTYPE + ANALOGY
    # discriminators (target family/class, surface-antigen vs driver vs TSG phenotype, analogy/"most similar
    # to" reasoning, drug-target archetype) carry the precision query. often INDICATION-INDEPENDENT →
    # None-indication → _indication_phrase→"cancer" (like target-intrinsic).
    "target-archetype":           ["drug target class", "oncogene tumor suppressor classification",
                                   "cell surface antigen", "driver gene amplification mutation",
                                   "oncogene addiction", "target druggability class",
                                   "antibody-drug conjugate target", "molecular subtype classification"],
}


def _indication_phrase(indication: Optional[str]) -> str:
    if not indication:
        return "cancer"
    return _INDICATION_PHRASE.get(indication.upper(), f"{indication} cancer")


# Per-lens override of the term cap. Default is 5; a lens whose axis_labels alone would fill (or overflow)
# the default — leaving no room for its curated discriminators — gets a bump here. combination-and-
# vulnerability declares FIVE axis_labels (SL/CODEP/COMBO/SYNERGY/RESISTANCE), so a cap of 5 would admit
# ZERO curated terms; 9 lets the first ~4 discriminators (synthetic lethality / drug combination /
# resistance mechanism / KO-vs-inhibition) through. Surgical: every other lens keeps the default cap →
# byte-identical query strings. cis-feature-coherence declares FOUR axis_labels
# (CIS_DOSAGE/SILENCING/EXPR_DEP/CONJOINT), so a cap of 5 admits only ONE curated term; 9 lets the first ~5
# discriminators (amplicon driver-vs-passenger / focal amplification / CpG island methylator phenotype /
# oncogene addiction dosage / protein abundance copy number) through.
_LENS_MAX_TERMS = {"combination-and-vulnerability": 9, "cis-feature-coherence": 9,
                   # translational-readiness declares FOUR axis_labels (MODEL/GENOTYPE/ORGANOID/PDX), so the
                   # default 5-cap admits only ONE curated term; 8 lets the first ~4 discriminators (PDX
                   # fidelity / tumor organoid model / PDX drug response / preclinical model genomic fidelity)
                   # through alongside the axis labels. Surgical: every other lens keeps the default cap.
                   "translational-readiness": 8,
                   # target-archetype declares FIVE (framework-internal) axis_labels, so the default 5-cap
                   # admits ZERO curated terms; 10 lets the first ~5 phenotype/analogy discriminators (drug
                   # target class / oncogene-vs-TSG / cell surface antigen / driver amp-vs-mutation / oncogene
                   # addiction) through alongside the axis labels. Surgical: every other lens keeps the default.
                   "target-archetype": 10,
                   # synthetic-lethal-partners + combinatorial-dependency each declare only ONE axis_label
                   # (SL / CODEP), so the default 5-cap would admit 4 curated terms; 7 lets ~6 of the
                   # SL-validation / reproducibility / paralog-buffering / KO-vs-inhibition discriminators
                   # through alongside the single axis label. Surgical: every other lens keeps the default cap.
                   "synthetic-lethal-partners": 7, "combinatorial-dependency": 7}


def _lens_terms(lens, *, max_terms: int = 5) -> list[str]:
    """The lens-specific query terms: the LensConfig's own axis_labels (what the skill declares it
    measures) PLUS the curated per-lens supplement. Deduped (case-insensitive), capped. [] when no lens.
    The cap is the per-lens _LENS_MAX_TERMS override when present, else `max_terms`."""
    if lens is None:
        return []
    cap = _LENS_MAX_TERMS.get(getattr(lens, "name", ""), max_terms)
    seen: set = set()
    out: list[str] = []
    def _add(t):
        t = (t or "").strip()
        k = t.lower()
        if t and k not in seen:
            seen.add(k)
            out.append(t)
    for v in (getattr(lens, "axis_labels", {}) or {}).values():
        _add(v)
    for t in _LENS_QUERY_TERMS.get(getattr(lens, "name", ""), []):
        _add(t)
    return out[:cap]


def _build_query_variations(target: str, indication: Optional[str], lens) -> list[str]:
    """Ordered query VARIATIONS for (target, indication, lens): a broad gene∧disease query for recall,
    then a lens-SPECIFIC query (gene ∧ disease ∧ (term1 OR term2 …)) for precision. Both AND/OR/quoted
    syntax is accepted by Europe PMC and PubTator3 free-text search. Deduped."""
    phrase = _indication_phrase(indication)
    base = f'("{target}") AND ("{phrase}")'
    variations = [base]
    terms = _lens_terms(lens)
    if terms:
        or_clause = " OR ".join(f'"{t}"' for t in terms)
        variations.append(f'{base} AND ({or_clause})')
    return variations


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _clean_pubtator_hl(s: str) -> str:
    """PubTator3 `text_hl` carries bioconcept markup — highlighted spans as ``@@@matched text@@@`` and
    inline entity tokens like ``@DISEASE_Colorectal_Neoplasms`` / ``@DISEASE_MESH:D015179``. Unwrap the
    spans (keep the human text), drop the entity tokens + any HTML tags, and collapse whitespace so the
    grounding snippet reads as prose."""
    s = re.sub(r"@@@(.*?)@@@", r"\1", s or "")        # unwrap highlighted spans → keep inner text
    s = re.sub(r"@[A-Za-z]+_\S+", "", s)              # drop @TYPE_Identifier bioconcept tokens
    return re.sub(r"\s+", " ", _strip_tags(s)).strip()


def _first_author(authors) -> str:
    """First-author surname-ish from a list (str or {name}) or an authorString."""
    if isinstance(authors, list) and authors:
        a = authors[0]
        if isinstance(a, dict):
            a = a.get("name") or a.get("fullName") or a.get("lastName") or ""
        a = str(a).strip()
        return a or "?"
    if isinstance(authors, str) and authors.strip():
        return authors.split(",")[0].strip()
    return "?"


def _year_from(date) -> str:
    s = str(date or "")
    return s[:4] if s[:4].isdigit() else "?"


def _http_get_json(url: str, timeout: float, *, retries: int = 1) -> Optional[dict]:
    """GET + parse JSON, with ONE retry on transient failure. Returns None on any error (best-effort)."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if getattr(r, "status", 200) != 200:
                    return None
                return json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — best-effort; retry once, then degrade to None
            if attempt < retries:
                continue
            return None


def _search(query: str, *, page_size: int, result_type: str, timeout: float) -> Optional[dict]:
    """Europe PMC search (kept as `_search` — the monkeypatch seam the tests pin)."""
    params = urllib.parse.urlencode({"query": query, "format": "json",
                                     "resultType": result_type, "pageSize": page_size})
    return _http_get_json(f"{_EPMC_SEARCH}?{params}", timeout)


# ── grounding-corpus assembly (shared across sources) ──────────────────────────────────────────────
def _fmt_corpus(source_label: str, target: str, phrase: str, records: list[dict], max_results: int) -> Optional[str]:
    """Dedupe records by PMID (preserving first-seen order across query variations), cap, and format the
    compact grounding corpus. None when no PMID-bearing hit survived."""
    seen: set = set()
    kept: list[dict] = []
    for r in records:
        pmid = str(r.get("pmid") or "").strip()
        if not pmid or pmid in seen:
            continue
        seen.add(pmid)
        kept.append(r)
        if len(kept) >= max_results:
            break
    if not kept:
        return None
    header = (f"Top {source_label} results for {target} in {phrase} (cite these PMIDs; you MAY mark "
              f"verified=true only for identifiers listed here):")
    lines = []
    for r in kept:
        cite = f"{r.get('author', '?')} {r.get('year', '?')}, {r.get('journal', '?')}"
        title = (r.get("title") or "").strip().rstrip(".")
        snip = (r.get("snippet") or "").strip()
        lines.append(f"[PMID:{r['pmid']}] {cite} — {title}." + (f" {snip}" if snip else ""))
    return header + "\n" + "\n".join(f"  {ln}" for ln in lines)


def _truncate(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s[:n].rsplit(" ", 1)[0] + "…" if len(s) > n else s


# ── retrievers ─────────────────────────────────────────────────────────────────────────────────────
def europe_pmc_retrieve(target, indication, lens=None, *, max_results: int = 8,
                        abstract_chars: int = 420, timeout: float = 8.0) -> Optional[str]:
    """Grounding corpus of the top Europe PMC hits for (target, indication), LENS-AWARE (see
    _build_query_variations). None on any failure / no hits."""
    if not target:
        return None
    phrase = _indication_phrase(indication)
    records: list[dict] = []
    for query in _build_query_variations(target, indication, lens):
        data = _search(f"{query} AND (HAS_ABSTRACT:Y)", page_size=max_results,
                       result_type="core", timeout=timeout)
        for r in (((data or {}).get("resultList") or {}).get("result") or []):
            pmid = r.get("pmid")           # ONLY a real PMID — never fall back to `id` (a PPR/preprint id
            if not pmid:                   # is not PMID-verifiable and must not be mislabelled [PMID:...]).
                continue
            records.append({
                "pmid": pmid,
                "author": _first_author(r.get("authorString")),
                "year": r.get("pubYear", "?"),
                "journal": r.get("journalTitle") or r.get("source") or "?",
                "title": r.get("title") or "",
                "snippet": _truncate(r.get("abstractText") or "", abstract_chars),
            })
    return _fmt_corpus("Europe PMC", target, phrase, records, max_results)


def pubtator3_retrieve(target, indication, lens=None, *, max_results: int = 8,
                       snippet_chars: int = 420, timeout: float = 8.0) -> Optional[str]:
    """Grounding corpus from NCBI PubTator3 search (entity/bioconcept-index-ranked), LENS-AWARE. Uses the
    relevance-highlighted `text_hl` snippet (tags stripped) as the grounding text. None on failure / no hits.
    A drop-in `retrieve_fn` (same signature as europe_pmc_retrieve) — the fallback source in default_retrieve."""
    if not target:
        return None
    phrase = _indication_phrase(indication)
    records: list[dict] = []
    for query in _build_query_variations(target, indication, lens):
        data = _http_get_json(f"{_PUBTATOR_SEARCH}?{urllib.parse.urlencode({'text': query})}", timeout)
        for r in ((data or {}).get("results") or []):
            pmid = r.get("pmid")
            if not pmid:
                continue
            records.append({
                "pmid": str(pmid),
                "author": _first_author(r.get("authors")),
                "year": _year_from(r.get("date")),
                "journal": r.get("journal") or "?",
                "title": r.get("title") or "",
                "snippet": _truncate(_clean_pubtator_hl(r.get("text_hl") or ""), snippet_chars),
            })
    return _fmt_corpus("NCBI PubTator3", target, phrase, records, max_results)


def default_retrieve(target, indication, lens=None, *, max_results: int = 8, timeout: float = 8.0) -> Optional[str]:
    """RECOMMENDED retriever: Europe PMC first, PubTator3 on failure — a transient outage of one source
    no longer collapses grounding to internal-knowledge/unverified. Both are lens-aware."""
    return (europe_pmc_retrieve(target, indication, lens, max_results=max_results, timeout=timeout)
            or pubtator3_retrieve(target, indication, lens, max_results=max_results, timeout=timeout))


# ── PMID verification (Europe PMC primary, NCBI E-utilities fallback) ───────────────────────────────
def _pmid_exists_epmc(pmid: str, timeout: float) -> Optional[bool]:
    data = _search(f"EXT_ID:{pmid} AND SRC:MED", page_size=1, result_type="idlist", timeout=timeout)
    if data is None:
        return None
    return int(data.get("hitCount") or 0) >= 1


def _pmid_exists_ncbi(pmid: str, timeout: float) -> Optional[bool]:
    """NCBI E-utilities esummary fallback: the PMID exists iff it appears in result.uids with no error."""
    url = f"{_NCBI_ESUMMARY}?{urllib.parse.urlencode({'db': 'pubmed', 'id': pmid, 'retmode': 'json'})}"
    data = _http_get_json(url, timeout)
    if data is None:
        return None
    res = data.get("result") or {}
    if str(pmid) not in [str(u) for u in (res.get("uids") or [])]:
        return False
    return "error" not in (res.get(str(pmid)) or {})


def _pmid_exists(pmid: str, timeout: float) -> Optional[bool]:
    """True/False if the PMID does/doesn't exist; None if NEITHER source could run. Europe PMC first,
    NCBI E-utilities as the fallback so verification survives a single-source outage."""
    r = _pmid_exists_epmc(pmid, timeout)
    if r is not None:
        return r
    return _pmid_exists_ncbi(pmid, timeout)


def verify_citations(result: dict, *, timeout: float = 8.0) -> dict:
    """Reconcile every citation.verified against ground truth (in place) + stamp a `_verification`
    summary. Best-effort: if the checks cannot run, leave flags and mark status 'unavailable'. A citation
    with no PMID stays verified=false (identifier not checkable here)."""
    if not isinstance(result, dict):
        return result
    cites = []
    for ax in (result.get("axes") or []):
        if isinstance(ax, dict):
            cites += [c for c in (ax.get("citations") or []) if isinstance(c, dict)]
    for bs in (result.get("blind_spots") or []):
        if isinstance(bs, dict):
            cites += [c for c in (bs.get("citations") or []) if isinstance(c, dict)]
    checked = verified = flipped = 0
    ran = False
    seen: dict[str, Optional[bool]] = {}
    for c in cites:
        pmid = str(c.get("pmid") or "").strip()
        if not pmid:
            c["verified"] = False              # no identifier → not verifiable here
            continue
        if pmid not in seen:
            seen[pmid] = _pmid_exists(pmid, timeout)
        exists = seen[pmid]
        if exists is None:                     # neither source could run — leave the model's flag
            continue
        ran = True
        checked += 1
        was = bool(c.get("verified"))
        c["verified"] = exists
        verified += 1 if exists else 0
        flipped += 1 if was != exists else 0
    result["_verification"] = ({"status": "unavailable",
                                "note": "PMID verification could not run (no network / API error); "
                                        "citation.verified reflects the model's self-report, treat as unconfirmed."}
                               if (cites and not ran) else
                               {"status": "checked", "source": "europe_pmc",
                                "n_pmid_checked": checked, "n_verified": verified, "n_flipped": flipped})
    return result


__all__ = ["europe_pmc_retrieve", "pubtator3_retrieve", "default_retrieve", "verify_citations"]
