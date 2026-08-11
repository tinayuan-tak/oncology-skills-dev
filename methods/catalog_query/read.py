"""catalog_query.read — read-only query engine over the data-catalog manifests.

This module is the *consumption* side of the data catalog: it loads the source +
derived manifest YAMLs (plus subgroup-catalogs and the target-contracts products
registry) into an in-memory index and answers four kinds of question —

    search   : which dataset/manifest covers a need? (facet filter + keyword)
    describe : everything about ONE manifest (s3_uri, schema, sort key, lineage, consumers)
    lineage  : walk derived_from (upstream) / cited_by (downstream) both directions
    audit    : coverage gaps, stale/legacy references, orphans, size-drift

Per the framework's layer-distinction discipline (mirrored verbatim from
dge_deseq2/read.py): reading + filtering catalog YAML is *compute*, not
*orchestration*. It belongs here in analysis-methods, not in skills/. This
module makes NO orchestration decisions, performs NO network/S3 access, and
NEVER writes — it is a pure function of the on-disk catalog.

Consumers:
  - the catalog-query skill (claude-oncology-skills) via the cli.py subprocess
  - Jupyter notebooks doing ad-hoc "which manifest do I need?" lookups
  - future non-Claude consumers (AgenticBoost, batch jobs)
  - RESOLVER-READY: `describe()` / `load_manifest()` generalize the private
    _load_manifest/_s3_uri_to_path in dge_deseq2/read.py to a public API over
    BOTH sources/ and derived/. A follow-on can back a shared manifest_id ->
    s3_uri resolver here, retiring the ~57 hard-coded S3 keys across methods/.

Companion (read, never written):
    data-catalog:manifests/{sources,derived}/*.yaml
    data-catalog:subgroup-catalogs/**/*.yaml
    data-catalog:indication-configs/*.yaml
    target-contracts:vocabularies/products.yaml
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

# Prefer the libyaml C loader — ~5x faster on the big source manifests (a few
# have 10k+ files[] entries). Fall back to the pure-Python loader if libyaml
# is not built into the local PyYAML. Same semantics either way.
try:
    _SafeLoader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - depends on local libyaml build
    _SafeLoader = yaml.SafeLoader


def _yaml_load(fh):
    return yaml.load(fh, Loader=_SafeLoader)


# Repo roots — env-var-overridable with the local-dev default (matches gdc_somatic_hotspot's
# DATA_CATALOG_ROOT pattern). Overriding via env is what lets CI / a non-/home/sagemaker-user
# checkout resolve manifests (the hardcoded default previously broke any environment — e.g. GitHub
# Actions — where the sibling repos aren't at /home/sagemaker-user).
DATA_CATALOG = Path(os.environ.get(
    "DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"))
TARGET_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))

# ---------------------------------------------------------------------------
# Manifest primitives — the public generalization of dge_deseq2/read.py's
# private _load_manifest (which globs only manifests/derived/). These search
# BOTH sources/ and derived/ so any consumer can resolve any manifest_id.
# ---------------------------------------------------------------------------


def _s3_uri_to_path(s3_uri: str) -> str:
    """Strip the s3:// scheme so a filesystem/pyarrow reader can consume the key."""
    return s3_uri[5:] if s3_uri.startswith("s3://") else s3_uri


def load_manifest(manifest_id: str, root: Path = DATA_CATALOG) -> dict:
    """Load one manifest YAML by id from manifests/{sources,derived}/.

    Generalizes dge_deseq2/read.py:_load_manifest (derived-only) to both trees.
    Raises FileNotFoundError with the two searched dirs if the id is unknown.
    """
    for sub in ("sources", "derived"):
        candidate = root / "manifests" / sub / f"{manifest_id}.yaml"
        if candidate.exists():
            with candidate.open() as f:
                return _yaml_load(f)
    raise FileNotFoundError(
        f"Manifest {manifest_id!r} not found in "
        f"{root}/manifests/{{sources,derived}}/"
    )


def s3_uri_for(manifest_id: str, root: Path = DATA_CATALOG) -> str:
    """Resolve a manifest_id to its authoritative s3_uri (the resolver seam)."""
    return load_manifest(manifest_id, root=root)["s3_uri"]


