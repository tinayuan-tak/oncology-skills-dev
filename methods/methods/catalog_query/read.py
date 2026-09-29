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
module makes NO orchestration decisions, performs NO network/S3 access, and NEVER mutates the
catalog — it is a pure function of the on-disk catalog. Its one sanctioned write is an atomic,
self-invalidating memoization of the BUILT INDEX to a temp cache dir (a derived artifact keyed by a
signature over the catalog inputs — see load_catalog); that is an optimization, never a catalog
mutation, and it fails open to a fresh build on any error.

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

import hashlib
import os
import pickle
import re
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from methods.roots import contracts_root, data_catalog_root

# Prefer the libyaml C loader — ~5x faster on the big source manifests (a few
# have 10k+ files[] entries). Fall back to the pure-Python loader if libyaml
# is not built into the local PyYAML. Same semantics either way.
try:
    _SafeLoader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - depends on local libyaml build
    _SafeLoader = yaml.SafeLoader


def _yaml_load(fh):
    return yaml.load(fh, Loader=_SafeLoader)


# The `files:` array (per-file path/md5/size) runs to 10k+ entries on the big source releases —
# 700k+ YAML lines catalog-wide — and load_catalog DISCARDS it, keeping only the distinct file
# `category` set. Constructing those arrays dominated the catalog parse (~7s; ~0.6s once skipped).
# _lean_load_manifest text-strips the top-level `files:` block BEFORE parsing (so the C scanner never
# tokenizes it) while harvesting each entry's `category` via regex. Byte-identical to
# `_yaml_load(f)` + `raw.pop("files")` + the category set for every manifest — guarded by
# tests/methods/catalog_query/test_lean_parse_equivalence.py.
_FILES_KEY_RE = re.compile(r"^files:\s*(#.*)?$")
_CATEGORY_RE = re.compile(r"^\s+(?:-\s+)?category:\s*(.+?)\s*(?:#.*)?$")
_FORMAT_RE = re.compile(r"^\s+(?:-\s+)?format:\s*(.+?)\s*(?:#.*)?$")


def _lean_load_manifest(path):
    """Parse a manifest to (doc_without_files, sorted_categories, sorted_formats) WITHOUT constructing
    the discarded `files:` array. Strips the top-level (column-0) block-style `files:` block — its line
    plus every following indented / column-0 sequence-item line up to the next column-0 key — and
    harvests each entry's `category` AND `format` scalar (the two facets any query reads from files[]).
    A manifest with no block-style `files:` (or an inline `files: [...]`) falls through to a normal
    parse; a defensive `doc.pop('files')` then matches load_catalog's unconditional pop."""
    text = path.read_text()
    lines = text.splitlines()
    out: list[str] = []
    cats: set = set()
    fmts: set = set()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if _FILES_KEY_RE.match(line):
            i += 1
            while i < n:
                l = lines[i]
                if l == "" or l[0] in (" ", "\t") or l.startswith("- ") or l == "-" or l.startswith("-\t"):
                    m = _CATEGORY_RE.match(l)
                    if m:
                        v = m.group(1).strip().strip('"').strip("'")
                        if v:
                            cats.add(v)
                    mf = _FORMAT_RE.match(l)
                    if mf:
                        vf = mf.group(1).strip().strip('"').strip("'")
                        if vf:
                            fmts.add(vf)
                    i += 1
                    continue
                break
            continue
        out.append(line)
        i += 1
    # Preserve the file's trailing newline so a trailing block/folded scalar parses identically.
    body = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    doc = yaml.load(body, Loader=_SafeLoader) or {}
    # Defensive: an inline `files: [...]` (flow style) isn't stripped above; match the original's
    # unconditional pop so `files` never leaks into raw (its categories would be unharvested, but no
    # such manifest exists in the catalog today — the equivalence guard test would catch a new one).
    doc.pop("files", None)
    return doc, sorted(cats), sorted(fmts)


