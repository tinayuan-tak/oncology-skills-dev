#!/usr/bin/env python3
"""paralog_genetic_interaction CLI — per-target combinatorial-KO genetic-interaction lookup.

Thin debug/batch entrypoint over the reader. The card path calls the reader functions
directly; this CLI is for spot-checks and batch dumps.

Usage:
    python -m methods.paralog_genetic_interaction.cli --target CDK4
    python -m methods.paralog_genetic_interaction.cli --target SMARCA2 --partner SMARCA4 --lineage
"""

from __future__ import annotations

import json

import click

from methods.paralog_genetic_interaction.read import (
    combinatorial_dependency_for_gene,
    lineage_breakdown_for_pair,
)


@click.command()
@click.option("--target", required=True, help="Target gene symbol (HGNC).")
@click.option("--partner", default=None, help="Partner gene symbol — with --lineage, show per-lineage GI.")
@click.option("--lineage", is_flag=True, help="Show the per-lineage breakdown for --target/--partner.")
def main(target: str, partner: str, lineage: bool) -> None:
    if lineage:
        if not partner:
            raise click.UsageError("--lineage requires --partner")
        click.echo(json.dumps(lineage_breakdown_for_pair(target, partner), indent=2))
        return
    click.echo(json.dumps(combinatorial_dependency_for_gene(target), indent=2))


if __name__ == "__main__":
    main()