def bucket_key_for(manifest_id: str, root: Path = DATA_CATALOG) -> tuple[str, str]:
    """Resolve a manifest_id to (bucket, key) for a boto3 get_object/download_file.

    Splits the authoritative s3_uri into its bucket and bucket-relative key — the
    exact pair the WHOLE_FILE readers pass to `s3.download_file(bucket, key, ...)`.
    Lets a reader replace a hand-typed `S3_KEY = "data-catalog/derived/.../x.parquet"`
    constant with `_, S3_KEY = bucket_key_for(MANIFEST_ID)`, so the key is derived
    from the manifest (single source of truth) rather than a parallel copy that can
    drift. Raises FileNotFoundError if the id is unknown (fail loud at import, not
    silently at read).
    """
    path = _s3_uri_to_path(s3_uri_for(manifest_id, root=root))  # bucket/key...
    bucket, _, key = path.partition("/")
    return bucket, key


def bucket_prefix_for(manifest_id: str, root: Path = DATA_CATALOG) -> tuple[str, str]:
    """Resolve a source manifest_id to (bucket, key_prefix) for sub-file reads.

    For a source-release whose s3_uri is a DIRECTORY (ends in '/'), returns the
    bucket-relative prefix WITH its trailing slash preserved — faithful to the
    manifest — so a reader builds a per-file key as `f"{PREFIX}{filename}"`
    (no manual separator). Lets a reader replace a hand-typed
    `PREFIX = "data-catalog/sources/.../dmc-26q1"` + `f"{PREFIX}/Model.csv"` with
    `_, PREFIX = bucket_prefix_for(ID)` + `f"{PREFIX}Model.csv"`, deriving the
    prefix from the manifest (single source of truth). Raises FileNotFoundError
    if the id is unknown.
    """
    bucket, key = bucket_key_for(manifest_id, root=root)
    return bucket, key


def sidecar_bucket_key_for(manifest_id: str, root: Path = DATA_CATALOG) -> tuple[str, str]:
    """Resolve a manifest_id to (bucket, key) for its target-resolution SIDECAR.

    The sidecar path lives in `target_resolution.sidecar_s3_uri` — NOT the
    manifest's top-level s3_uri (which is the payload). Use this for the
    `*.target_resolution.parquet` resolver sidecars, where `bucket_key_for`
    (payload) is the wrong answer. Lets a reader replace a hand-typed
    `SIDECAR_KEY = "data-catalog/.../x.target_resolution.parquet"` with
    `_, SIDECAR_KEY = sidecar_bucket_key_for(MANIFEST_ID)`.

    Raises FileNotFoundError if the id is unknown, or ValueError if the manifest
    has no resolver sidecar (no target_resolution block, or
    target_resolution.not_applicable) — fail loud rather than resolve a wrong path.
    """
    tr = load_manifest(manifest_id, root=root).get("target_resolution") or {}
    if tr.get("not_applicable") or "sidecar_s3_uri" not in tr:
        raise ValueError(
            f"Manifest {manifest_id!r} declares no target-resolution sidecar "
            f"(not_applicable or absent); sidecar_bucket_key_for is inapplicable."
        )
    path = _s3_uri_to_path(tr["sidecar_s3_uri"])
    bucket, _, key = path.partition("/")
    return bucket, key


# ---------------------------------------------------------------------------
# Release resolution (T4, 2026-08-11 engineering review)
# ---------------------------------------------------------------------------
# compose-dashboard's data_mode (latest_approved | pinned | exploratory) + release_pin
# previously flowed only into ID strings — they never selected which manifest a card read.
# resolve_release turns (logical family, data_mode, release_pin) into a concrete manifest_id,
# reusing the SAME catalog machinery (load_catalog + the curator-declared `supersedes` graph)
# rather than inventing a parallel registry.
#
# NB on `latest_approved`: the manifest schema carries NO approval/status field (it's
# additionalProperties:false), so there is no metadata to gate "approved" on today. The only
# honest, catalog-backed definition of "latest approved" is "the newest sibling in the family
# that no other manifest has superseded" (i.e. catalog head via the supersedes back-pointer).
# This is documented as such; a real approval-status field is a future data-catalog change.


class ReleaseResolutionError(ValueError):
    """Raised when a (family, data_mode, release_pin) triple can't be resolved to a manifest."""


