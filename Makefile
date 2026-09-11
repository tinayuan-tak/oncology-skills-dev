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

.PHONY: dashboard dashboard-dry promote-list profile atlas atlas-check health-check drift-check
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

# health-check : local drift-guard for the framework_health feed only (the fast half of
#                drift-check). Token-free — reads the side-by-side sibling clones, not the network.
#                Fails if health/framework_health.json is stale vs current cross-repo wiring.
health-check:
	python3 validators/framework_health/build_framework_health.py --check --json-only

# drift-check : token-free LOCAL equivalent of the (parked) framework-health-cross-repo CI job — runs
#               BOTH cross-repo staleness guards (framework_health + Living Atlas) against the
#               side-by-side sibling checkouts. Run before landing any cards/ | interpretation-rules/ |
#               resolvers/ | schemas/ | vocabularies/ | health/ change that can move a dashboard feed.
#               Needs all four sibling repos cloned alongside this one (the layout the probes expect);
#               a MISSING sibling silently degrades the probe to a FALSE result, so this target refuses
#               to run unless all four are present. That is also why it must run from the PRIMARY
#               checkout (~/rnd-...-target-contracts), not a /tmp worktree. Regen stale feeds with
#               `make atlas` + `python3 validators/framework_health/build_framework_health.py`.
drift-check:
	@for r in claude-oncology-skills analysis-methods data-products data-catalog; do \
	  test -d "../rnd-computational-biology-oncology-$$r" || { \
	    echo "drift-check: missing sibling clone ../rnd-computational-biology-oncology-$$r"; \
	    echo "  cannot run token-free from here (a missing sibling degrades the probe to a FALSE pass/fail)."; \
	    echo "  run from the primary checkout with all four siblings cloned alongside it."; \
	    exit 2; }; \
	done
	python3 validators/framework_health/build_framework_health.py --check --json-only
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
