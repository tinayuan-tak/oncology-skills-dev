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

.PHONY: dashboard dashboard-dry
dashboard:
	AWS_PROFILE=$(AWS_PROFILE) python3 -m validators.output_registry.publish_dashboard --generated-at $(STAMP)

dashboard-dry:
	python3 -m validators.output_registry.publish_dashboard --generated-at $(STAMP) --dry-run