def _family_of(manifest_id: str) -> str:
    """The logical family of a manifest id = the id with a trailing version/release suffix
    stripped. Convention in this catalog: `<family>-<release>-v<N>` or `<family>-v<N>` — new
    releases are new SIBLINGS (ids never renamed), so the family is the stable join key.
    Strips trailing `-v<N>` and a trailing release token if present (e.g. `-26q1`)."""
    mid = re.sub(r"-v\d+$", "", manifest_id)                 # drop -v2
    mid = re.sub(r"-\d{2}q\d$", "", mid, flags=re.IGNORECASE)  # drop -26q1 style release token
    return mid


def resolve_release(
    family: str,
    data_mode: str,
    release_pin: Optional[str] = None,
    root: Path = DATA_CATALOG,
    contracts_root: Path = TARGET_CONTRACTS,
) -> str:
    """Resolve a logical product `family` + `data_mode` (+ `release_pin`) to a concrete manifest_id.

    data_mode:
      - "pinned":         requires release_pin; resolves to the exact sibling for that pin. The
                          candidate ids tried are `f"{family}-{release_pin}"` and
                          `f"{family}-{release_pin}-v1"`, else any family member whose id contains
                          the pin token. Fails loud (ReleaseResolutionError) if none exists.
      - "latest_approved":the newest family member NOT named in any other manifest's `supersedes`
                          field (catalog head via the supersedes graph). Ties (no supersedes edges)
                          break by natural id sort (highest version/release suffix wins).
      - "exploratory":    same head resolution as latest_approved, but a release_pin — if given and
                          resolvable — takes precedence (lets a dev pin an in-progress sibling).

    Returns the resolved manifest_id (a string). Never touches S3 — pair with s3_uri_for /
    bucket_key_for to get the path. Fail-loud by design (mirrors the depmap_common release guard).
    """
    idx = load_catalog(root=root, contracts_root=contracts_root)
    members = [mid for mid in idx.manifests if _family_of(mid) == family]
    if not members:
        # family may already BE a concrete id (single-release product) — accept it as-is.
        if family in idx.manifests:
            return family
        raise ReleaseResolutionError(
            f"No manifest in family {family!r} (data_mode={data_mode!r}). "
            f"Known families are the id-prefixes under manifests/{{sources,derived}}/."
        )

    def _pinned(pin: str) -> Optional[str]:
        for cand in (f"{family}-{pin}", f"{family}-{pin}-v1"):
            if cand in idx.manifests:
                return cand
        hits = sorted(m for m in members if pin.lower() in m.lower())
        return hits[-1] if hits else None

    if data_mode == "pinned":
        if not release_pin:
            raise ReleaseResolutionError(f"data_mode='pinned' requires a release_pin for family {family!r}.")
        resolved = _pinned(release_pin)
        if resolved is None:
            raise ReleaseResolutionError(
                f"release_pin={release_pin!r} does not resolve to any manifest in family "
                f"{family!r}. Members: {sorted(members)}."
            )
        return resolved

    if data_mode == "exploratory" and release_pin:
        resolved = _pinned(release_pin)
        if resolved is not None:
            return resolved
        # fall through to head resolution when the pin doesn't resolve (exploratory is permissive)

    if data_mode in ("latest_approved", "exploratory"):
        superseded = {
            rec.supersedes for rec in idx.manifests.values()
            if rec.supersedes and _family_of(rec.supersedes) == family
        }
        head = sorted(m for m in members if m not in superseded)
        if not head:
            # every member is superseded (dangling chain) — fall back to all members.
            head = sorted(members)
        return head[-1]

    raise ReleaseResolutionError(
        f"Unknown data_mode {data_mode!r} (expected latest_approved | pinned | exploratory)."
    )


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------