# Repo roots — env-var-overridable, defaulting to the sibling checkout DERIVED from this file's own
# location (matches gdc_somatic_hotspot's DATA_CATALOG_ROOT pattern). Overriding via env used to be
# the only thing that let CI or any non-/home/sagemaker-user checkout resolve manifests; the derived
# default now matches CI's own layout, so methods-validate.yml no longer exports these roots at all —
# CI exercises this `or` branch exactly as a fresh checkout does, which is the point of not pinning
# it. `or` rather than a two-arg .get() default so an EMPTY value falls back too:
# .get(K, d) returns "" and Path("") is "." — the CWD, a plausible wrong root that reads as
# "manifests missing" rather than as a resolution failure.
DATA_CATALOG = data_catalog_root()
TARGET_CONTRACTS = contracts_root()

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
    raise FileNotFoundError(f"Manifest {manifest_id!r} not found in {root}/manifests/{{sources,derived}}/")


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

    DOTTED releases (2026-09-11): a release whose own version has a minor component is written with
    the dot as a hyphen — `gdc-pancohort-somatic-dr45-0` (GDC DR45.0), `genie-public-v19-0` (GENIE
    19.0), `hpa-v25-1` (HPA v25.1), `toxcast-invitrodb-v3-3`. The single-token patterns left that
    trailing `-0` / `-1` in the family key, so a card declaring the release-free logical id — which
    is what a card with a separate `release_pin` MUST declare, or it freezes to one release — found
    no family members and the run published
    `resolution_error: No manifest in family 'gdc-pancohort-somatic'` instead of a real head and
    staleness verdict. Measured on the 509-manifest catalog: 13 ids change family and NO family's
    member count changes (all 13 are singletons before and after), so no head selection moves.
    Declaring the fully-pinned id still works — resolve_release falls back to
    `if family in idx.manifests: return family`.

    MID-STRING release (2026-09-26, #1768): the DepMap parquet derived product is named
    `depmap-<release>-parquet-v<N>` (`depmap-26q1-parquet-v1`, `depmap-26q3-parquet-v1`) — the quarter
    token sits MID-string, sandwiched between the stem and a `-<format>-v<N>` derived tail, so the
    trailing patterns below never reach it: the two releases resolved to DISTINCT family keys
    (`depmap-26q1-parquet` vs `depmap-26q3-parquet`), were never siblings, and `is_stale` (envelope's
    `head not in used`) could NEVER fire for that family — a detector blind spot that fails OPEN.
    (Contrast the source family `depmap-consortium-26q1` and the `<stem>-<release>-v<N>` derived
    families `depmap-coessentiality-26q1-v1` / `allgene-depmap-rank-26q1-v1`: there the quarter is
    trailing-adjacent, so stripping `-v<N>` first exposes it and they already collapse correctly.)
    The added pattern strips a quarter token ONLY in that `<stem>-<release>-<format>-v<N>` shape
    (quarter immediately followed by a single lowercase format word and a trailing version). Measured
    on the live 547-manifest catalog this changes EXACTLY the two parquet ids (both -> `depmap-parquet`)
    and NO other id — the consortium sub-products (`depmap-consortium-26q1-paralogs`,
    `-crispr-supplementary`, `-rnai`, ...) lack a trailing `-v<N>` and are untouched, so no other
    family's key or head selection moves (verdict-inert; guards the same invariant as
    test_dotted_release_family_change_moves_no_head).
    """
    mid = re.sub(r"-dr\d+(?:-\d+)?$", "", manifest_id, flags=re.IGNORECASE)  # drop -dr45 / -dr45-0
    # mid-string quarter in the derived shape <stem>-<release>-<format>-v<N> (e.g. depmap-26q1-parquet-v1)
    mid = re.sub(r"-\d{2}q\d+(?=-[a-z]+-v\d+(?:-\d+)?$)", "", mid, flags=re.IGNORECASE)
    mid = re.sub(r"-v\d+(?:-\d+)?$", "", mid, flags=re.IGNORECASE)  # drop -v2 / -v25-1
    mid = re.sub(r"-\d{2}q\d+$", "", mid, flags=re.IGNORECASE)  # drop -26q1 / -26q10 release token
    return mid


def _version_key(manifest_id: str) -> tuple:
    """Natural-order sort key for picking the HEAD among family siblings.

    A plain `sorted(...)[-1]` is LEXICAL, which mis-orders exactly the tokens that
    distinguish sibling releases: `-v10` sorts BEFORE `-v9` ('1' < '9'), and a release
    token like `26q10` sorts before `26q2`. That silently returns an OLDER manifest as
    the "latest" head. This key splits the id into alternating text / digit-run chunks and
    compares digit runs as ints, so `foo-v10` > `foo-v9` and `bar-26q10` > `bar-26q2`.
    Each chunk is emitted as a (type_flag, value) pair (0=int, 1=str) so positions never
    compare int-vs-str; sibling ids share structure, so aligned positions are same-type."""
    parts = [p for p in re.split(r"(\d+)", manifest_id) if p != ""]
    return tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in parts)


def resolve_release(
    family: str,
    data_mode: str,
    release_pin: Optional[str] = None,
    root: Path = DATA_CATALOG,
    contracts_root: Path = TARGET_CONTRACTS,
) -> str:
    """Resolve a logical product `family` + `data_mode` (+ `release_pin`) to a concrete manifest_id.

    `family` is normally a manifest-id family (the id with its `-v<N>`/`-<release>` suffix stripped),
    but it may also be a concrete manifest id (single-release product) or a **product_id** from
    target-contracts/vocabularies/products.yaml. The product_id path exists because a card that reads
    an indication-dispatched product declares the stable product_id rather than a per-indication
    manifest id; when `family` matches no manifest-id family and no concrete id, it is resolved to the
    head among the manifests whose own `product_id:` field equals it (the product's OUTPUT manifests) —
    NOT via idx.consumers, which is the product's INPUT sources.

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

        # `family` may be a PRODUCT_ID (products.yaml registry id) rather than a manifest-id
        # family. A card that reads an indication-DISPATCHED product declares the stable
        # product_id (it cannot name one manifest statically — e.g. COADREAD reads the paired-
        # adjacent DGE manifest, other indications read the {ind}-dge-tumor-vs-normal-sensitivity
        # sibling), so provenance stamps the product_id. Resolve it to the manifest(s) whose OWN
        # `product_id:` field equals it — i.e. the product's OUTPUT manifest(s) — and take the head
        # among THOSE. NOTE: this keys on the manifest's product_id field, NOT idx.consumers
        # (which is products.yaml `sources` — a product's INPUT manifests; resolving there would
        # wrongly return the upstream raw source, e.g. a TCGA GDC release, not the derived product).
        # Purely additive: only reached when the string matches no manifest-id family and no
        # concrete manifest id.
        def _declares_product(rec) -> bool:
            v = rec.raw.get("product_id")
            return v == family or (isinstance(v, list) and family in v)

        members = sorted(mid for mid, rec in idx.manifests.items() if _declares_product(rec))
        if not members:
            raise ReleaseResolutionError(
                f"No manifest in family {family!r} (data_mode={data_mode!r}). "
                f"Known families are the id-prefixes under manifests/{{sources,derived}}/, or a "
                f"product_id from target-contracts/vocabularies/products.yaml."
            )

    def _pinned(pin: str) -> Optional[str]:
        for cand in (f"{family}-{pin}", f"{family}-{pin}-v1"):
            if cand in idx.manifests:
                return cand
        hits = sorted((m for m in members if pin.lower() in m.lower()), key=_version_key)
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
        # A supersedes edge is in-family either by the id-prefix family match OR (when resolving a
        # product_id) by pointing at one of the product's own manifests — the product_id will never
        # equal _family_of(a manifest id), so the membership test is what makes head resolution honor
        # supersedes within a product's manifest set.
        _member_set = set(members)
        superseded = {
            rec.supersedes
            for rec in idx.manifests.values()
            if rec.supersedes and (_family_of(rec.supersedes) == family or rec.supersedes in _member_set)
        }
        # Version-aware sort (NOT lexical): `-v10` must beat `-v9`, `26q10` must beat `26q2`.
        head = sorted((m for m in members if m not in superseded), key=_version_key)
        if not head:
            # every member is superseded (dangling chain) — fall back to all members.
            head = sorted(members, key=_version_key)
        return head[-1]

    raise ReleaseResolutionError(f"Unknown data_mode {data_mode!r} (expected latest_approved | pinned | exploratory).")


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------


@dataclass
class ManifestRecord:
    """One normalized manifest, either source-release or derived."""

    id: str
    type: str  # source-release | derived
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
    def formats(self) -> list[str]:
        """Distinct file formats present (fastq/bam/vcf/parquet/h5ad/...), harvested from files[] at
        load time into raw['_formats']. The reprocessing-triage facet: 'which datasets have RAW reads'."""
        return self.raw.get("_formats", [])

    @property
    def parquet_schema(self) -> list[dict]:
        return self.raw.get("parquet_schema", []) or []

    @property
    def query_optimization(self) -> Optional[dict]:
        return self.raw.get("query_optimization")

    @property
    def supersedes(self) -> Optional[str]:
        return self.raw.get("supersedes")


# Merged-view field access for the curated `classification:` block. Each queryable field maps to
# (classification_key on the manifest, path into the generated dataset-intelligence profile, is_list).
# The manifest block is AUTHORITATIVE; the profile value (curated ⊕ inferred by dataset_intel_lib) is
# the fallback so a filter still reaches the ~490 manifests not yet backfilled.
# field -> (classification-block key, path into the dataset-intelligence profile, is_list).
# is_list=True → merged_field normalizes to a list and search matches by membership. measurement_class
# and analytical_stage are scalar-OR-array on the manifest (a multi-assay release lists all), so they
# are membership-matched too. Fields with no classification key (aggregation_recommendation) resolve
# from the profile only — .get(<key>) on the block simply returns None and falls through.
_MERGED_FIELDS: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "indications": ("indications", ("biology", "indications", "value"), True),
    "tissue": ("tissue", ("biology", "tissue", "value"), True),
    "measurement_class": ("measurement_class", ("measurement", "measurement_class", "value"), True),
    "measurement_type": ("measurement_type", ("measurement", "measurement_type", "value"), False),
    "platform": ("platform", ("measurement", "platform", "value"), False),
    "molecular_grain": ("molecular_grain", ("usage", "molecular_grain"), False),
    "gene_key": ("gene_key", ("usage", "gene_key"), False),
    "sample_type": ("sample_type", ("biology", "sample_type", "value"), True),
    "analytical_stage": ("analytical_stage", ("measurement", "analytical_stage", "value"), True),
    "reference_genome": ("reference_genome", ("measurement", "reference_genome", "value"), False),
    "annotation": ("annotation", ("measurement", "annotation", "value"), False),
    "license_class": ("license_class", ("quality", "license_class"), False),
    "treatment": ("treatment", ("biology", "treatment", "value"), True),
    "aggregation_recommendation": ("aggregation_recommendation", ("usage", "aggregation_recommendation"), False),
}

