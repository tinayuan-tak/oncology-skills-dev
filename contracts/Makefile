# target-contracts — convenience targets.
#
# dashboard : regenerate the output registry + framework health + the Living Architecture
#             Document (the SINGLE canonical dashboard — supersets the old unified dashboard),
#             then publish to S3 (presigned URL) and a dated GitHub release. Needs AWS_PROFILE
#             (e.g. cbg) for S3 + the skill-runs index, and gh auth for the release.
#             Assumes the canonical sibling checkout layout (see framework_health.probe).
#
#   make dashboard                 # full publish
#   make dashboard-dry             # assemble + stamp only, no S3 / gh writes
#   make dashboard AWS_PROFILE=cbg STAMP=2026-08-20T12:00:00Z

STAMP ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
AWS_PROFILE ?= cbg

.PHONY: dashboard dashboard-dry promote-list profile atlas atlas-product atlas-check health-check
# atlas : regenerate the Framework Atlas LOCALLY — the SAME single dashboard
#              `make dashboard` publishes (Overview/Explorer/Health/Cards/Datasets/Coverage +
#              Flow / Gaps / Concepts / Docs + the glossary legibility layer). Writes the
#              committed feed health/framework_atlas.{json,html}. Needs the sibling checkouts.
#   make atlas          # regenerate the committed json + html
#   make atlas-check    # local drift-guard: fail if the committed json is stale
atlas:
	python3 -m validators.architecture_dashboard.living.build_living_doc

atlas-check:
	python3 -m validators.architecture_dashboard.living.build_living_doc --check

# atlas-product : render one standalone per-subskill "product page" HTML per roster skill into
#                 health/product/<skill>.html (the target-invariant five-panel view: verdict spine,
#                 card drill-down, verdict-inert optionality lanes, nomination roll-up, and the
#                 question hierarchy). Reads the COMMITTED health/framework_atlas.json (no siblings
#                 needed) — run `make atlas` first if the feed is stale. Same renderer as the Atlas
#                 Product tab, so the standalone pages never diverge from it.
#   make atlas-product
atlas-product:
	python3 -m validators.architecture_dashboard.living.build_living_doc --all-skills

# health-check : local drift-guard for the framework_health feed only. Token-free — reads
#                the side-by-side sibling clones, not the network. Fails if
#                health/framework_health.json is stale vs current cross-repo wiring.
health-check:
	python3 validators/framework_health/build_framework_health.py --check --json-only

# drift-check was removed 2026-09 (issue #2139): it required all four sibling repos
# cloned side-by-side at ../rnd-computational-biology-oncology-<repo> and always exited 2
# in-tree (that checkout layout no longer exists here). `health-check` above covers the
# token-free framework_health half from a checkout-only runner; for the Living Atlas half
# use `make atlas-check`, which needs the same sibling checkouts as `make atlas`/`dashboard`.

dashboard:
	AWS_PROFILE=$(AWS_PROFILE) python3 -m validators.output_registry.publish_dashboard --generated-at $(STAMP)

dashboard-dry:
	python3 -m validators.output_registry.publish_dashboard --generated-at $(STAMP) --dry-run

# promote-list : show the promotion backlog — target×indication cells that exist only as
#                exploratory runs (no governed evidence package yet). Promote one with
#                `python3 -m validators.output_registry.promote --target T --indication I`.
promote-list:
	python3 -m validators.output_registry.promote --list

# profile : run target-profile for one TARGET/INDICATION and publish its full-profile HTML
#           dashboard (S3 presigned URL + dated gh release). Deterministic by default; add
#           SYNTHESIZE=1 for the Tier-3 LLM narrative (needs BEDROCK_AWS_PROFILE).
#   make profile TARGET=MET INDICATION=COADREAD
profile:
	AWS_PROFILE=$(AWS_PROFILE) python3 -m validators.output_registry.publish_profile \
	  --target $(TARGET) --indication $(INDICATION) --generated-at $(STAMP) $(if $(SYNTHESIZE),--synthesize,)