@dataclass
class ManifestRecord:
    """One normalized manifest, either source-release or derived."""
    id: str
    type: str                                   # source-release | derived
    path: Path
    raw: dict = field(repr=False)
    # forward lineage (declared on the manifest itself)
    derived_from: list[str] = field(default_factory=list)
    declared_cited_by: list[str] = field(default_factory=list)
    # reverse lineage (COMPUTED from the whole index; overrides the declared list)
    computed_cited_by: list[str] = field(default_factory=list)

    # --- convenience accessors over raw, tolerant of the two shapes ---
    @property
    def provider(self) -> Optional[str]:
        return self.raw.get("provider")

    @property
    def dataset(self) -> Optional[str]:
        return self.raw.get("dataset")

    @property
    def version(self) -> Optional[str]:
        return self.raw.get("version")

    @property
    def description(self) -> str:
        # sources use `description`; derived use `transformation`
        return self.raw.get("description") or self.raw.get("transformation") or ""

    @property
    def s3_uri(self) -> Optional[str]:
        return self.raw.get("s3_uri")

    @property
    def data_subject(self) -> Optional[str]:
        return self.raw.get("data_subject")

    @property
    def license(self) -> Optional[str]:
        return self.raw.get("license")

    @property
    def system_of_record(self) -> bool:
        # Schema: "Default true if absent." Only meaningful for source-releases.
        return bool(self.raw.get("system_of_record", True))

    @property
    def size_bytes(self) -> Optional[int]:
        return self.raw.get("total_size_bytes") or self.raw.get("size_bytes")

    @property
    def categories(self) -> list[str]:
        """Distinct file categories (source-releases) — a search/inspect facet.

        Precomputed at load time into raw['_categories'] so the heavy files[]
        array can be dropped from the in-memory record (it is catalog-internal;
        category is the only facet any query needs from it).
        """
        return self.raw.get("_categories", [])

    @property
    def parquet_schema(self) -> list[dict]:
        return self.raw.get("parquet_schema", []) or []

    @property
    def query_optimization(self) -> Optional[dict]:
        return self.raw.get("query_optimization")

    @property
    def supersedes(self) -> Optional[str]:
        return self.raw.get("supersedes")


