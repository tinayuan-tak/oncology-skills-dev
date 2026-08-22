"""Structural lint: query-time card readers must not download a WHOLE derived product to read it.

THE ANTI-PATTERN (data-layer hardening, 2026-08-21 — see docs of the parquet-storage-standard)
------------------------------------------------------------------------------------------------
A per-target/per-cohort reader that calls ``s3.download_file(...)`` to pull an ENTIRE derived
product to local disk, then reads one gene/target/cohort's slice out of it, pays the whole-file
download on every cold start. The standard is to STREAM with pushdown instead:
``pyarrow.parquet.read_table(f"{bucket}/{key}", filesystem=S3FileSystem(), filters=[(key,"=",v)],
columns=[...])`` — only the needed column-chunks / row-groups transit the wire, no download.
Exemplars: ``methods/combo_drug_anchor/read.py``, ``methods/dge_deseq2/read.py:_get_s3fs``,
``methods/depmap_common/parquet.py:_stream_table``.

WHAT THIS LINT ENFORCES (a RATCHET)
-----------------------------------
Statically (via ``ast``) scan every ``methods/*/*.py`` (readers + one-level helpers) for a CALL to
``*.download_file(...)``. Each call site is keyed ``"<module>/<file>::<enclosing_function>"`` (stable
across line moves). A site FAILS the build unless it is (a) inline-marked, (b) in ``_ALLOWLIST``
(legitimately full-file), or (c) in ``_BASELINE`` (pre-existing burn-down debt, enumerated so CI is
green today). Any NEW ``download_file`` in a reader trips the guard — new whole-download readers
cannot be added.

TWO SUPPRESSION LISTS (the distinction reviewers care about)
------------------------------------------------------------
``_ALLOWLIST`` — PERMANENTLY legitimate full-file reads: (1) precompute / derive / build pipelines
  that INTENTIONALLY consume the whole product to PRODUCE a derived one; (2) reference / annotation
  loaders (gene-length, exon index, PWM, pathway maps) — small, one-time, whole-file by nature;
  (3) small single-shot tables where a download is already cheap; (4) the deliberate whole-matrix
  BATCH escape hatch (``depmap_common.get_full_matrix_path``) that pairs with the streamed per-target
  path; (5) graceful-degradation FALLBACKS that sit BEHIND a streamed primary read.
``_BASELINE`` — pre-existing query-time whole-download readers still to be converted (burn-down).
  Shrinks as each is streamed; a stale entry (no longer present) is reported by the not-stale test.

ESCAPE HATCH: put ``# pushdown-discipline: exempt -- <reason>`` on the download_file line (or in its
enclosing function) to suppress a finding inline, next to the code.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_METHODS = Path(__file__).resolve().parents[1] / "methods"


# --- PERMANENTLY legitimate full-file download_file sites (keyed <module>/<file>::<function>) ---
_ALLOWLIST = {
    # (1) precompute / derive / build pipelines — consume the whole upstream product BY DESIGN.
    "cptac_protein_deg/steps/01_prepare_msstats_input.py::download": "precompute: prepares MSstats input from the full matrix",
    "surfaceome_family_fusion/derive.py::_download_source": "derive: builds the derived product from full upstream",
    # (2) whole-matrix BATCH escape hatch — the deliberate pair of the streamed per-target path.
    "depmap_common/parquet.py::_fetch_parquet": "batch escape hatch (get_full_matrix_path) for full-scan precompute jobs; per-target reads stream",
    # (3) reference / annotation loaders — small, one-time, whole-file by nature.
    "dge_deseq2/gene_lengths.py::_try_s3_fetch": "reference: gene-length table, small one-time load",
    "gencode_exon_index/loader.py::_try_s3_fetch": "reference: GENCODE exon index annotation",
    "kinome_atlas_pwm_lookup/loader.py::_try_s3_fetch": "reference: kinase PWM lookup",
    "reactome_pathway_context/read.py::_ensure_cached": "reference: Reactome pathway map",
    "depmap_paralog_aggregator/cli.py::_ensure_ensembl_cached": "reference: Ensembl paralog pairs",
    "depmap_paralog_aggregator/cli.py::_ensure_ensembl_id_map_cached": "reference: Ensembl id map",
    # (4) small single-shot tables — download already cheap.
    "gnomad_constraint/cli.py::_download_source": "small (~19k-row) constraint table, single-shot",
    "tcga_gtex_expression_distribution/read.py::_ensure_sidecar_cached": "small UUID<->barcode sidecar (subtyping bridge)",
    # (5) whole-file products that need full extraction (zip / non-columnar) — no pushdown possible.
    "hpa_normal_tissue_liability/cli.py::_ensure_hpa_cached": "HPA zip archive — needs full extract, not columnar",
    # (6) small DUAL-INDEX readers — load a small (<~2MB) per-protein product ONCE and build an
    # in-memory index keyed by BOTH gene_symbol AND uniprot accession, serving unbounded per-target
    # lookups. Callers pass HGNC SYMBOLS but the product's sort/filter key is the UniProt AC, so a
    # per-target pushdown cannot preserve the symbol-lookup path; the whole-file dual-index build is
    # required and the download is already cheap. (Reclassified from _BASELINE in burn-down Wave 1.)
    "surfaceome_family_fusion/read.py::_ensure_derived_cached": "449KB dual-index (gene_symbol|uniprot_ac); callers pass symbols, sort key is uniprot_ac",
    "structure_features_static/read.py::_ensure_derived_cached": "1.5MB dual-index structure-features; symbol|uniprot_ac lookup, whole-index build",
    "structure_features_static/read.py::_ensure_ligand_cached": "403KB dual-index ligandability; symbol|uniprot_id lookup, whole-index build",
    "surface_antigen_density_ladder/read.py::_ensure_corpus_cached": "181-record curated density corpus — tiny single-shot",
    # (7) graceful-degradation FALLBACK behind a streamed-pushdown PRIMARY. The reader's primary path
    # already reads a materialised per-gene pushdown product; this download is only the last-resort
    # fallback when that product is unreachable — resilience, not a cold-start cost on the happy path.
    "depmap_paralog_aggregator/read.py::_ensure_paralog_cached": "FALLBACK behind depmap-paralog-buffering-per-gene-v1 pushdown primary (reader already migrated); 69MB ParalogGeneEffect.csv used only if the product is unreachable, and the buffering product's offline Ensembl-Compara ohnolog join can't be reproduced from the CSV anyway",
}

# --- pre-existing query-time whole-download readers, to CONVERT to streamed pushdown (burn-down) ---
# Each is a real per-target/cohort reader that still downloads the whole product. Shrinks as converted.
_BASELINE = {
    "signor_mechanism_network/read.py::_try_load_derived_parquet_from_s3": "prefetch of signor-mechanism-network-per-gene-v1 which was REVERTED (no manifest/object) — needs re-materialising",
    "signor_mechanism_network/read.py::_ensure_signor_source_cached": "SIGNOR source TXT compose-on-read — needs a parquet product",
}

_MARKER = "pushdown-discipline: exempt"


def _enclosing_function(tree: ast.AST):
    """Map each ast node to the name of its nearest enclosing def/asyncdef (or '<module>')."""
    parent_fn = {}
    stack = [("<module>", tree)]

    class V(ast.NodeVisitor):
        def _visit_scope(self, node, name):
            for child in ast.iter_child_nodes(node):
                parent_fn[child] = name
                self._descend(child, name)

        def _descend(self, node, name):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.iter_child_nodes(node):
                    parent_fn[child] = node.name
                    self._descend(child, node.name)
            else:
                for child in ast.iter_child_nodes(node):
                    parent_fn[child] = name
                    self._descend(child, name)

    v = V()
    v._visit_scope(tree, "<module>")
    return parent_fn


def _scan():
    """Return {key: (relpath, lineno)} for every download_file call site under methods/."""
    found = {}
    for py in sorted(_METHODS.rglob("*.py")):
        if "/tests/" in str(py) or py.name.startswith("test_"):
            continue
        src = py.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        parent_fn = _enclosing_function(tree)
        lines = src.splitlines()
        rel = str(py.relative_to(_METHODS))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "download_file":
                fn = parent_fn.get(node, "<module>")
                # inline exempt marker on the call line or anywhere in the enclosing function's span
                exempt = False
                if isinstance(node, ast.Call):
                    ln = node.lineno
                    if 0 < ln <= len(lines) and _MARKER in lines[ln - 1]:
                        exempt = True
                if exempt:
                    continue
                found[f"{rel}::{fn}"] = (rel, node.lineno)
    return found


def test_no_new_whole_download_readers():
    found = _scan()
    known = set(_ALLOWLIST) | set(_BASELINE)
    violations = sorted(k for k in found if k not in known)
    assert not violations, (
        "NEW whole-file download_file in a reader — stream with pushdown instead "
        "(pyarrow read_table over S3FileSystem with filters=/columns=; see the parquet-storage-standard "
        "and methods/combo_drug_anchor/read.py). If legitimately whole-file (precompute/reference/batch/"
        "fallback), add it to _ALLOWLIST with a reason or mark the line "
        f"'# {_MARKER} -- <reason>'. New sites:\n  " + "\n  ".join(
            f"{k} ({found[k][0]}:{found[k][1]})" for k in violations))


def test_baseline_and_allowlist_not_stale():
    """Every _BASELINE / _ALLOWLIST key must still correspond to a real download_file site — a stale
    entry (site converted or removed) should be deleted so the ratchet reflects reality."""
    found = set(_scan())
    stale = sorted((set(_BASELINE) | set(_ALLOWLIST)) - found)
    assert not stale, (
        "Stale pushdown-discipline entries (no longer a download_file site — remove them):\n  "
        + "\n  ".join(stale))
