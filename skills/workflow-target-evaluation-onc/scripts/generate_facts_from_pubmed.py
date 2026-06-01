#!/usr/bin/env python3
"""Generate {GENE}_risk_assessment_facts.yaml from PubMed via LLM.

The v1.4.0 Step 0 generator. Closes the last hand-writing gap in the
oncology target-evaluation workflow.

Pipeline:
  1. PubMed E-utilities — 6 per-category searches → abstracts
  2. Sonnet (Anthropic Bedrock) — per-abstract claim extraction
  3. Opus (Anthropic Bedrock) — synthesis to facts.yaml shape
  4. Strict load_facts() validation → write to disk + provenance log

Usage:
    pixi run python scripts/generate_facts_from_pubmed.py \\
        --gene PCDH7 --disease nsclc \\
        --output-dir /path/to/PCDH7 \\
        [--modality "T-cell engager"]

Outputs:
    {GENE}_risk_assessment_facts.yaml      validated + canonical
    {GENE}_extraction_log.json             provenance (PubMed counts,
                                           token usage per stage)

Exit codes:
    0  — success
    1  — input validation error (bad disease, etc.)
    2  — Bedrock auth failure (run `aws sso login --profile cmp-dev`)
    3  — output failed strict validation (LLM produced invalid output)
    4  — output file already exists (use --force to overwrite)
    5  — file system error
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import date as _date
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from integrated_report.bedrock_client import (  # noqa: E402
    BedrockAuthError, ModelConfig, get_bedrock_client,
)
from integrated_report.extract_claims import extract_claims  # noqa: E402
from integrated_report.pubmed_search import search_pubmed  # noqa: E402
from integrated_report.risk_assessment_renderer import load_facts  # noqa: E402
from integrated_report.synthesize_facts import synthesize_facts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Generate risk_assessment_facts.yaml from PubMed via LLM.'
    )
    parser.add_argument('--gene', required=True, help='Gene symbol (e.g. PCDH7)')
    parser.add_argument('--disease', required=True, choices=['crc', 'nsclc'])
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='Where {GENE}_risk_assessment_facts.yaml will be written.')
    parser.add_argument('--modality', default=None,
                        help='Therapeutic modality (informational; included in facts.yaml).')
    parser.add_argument('--target-aliases', default='',
                        help='Optional gene aliases / HGNC ID for the target_aliases field.')
    parser.add_argument('--abstracts-per-category', type=int, default=10,
                        help='Cap on PubMed results per category (default: 10).')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite an existing facts.yaml.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run extraction; print outcome but do not write.')
    parser.add_argument('--max-synth-retries', type=int, default=3,
                        help='Max Stage 2 (Opus synthesis) retries on '
                             'load_facts() validation failure (default: 3). '
                             'Each retry passes the validation error back to '
                             'Opus so it can correct field placement. Set 0 '
                             'to fail-fast (useful for debugging).')
    args = parser.parse_args()

    out_dir: Path = args.output_dir
    if not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)

    facts_path = out_dir / f'{args.gene}_risk_assessment_facts.yaml'
    if facts_path.exists() and not args.force and not args.dry_run:
        sys.stderr.write(
            f'ERROR: {facts_path} already exists. Use --force to overwrite.\n'
        )
        return 4

    log_path = out_dir / f'{args.gene}_extraction_log.json'
    log: dict[str, object] = {
        'gene': args.gene,
        'disease': args.disease,
        'modality': args.modality,
        'started_at': _date.today().isoformat(),
        'stages': {},
    }

    # ------------------------------------------------------------------
    # Stage 0: PubMed
    # ------------------------------------------------------------------
    print(f'Stage 0: searching PubMed for {args.gene} in {args.disease} '
          f'({args.abstracts_per_category}/category)...')
    t0 = time.time()
    try:
        search_result = search_pubmed(
            args.gene, args.disease,
            abstracts_per_category=args.abstracts_per_category,
        )
    except Exception as e:
        sys.stderr.write(f'ERROR: PubMed search failed: {e}\n')
        return 1
    pubmed_secs = time.time() - t0
    counts = {
        cat: len(abs_list)
        for cat, abs_list in search_result.abstracts_by_category.items()
    }
    total_abstracts = sum(counts.values())
    log['stages']['pubmed'] = {
        'duration_s': round(pubmed_secs, 2),
        'abstracts_per_category': counts,
        'total_abstracts': total_abstracts,
        'unique_pmids': len(search_result.all_pmids),
    }
    print(f'  Got {total_abstracts} abstracts ({len(search_result.all_pmids)} unique)'
          f' in {pubmed_secs:.1f}s.')
    for cat, n in counts.items():
        print(f'    {cat}: {n}')

    if total_abstracts == 0:
        sys.stderr.write(
            'ERROR: PubMed returned zero abstracts across all 6 categories. '
            'Check gene symbol spelling.\n'
        )
        return 1

    # ------------------------------------------------------------------
    # Bedrock client (single instance, shared across Stages 1+2)
    # ------------------------------------------------------------------
    try:
        client = get_bedrock_client()
        cfg = ModelConfig.from_env()
    except BedrockAuthError as e:
        sys.stderr.write(f'\n{e}\n')
        return 2
    except Exception as e:
        sys.stderr.write(f'ERROR: Bedrock client init failed: {e}\n')
        return 2
    print(f'  Bedrock models: extract={cfg.extraction_model}, '
          f'synth={cfg.synthesis_model}')

    # ------------------------------------------------------------------
    # Stage 1: extract claims
    # ------------------------------------------------------------------
    print('Stage 1: extracting claims via Sonnet...')
    t1 = time.time()
    try:
        extractions = extract_claims(
            search_result, client=client, model_config=cfg,
        )
    except Exception as e:
        sys.stderr.write(f'ERROR: claim extraction failed: {e}\n')
        traceback.print_exc()
        return 2
    extract_secs = time.time() - t1
    extract_counts = {
        cat: len(ce.claims) for cat, ce in extractions.items()
    }
    total_claims = sum(extract_counts.values())
    log['stages']['extract_claims'] = {
        'duration_s': round(extract_secs, 2),
        'claims_per_category': extract_counts,
        'total_claims': total_claims,
        'model': cfg.extraction_model,
    }
    print(f'  Extracted {total_claims} claims in {extract_secs:.1f}s.')
    for cat, n in extract_counts.items():
        print(f'    {cat}: {n}')

    # ------------------------------------------------------------------
    # Stage 2: synthesize facts (with retry-on-validation-failure)
    # ------------------------------------------------------------------
    print('Stage 2: synthesizing facts via Opus...')
    t2 = time.time()
    tmp_path = out_dir / f'.{args.gene}_facts_tmp.yaml'
    feedback: str | None = None
    facts: dict[str, object] | None = None
    last_validation_error: str | None = None
    attempts_used = 0
    for attempt in range(args.max_synth_retries + 1):
        attempts_used = attempt + 1
        if attempt == 0:
            print(f'  Attempt {attempt + 1}/{args.max_synth_retries + 1} '
                  f'(initial)...')
        else:
            print(f'  Attempt {attempt + 1}/{args.max_synth_retries + 1} '
                  f'(retry with validation feedback)...')
        try:
            candidate = synthesize_facts(
                gene=args.gene, disease=args.disease,
                extractions=extractions,
                modality=args.modality,
                target_aliases=args.target_aliases,
                modality_candidates=[args.modality] if args.modality else [],
                client=client, model_config=cfg,
                feedback=feedback,
            )
        except Exception as e:
            sys.stderr.write(f'ERROR: synthesis failed: {e}\n')
            traceback.print_exc()
            return 2
        # Probe-validate via load_facts before accepting.
        tmp_path.write_text(yaml.safe_dump(
            candidate, sort_keys=False, allow_unicode=True,
        ))
        try:
            load_facts(tmp_path)
            facts = candidate
            last_validation_error = None
            break
        except ValueError as e:
            last_validation_error = str(e)
            feedback = last_validation_error
            print(f'    Validation failed: {last_validation_error}')
    if facts is None:
        sys.stderr.write(
            f'ERROR: synthesized facts failed strict validation after '
            f'{attempts_used} attempt(s):\n  {last_validation_error}\n'
            f'  Tmp file preserved for inspection: {tmp_path}\n'
        )
        return 3
    # Success — clean up the tmp probe file.
    if tmp_path.exists():
        tmp_path.unlink()
    synth_secs = time.time() - t2
    log['stages']['synthesize_facts'] = {
        'duration_s': round(synth_secs, 2),
        'model': cfg.synthesis_model,
        'attempts': attempts_used,
        'max_retries_configured': args.max_synth_retries,
    }
    print(f'  Synthesized facts in {synth_secs:.1f}s '
          f'(attempts: {attempts_used}/{args.max_synth_retries + 1}).')
    print('  ✓ Output validates cleanly.')

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    if args.dry_run:
        print(f'  --dry-run: NOT writing to {facts_path}')
        print(f'  Stages summary:')
        for stage, info in log['stages'].items():
            print(f'    {stage}: {info}')
        return 0

    facts_path.write_text(yaml.safe_dump(
        facts, sort_keys=False, allow_unicode=True, width=100,
    ))
    log_path.write_text(json.dumps(log, indent=2))
    print(f'\nWrote: {facts_path}')
    print(f'  Provenance: {log_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