@dataclass
class CatalogIndex:
    """The whole catalog loaded once: manifests keyed by id + a lineage graph."""
    manifests: dict[str, ManifestRecord]
    # manifest_id -> [product_id, ...] from target-contracts products.yaml
    consumers: dict[str, list[str]]
    # manifest_id -> [subgroup_catalog_id, ...] from subgroup-catalogs/
    subgroup_citations: dict[str, list[str]]
    # indication code -> config dict from indication-configs/
    indication_configs: dict[str, dict]

    # ---- capability 1: search ----
    def search(
        self,
        query: Optional[str] = None,
        *,
        provider: Optional[str] = None,
        data_subject: Optional[str] = None,
        type: Optional[str] = None,
        category: Optional[str] = None,
        license: Optional[str] = None,
        system_of_record: Optional[bool] = None,
    ) -> list[ManifestRecord]:
        """Facet-filter + keyword match over the manifests. All filters AND together.

        `query` matches (case-insensitive substring) against id/description/
        dataset/provider. Facets match exactly (category matches any file
        category). Results are id-sorted for determinism.
        """
        q = query.lower() if query else None
        out: list[ManifestRecord] = []
        for rec in self.manifests.values():
            if type and rec.type != type:
                continue
            if provider and rec.provider != provider:
                continue
            if data_subject and rec.data_subject != data_subject:
                continue
            if license and (rec.license or "").lower().find(license.lower()) < 0:
                continue
            if system_of_record is not None and rec.system_of_record != system_of_record:
                continue
            if category and category not in rec.categories:
                continue
            if q:
                hay = " ".join(
                    str(x) for x in (rec.id, rec.description, rec.dataset, rec.provider) if x
                ).lower()
                if q not in hay:
                    continue
            out.append(rec)
        return sorted(out, key=lambda r: r.id)

    # ---- capability 2: describe ----
    def describe(self, manifest_id: str) -> dict:
        """Authoritative single-source view of one manifest.

        Raises KeyError if unknown (callers surface a helpful message).
        """
        rec = self.manifests[manifest_id]
        return {
            "id": rec.id,
            "type": rec.type,
            "provider": rec.provider,
            "dataset": rec.dataset,
            "version": rec.version,
            "s3_uri": rec.s3_uri,
            "data_subject": rec.data_subject,
            "license": rec.license,
            "system_of_record": rec.system_of_record if rec.type == "source-release" else None,
            "size_bytes": rec.size_bytes,
            "description": rec.description,
            "file_categories": rec.categories,
            "parquet_schema": rec.parquet_schema,
            "query_optimization": rec.query_optimization,
            "derived_from": rec.derived_from,
            "cited_by": rec.computed_cited_by,          # the COMPUTED reverse graph
            "consumed_by_products": self.consumers.get(manifest_id, []),
            "cited_by_subgroup_catalogs": self.subgroup_citations.get(manifest_id, []),
            "manifest_path": str(rec.path),
        }

    # ---- capability 3: lineage ----
    def lineage(
        self,
        manifest_id: str,
        *,
        direction: str = "both",       # upstream | downstream | both
        depth: Optional[int] = None,
    ) -> dict:
        """Walk the lineage graph from a manifest.

        upstream follows derived_from; downstream follows the COMPUTED cited_by
        (which folds in subgroup-catalog citations, exactly as
        validate_catalog.py does). Returns nested adjacency dicts; cli.py renders
        the tree.
        """
        if manifest_id not in self.manifests:
            raise KeyError(manifest_id)

        def walk(mid: str, edge: str, seen: set, d: int) -> dict:
            rec = self.manifests.get(mid)
            if rec is None:
                return {"id": mid, "missing": True, "children": []}
            if mid in seen or (depth is not None and d > depth):
                return {"id": mid, "children": [], "truncated": mid in seen}
            seen = seen | {mid}
            nxt = rec.derived_from if edge == "upstream" else rec.computed_cited_by
            return {
                "id": mid,
                "type": rec.type,
                "children": [walk(c, edge, seen, d + 1) for c in nxt],
            }

        result: dict = {"id": manifest_id}
        if direction in ("upstream", "both"):
            result["upstream"] = walk(manifest_id, "upstream", set(), 0)
        if direction in ("downstream", "both"):
            result["downstream"] = walk(manifest_id, "downstream", set(), 0)
        return result

    # ---- capability 4: audit ----
    def audit(self) -> dict:
        """Curator lens: coverage gaps, superseded/stale, uncited sources.

        Pure derivation from the index — never mutates. Signals are chosen to be
        HONEST rather than noisy: we surface the curator-declared `supersedes`
        field (the ground-truth staleness signal) rather than guessing from id
        version suffixes, which in this catalog are a stability convention (new
        release = new sibling, ids never renamed) not a collision signal.
        """
        # Superseded ids named by another manifest's `supersedes` field.
        supersedes_map = {
            rec.supersedes: rec.id
            for rec in self.manifests.values()
            if rec.supersedes
        }
        # Superseded manifests STILL PRESENT in the catalog — the real stale
        # signal: a newer manifest declared it obsolete but it wasn't removed.
        superseded_still_present = sorted(
            f"{old} (superseded by {new})"
            for old, new in supersedes_map.items()
            if old in self.manifests
        )

        # Uncited source-releases: no manifest derives from them AND no product /
        # subgroup-catalog cites them. NOTE: this is NOT "unused" — reference /
        # annotation sources (HGNC, Ensembl, UniProt, …) are frequently read by
        # methods via a direct S3 path with no catalog-internal citation edge.
        # It flags candidates for a citation-hygiene review, not dead data.
        uncited_sources = sorted(
            rec.id
            for rec in self.manifests.values()
            if rec.type == "source-release"
            and not rec.computed_cited_by
            and not self.consumers.get(rec.id)
            and not self.subgroup_citations.get(rec.id)
        )

        # Coverage gaps: per-indication DGE sensitivity product presence.
        # The batch shipped `{ind}-dge-tumor-vs-normal-sensitivity-v1` products;
        # flag configured indications missing theirs.
        dge_present = {
            m.group(1)
            for mid in self.manifests
            if (m := re.match(r"^(.+)-dge-tumor-vs-normal-sensitivity-v\d+$", mid))
        }
        dge_gaps = sorted(
            code.lower()
            for code in self.indication_configs
            if code.lower() not in dge_present
        )

        return {
            "uncited_sources": uncited_sources,
            "superseded_still_present": superseded_still_present,
            "dge_coverage_gaps": dge_gaps,
            "counts": {
                "sources": sum(1 for r in self.manifests.values() if r.type == "source-release"),
                "derived": sum(1 for r in self.manifests.values() if r.type == "derived"),
                "indication_configs": len(self.indication_configs),
                "subgroup_catalogs": len({
                    c for cats in self.subgroup_citations.values() for c in cats
                }),
            },
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_products(contracts_root: Path) -> dict[str, list[str]]:
    """products.yaml -> {manifest_id: [product_id, ...]} (reverse index).

    Absent/unreadable registry is non-fatal (sibling repo may not be present);
    returns {} so the engine still runs on the data-catalog alone.
    """
    path = contracts_root / "vocabularies" / "products.yaml"
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            data = _yaml_load(f) or {}
    except yaml.YAMLError:
        return {}
    consumers: dict[str, list[str]] = {}
    for product in data.get("products", []) or []:
        pid = product.get("id")
        for src in product.get("sources", []) or []:
            consumers.setdefault(src, []).append(pid)
    return {k: sorted(v) for k, v in consumers.items()}


def _load_subgroup_citations(root: Path) -> dict[str, list[str]]:
    """subgroup-catalogs/**/*.yaml -> {manifest_id: [catalog_id, ...]}.

    Mirrors validate_catalog.py:compute_subgroup_catalog_citations — folds each
    stratum's atomic_strata[].data_source.manifest_id into the reverse index.
    """
    citations: dict[str, list[str]] = {}
    sgc_dir = root / "subgroup-catalogs"
    if not sgc_dir.exists():
        return citations
    for path in sorted(sgc_dir.rglob("*.yaml")):
        try:
            with path.open() as f:
                cat = _yaml_load(f) or {}
        except yaml.YAMLError:
            continue
        cat_id = cat.get("id", path.stem)
        for stratum in cat.get("atomic_strata", []) or []:
            mid = (stratum.get("data_source") or {}).get("manifest_id")
            if mid and cat_id not in citations.setdefault(mid, []):
                citations[mid].append(cat_id)
    return {k: sorted(v) for k, v in citations.items()}


def _load_indication_configs(root: Path) -> dict[str, dict]:
    configs: dict[str, dict] = {}
    ic_dir = root / "indication-configs"
    if not ic_dir.exists():
        return configs
    for path in sorted(ic_dir.glob("*.yaml")):
        try:
            with path.open() as f:
                cfg = _yaml_load(f) or {}
        except yaml.YAMLError:
            continue
        code = cfg.get("indication") or cfg.get("oncotree_code") or path.stem
        configs[code] = cfg
    return configs


@lru_cache(maxsize=4)
def load_catalog(
    root: Path = DATA_CATALOG,
    contracts_root: Path = TARGET_CONTRACTS,
) -> CatalogIndex:
    """Build the CatalogIndex once (cached per (root, contracts_root)).

    Walks manifests/{sources,derived}/*.yaml, computes the reverse cited_by
    graph from derived_from + subgroup-catalog citations (the single source of
    truth, matching validate_catalog.py), and attaches the products consumer map.
    """
    manifests: dict[str, ManifestRecord] = {}
    for sub in ("sources", "derived"):
        for path in sorted((root / "manifests" / sub).glob("*.yaml")):
            with path.open() as f:
                raw = _yaml_load(f)
            if not raw or "id" not in raw:
                continue
            # Precompute distinct file categories, then drop the heavy files[]
            # array — it is catalog-internal (per-file md5/size × thousands of
            # rows) and `category` is the only facet any query reads from it.
            files = raw.pop("files", None) or []
            raw["_categories"] = sorted({fe.get("category") for fe in files} - {None})
            mid = raw["id"]
            manifests[mid] = ManifestRecord(
                id=mid,
                type=raw.get("type", "source-release" if sub == "sources" else "derived"),
                path=path,
                raw=raw,
                derived_from=list(raw.get("derived_from", []) or []),
                declared_cited_by=list(raw.get("cited_by", []) or []),
            )

    subgroup_citations = _load_subgroup_citations(root)

    # Compute the reverse graph from derived_from (manifest->manifest) AND the
    # subgroup-catalog citations — identical semantics to validate_catalog.py's
    # compute_cited_by + compute_subgroup_catalog_citations.
    reverse: dict[str, set[str]] = {}
    for rec in manifests.values():
        for upstream in rec.derived_from:
            reverse.setdefault(upstream, set()).add(rec.id)
    for mid, cats in subgroup_citations.items():
        reverse.setdefault(mid, set()).update(cats)
    for rec in manifests.values():
        rec.computed_cited_by = sorted(reverse.get(rec.id, set()))

    return CatalogIndex(
        manifests=manifests,
        consumers=_load_products(contracts_root),
        subgroup_citations=subgroup_citations,
        indication_configs=_load_indication_configs(root),
    )