# Facets matched by case-insensitive substring rather than exact/membership (free-text values).
_SUBSTRING_FACETS = {"annotation", "platform"}


def _dig(d: Optional[dict], path: tuple[str, ...]):
    """Walk a nested dict by key path; return None if any hop is missing/not-a-dict."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


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
    # manifest_id -> generated dataset-intelligence profile (curated ⊕ inferred enrichment)
    profiles: dict[str, dict] = field(default_factory=dict)

    # ---- curated classification merged view ----
    def _classification(self, rec: ManifestRecord) -> dict:
        return rec.raw.get("classification") or {}

    def merged_field(self, rec: ManifestRecord, field_name: str):
        """The value of a classification field: the curated manifest block (authoritative) if present,
        else the generated dataset-intelligence profile value (curated ⊕ inferred fallback), else None.
        Returns a list for list-valued fields (indications, sample_type), a scalar otherwise."""
        cls_key, ppath, is_list = _MERGED_FIELDS[field_name]
        v = self._classification(rec).get(cls_key)
        if v in (None, [], ""):
            v = _dig(self.profiles.get(rec.id), ppath)  # inferred fallback
        if is_list:  # normalize BOTH curated and inferred to a list so callers see one shape
            return v if isinstance(v, list) else ([] if v in (None, "") else [v])
        return v

    def enrichment(self, rec: ManifestRecord) -> dict:
        """Merged classification view for one manifest, each field tagged `manifest` (curated) vs
        `inferred` (from the profile) so provenance is visible at the point of use."""
        out: dict[str, dict] = {}
        cls = self._classification(rec)
        for field_name in _MERGED_FIELDS:
            cls_key = _MERGED_FIELDS[field_name][0]
            val = self.merged_field(rec, field_name)
            if val in (None, []):
                continue
            out[field_name] = {
                "value": val,
                "source": "manifest" if cls.get(cls_key) not in (None, [], "") else "inferred",
            }
        return out

    # ---- capability 1: search ----
    @staticmethod
    def _facet_ok(wanted, have, substring: bool) -> bool:
        """True if a facet passes. `wanted` may be a str or a list (OR within — any match passes);
        `have` is the merged value (scalar or list). substring=True does case-insensitive contains
        (free-text facets like annotation/platform), else exact membership."""
        if not wanted:
            return True
        wl = wanted if isinstance(wanted, list) else [wanted]
        haves = have if isinstance(have, list) else ([] if have in (None, "") else [have])
        if substring:
            hay = " ".join(str(h) for h in haves).lower()
            return any(str(w).lower() in hay for w in wl)
        return any(w in haves for w in wl)

    def search(
        self,
        query: Optional[str] = None,
        *,
        provider: Optional[str] = None,
        data_subject: Optional[str] = None,
        type: Optional[str] = None,
        category: Optional[str] = None,
        file_format: Optional[str] = None,
        license: Optional[str] = None,
        system_of_record: Optional[bool] = None,
        indication=None,
        measurement_class=None,
        measurement_type=None,
        grain=None,
        gene_key=None,
        sample_type=None,
        stage=None,
        genome_build=None,
        license_class=None,
        platform=None,
        tissue=None,
        treatment=None,
        aggregation=None,
    ) -> list[ManifestRecord]:
        """Facet-filter + keyword match over the manifests. All facets AND together; a facet given a
        LIST OR-matches within itself (e.g. indication=['LUAD','LUSC']).

        `query` = case-insensitive substring over id/description/dataset/provider. Structural facets
        (provider/data_subject/type/category/file_format/license/system_of_record) match manifest
        fields. Scientific facets match the MERGED classification view — the curated `classification:`
        block if present, else the dataset-intelligence profile (curated ⊕ inferred). annotation and
        platform match by substring; the rest by exact membership. Results are id-sorted.
        """
        q = query.lower() if query else None
        # scientific facet arg -> merged-view field name
        sci = {
            "indications": indication,
            "measurement_class": measurement_class,
            "measurement_type": measurement_type,
            "molecular_grain": grain,
            "gene_key": gene_key,
            "sample_type": sample_type,
            "analytical_stage": stage,
            "reference_genome": genome_build,
            "license_class": license_class,
            "platform": platform,
            "tissue": tissue,
            "treatment": treatment,
            "aggregation_recommendation": aggregation,
        }
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
            if file_format and not self._facet_ok(file_format, rec.formats, substring=False):
                continue
            if any(
                not self._facet_ok(w, self.merged_field(rec, fn), fn in _SUBSTRING_FACETS) for fn, w in sci.items() if w
            ):
                continue
            if q:
                hay = " ".join(str(x) for x in (rec.id, rec.description, rec.dataset, rec.provider) if x).lower()
                if q not in hay:
                    continue
            out.append(rec)
        return sorted(out, key=lambda r: r.id)

    def facet_values(self, field_name: str) -> list[tuple[str, int]]:
        """Distinct merged values for a scientific facet + how many manifests carry each,
        descending by count then value. Powers the `facets` discovery subcommand."""
        from collections import Counter

        c: Counter = Counter()
        for rec in self.manifests.values():
            v = self.merged_field(rec, field_name)
            for item in v if isinstance(v, list) else ([v] if v not in (None, "") else []):
                c[item] += 1
        return sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0])))

    # ---- capability 2: describe ----
    def describe(self, manifest_id: str) -> dict:
        """Authoritative single-source view of one manifest.

        Raises KeyError if unknown (callers surface a helpful message).
        """
        rec = self.manifests[manifest_id]
        prof = self.profiles.get(manifest_id) or {}
        tr = rec.raw.get("target_resolution") or {}
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
            "file_formats": rec.formats,
            "parquet_schema": rec.parquet_schema,
            "query_optimization": rec.query_optimization,
            "classification": self._classification(rec),  # the curated block as-authored (may be {})
            "enrichment": self.enrichment(rec),  # merged view, each field tagged manifest|inferred
            "pipeline": rec.raw.get("pipeline"),  # aligner/quantifier/annotation — reprocessing provenance
            # resolver sidecar: does this product resolve to canonical hgnc_id (safe cross-source join)?
            "has_resolver_sidecar": bool(tr.get("sidecar_s3_uri")),
            "native_key_type": tr.get("native_key_type"),
            # integration signals from the inferred profile (merge-triage)
            "scale": prof.get("scale"),
            "entity_purity": _dig(prof, ("quality", "entity_purity")),
            "annotation_provenance": _dig(prof, ("quality", "annotation_provenance")),
            "access_tier": _dig(prof, ("quality", "access_tier")),
            "aggregation_recommendation": _dig(prof, ("usage", "aggregation_recommendation")),
            "aggregation_rationale": _dig(prof, ("usage", "aggregation_rationale")),
            "constituent_studies": prof.get("constituent_studies", []),
            "derived_from": rec.derived_from,
            "cited_by": rec.computed_cited_by,  # the COMPUTED reverse graph
            "consumed_by_products": self.consumers.get(manifest_id, []),
            "cited_by_subgroup_catalogs": self.subgroup_citations.get(manifest_id, []),
            "manifest_path": str(rec.path),
        }

    # ---- capability 3: lineage ----
    def lineage(
        self,
        manifest_id: str,
        *,
        direction: str = "both",  # upstream | downstream | both
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
        supersedes_map = {rec.supersedes: rec.id for rec in self.manifests.values() if rec.supersedes}
        # Superseded manifests STILL PRESENT in the catalog — the real stale
        # signal: a newer manifest declared it obsolete but it wasn't removed.
        superseded_still_present = sorted(
            f"{old} (superseded by {new})" for old, new in supersedes_map.items() if old in self.manifests
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
            m.group(1) for mid in self.manifests if (m := re.match(r"^(.+)-dge-tumor-vs-normal-sensitivity-v\d+$", mid))
        }
        dge_gaps = sorted(code.lower() for code in self.indication_configs if code.lower() not in dge_present)

        # Field-based DGE coverage: indications reachable via a curated tumor-vs-normal bulk_rna
        # product (classification.measurement_type == 'tumor_vs_normal_selectivity'). Strictly more
        # correct than the id-regex (catches a differently-named product; ignores a renamed one), but
        # depends on the classification backfill — so during the rollout it runs ALONGSIDE the regex
        # signal as a cross-check rather than replacing it.
        dge_covered_field: set[str] = set()
        for rec in self.manifests.values():
            if "bulk_rna" in (self.merged_field(rec, "measurement_class") or []) and (
                self._classification(rec).get("measurement_type") == "tumor_vs_normal_selectivity"
            ):
                dge_covered_field.update(str(i).upper() for i in (self.merged_field(rec, "indications") or []))
        dge_gaps_field = sorted(c for c in self.indication_configs if c.upper() not in dge_covered_field)

        # Cross-source overlaps: the same underlying study reachable through >1 manifest (double-count
        # risk when merging). Inverts the profiles' constituent_studies dedup keys (doi:/geo:/pmid:/
        # cxg:/3ca:) to study_key -> [manifest_id]; reports keys with more than one manifest. The
        # dedup guard for honest pooling. Empty when the profile layer is absent.
        study_to_manifests: dict[str, set[str]] = {}
        for mid, prof in self.profiles.items():
            for s in prof.get("constituent_studies") or []:
                key = s.get("key")
                if key and not key.startswith("manifest:"):  # a manifest:self key is not a shared study
                    study_to_manifests.setdefault(key, set()).add(mid)
        overlaps = {k: sorted(v) for k, v in study_to_manifests.items() if len(v) > 1}

        return {
            "uncited_sources": uncited_sources,
            "superseded_still_present": superseded_still_present,
            "dge_coverage_gaps": dge_gaps,
            "dge_coverage_gaps_by_field": dge_gaps_field,
            "overlaps": {k: overlaps[k] for k in sorted(overlaps)},
            "counts": {
                "sources": sum(1 for r in self.manifests.values() if r.type == "source-release"),
                "derived": sum(1 for r in self.manifests.values() if r.type == "derived"),
                "indication_configs": len(self.indication_configs),
                "subgroup_catalogs": len({c for cats in self.subgroup_citations.values() for c in cats}),
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


def _load_profiles(root: Path) -> dict[str, dict]:
    """inventories/dataset-intelligence.json -> {manifest_id: profile}.

    The generated enrichment layer (curated `classification:` blocks merged with regex/slug
    inference by data-catalog's dataset_intel_lib) that backs the merged search view for the
    ~490 manifests without a curated block yet. Absent/unreadable is non-fatal — the engine
    still runs on manifests alone (curated blocks read directly off `raw`).
    """
    import json

    path = root / "inventories" / "dataset-intelligence.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return {}
    if not isinstance(data, list):
        return {}
    return {p["manifest_id"]: p for p in data if isinstance(p, dict) and "manifest_id" in p}


# --- disk-persisted CatalogIndex cache -------------------------------------------------------------
# Building the index parses ALL ~442 manifest YAMLs (~0.85s cold). That parse dominates the ~1.1s
# fixed post-read pipeline of EVERY skill run (envelope.py's governance block resolves the run's used
# manifest_ids to their catalog HEAD / content-md5, which loads the whole catalog). The @lru_cache
# below serves the in-process warm path, but each fresh process (a skill CLI run, or a forked
# read-pool worker) pays the cold parse again. So we ALSO persist the built index to a pickle keyed by
# a signature over every catalog input file's (path, size, mtime_ns): a matching cache unpickles in
# ~0.02s instead of re-parsing 442 YAMLs. The cache is CORRECTNESS-SUBORDINATE — any signature miss
# rebuilds, and any cache read/write error fails open to a fresh in-memory build.
_CATALOG_INDEX_CACHE_VERSION = 2  # BUMP on any change to CatalogIndex/ManifestRecord shape or build logic


def _catalog_input_files(root: Path, contracts_root: Path) -> list[Path]:
    """Every on-disk file load_catalog reads, in stable sorted order. The disk-cache validity
    signature is computed over these, so ANY add/remove/edit of a catalog input invalidates a stale
    cached index. Mirrors the exact set the builder + _load_* helpers touch."""
    files: list[Path] = []
    for sub in ("sources", "derived"):
        files += sorted((root / "manifests" / sub).glob("*.yaml"))
    sgc = root / "subgroup-catalogs"
    if sgc.exists():
        files += sorted(sgc.rglob("*.yaml"))
    ic = root / "indication-configs"
    if ic.exists():
        files += sorted(ic.glob("*.yaml"))
    products = contracts_root / "vocabularies" / "products.yaml"
    if products.exists():
        files.append(products)
    # The generated enrichment layer feeds the merged classification view; a regen must invalidate.
    intel = root / "inventories" / "dataset-intelligence.json"
    if intel.exists():
        files.append(intel)
    return files


def _catalog_signature(root: Path, contracts_root: Path) -> str:
    """A cheap, airtight validity fingerprint of the catalog inputs: version + roots + every input
    file's (path, size, mtime_ns). ~450 stat() calls (~0.03s) — an add/remove/edit of any manifest,
    subgroup-catalog, indication-config, or products.yaml changes the digest, so a stale index is
    never served."""
    h = hashlib.sha256()
    h.update(f"v{_CATALOG_INDEX_CACHE_VERSION}\0{root}\0{contracts_root}\0".encode())
    for p in _catalog_input_files(root, contracts_root):
        try:
            st = p.stat()
            h.update(f"{p}\0{st.st_size}\0{st.st_mtime_ns}\0".encode())
        except OSError:
            h.update(f"{p}\0MISSING\0".encode())
    return h.hexdigest()[:16]


def _catalog_cache_dir() -> Path:
    """Where persisted indices live. Override with CATALOG_INDEX_CACHE_DIR; defaults to a temp-dir
    subfolder (per-user, cleared on reboot). NOT inside the data-catalog repo (would need gitignore +
    the root may be read-only in CI)."""
    override = os.environ.get("CATALOG_INDEX_CACHE_DIR")
    return Path(override) if override else Path(tempfile.gettempdir()) / "onc_catalog_index"


def _write_catalog_cache(cache_file: Path, idx: "CatalogIndex") -> None:
    """Atomically persist the index (temp file + os.replace) so a concurrent reader never sees a
    partial pickle, then prune this root's stale-signature pickles. Best-effort: any failure
    (read-only fs, race, pickling issue) is swallowed — the caller already holds the fresh index."""
    try:
        d = cache_file.parent
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".catalog-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:  # index-cache-write: derived memoization artifact, not a catalog file
                pickle.dump(idx, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, cache_file)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        # Prune older cached indices for THIS root (same prefix, different signature). The prefix is
        # root-derived so we never delete a sibling checkout's / CI's valid cache.
        prefix = cache_file.name.rsplit("-", 1)[0]  # "catalog-<roothash>"
        for old in d.glob(f"{prefix}-*.pkl"):
            if old.name != cache_file.name:
                try:
                    old.unlink()
                except OSError:
                    pass
    except Exception:  # noqa: BLE001 — persistence is an optimization, never a correctness gate
        pass


@lru_cache(maxsize=4)
def load_catalog(
    root: Path = DATA_CATALOG,
    contracts_root: Path = TARGET_CONTRACTS,
) -> CatalogIndex:
    """Build the CatalogIndex once (cached per (root, contracts_root)).

    Walks manifests/{sources,derived}/*.yaml, computes the reverse cited_by
    graph from derived_from + subgroup-catalog citations (the single source of
    truth, matching validate_catalog.py), and attaches the products consumer map.

    PERF: the build parses ~442 manifest YAMLs (~0.85s cold). The @lru_cache above serves the
    in-process warm path; ACROSS processes we serve a disk-persisted pickle keyed by
    _catalog_signature (unpickles in ~0.02s). The persisted index is byte-equivalent to a fresh
    build (guarded by test_index_disk_cache.py); any signature miss rebuilds, and any cache
    read/write error fails open to a fresh build. Kill-switch: CATALOG_INDEX_CACHE=0.
    """
    if os.environ.get("CATALOG_INDEX_CACHE") == "0":
        return _build_catalog_index(root, contracts_root)
    try:
        sig = _catalog_signature(root, contracts_root)
        root_hash = hashlib.sha256(f"{root}\0{contracts_root}".encode()).hexdigest()[:8]
        cache_file = _catalog_cache_dir() / f"catalog-{root_hash}-{sig}.pkl"
        if cache_file.exists():
            try:
                with cache_file.open("rb") as f:
                    idx = pickle.load(f)
                if isinstance(idx, CatalogIndex):
                    return idx
            except Exception:  # noqa: BLE001 — corrupt/incompatible pickle → rebuild
                pass
        idx = _build_catalog_index(root, contracts_root)
        _write_catalog_cache(cache_file, idx)
        return idx
    except Exception:  # noqa: BLE001 — the disk cache must NEVER break catalog correctness
        return _build_catalog_index(root, contracts_root)


def _build_catalog_index(
    root: Path = DATA_CATALOG,
    contracts_root: Path = TARGET_CONTRACTS,
) -> CatalogIndex:
    """The uncached build: parse the catalog YAMLs into a CatalogIndex. Called by load_catalog on a
    disk-cache miss (or when the cache is disabled)."""
    manifests: dict[str, ManifestRecord] = {}
    for sub in ("sources", "derived"):
        for path in sorted((root / "manifests" / sub).glob("*.yaml")):
            # Lean parse: skip constructing the heavy, DISCARDED files[] array (per-file md5/size ×
            # thousands of rows) while harvesting the distinct `category` set — the only facet any
            # query reads from it. Byte-identical to _yaml_load + raw.pop('files') + the category set
            # (equivalence guard test), at ~10x less parse time on the big source manifests.
            raw, categories, formats = _lean_load_manifest(path)
            if not raw or "id" not in raw:
                continue
            raw["_categories"] = categories
            raw["_formats"] = formats
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
        profiles=_load_profiles(root),
    )
