# target-contracts — convenience targets.
#
# dashboard : regenerate the output registry + framework health + unified dashboard, then
#             publish to S3 (presigned URL) and a dated GitHub release. Needs AWS_PROFILE
#             (e.g. cbg) for S3 + the skill-runs index, and gh auth for the release.
#             Assumes the canonical sibling checkout layout (see framework_health.probe).
#
#   make dashboard                 # full publish
#   make dashboard-dry             # assemble + stamp only, no S3 / gh writes
#   make dashboard AWS_PROFILE=cbg STAMP=2026-08-20T12:00:00Z

STAMP ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
AWS_PROFILE ?= cbg

.PHONY: dashboard dashboard-dry promote-list profile living-doc living-doc-check
# living-doc : regenerate the Living Architecture Document (superset of the unified dashboard:
#              + Gaps / Concepts / Docs tabs + the glossary legibility layer). Writes the
#              committed feed health/living_doc.{json,html}. Needs the sibling checkouts.
#   make living-doc          # regenerate the committed json + html
#   make living-doc-check    # local drift-guard: fail if the committed json is stale
living-doc:
	python3 -m validators.architecture_dashboard.living.build_living_doc

living-doc-check:
	python3 -m validators.architecture_dashboard.living.build_living_doc --check

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
