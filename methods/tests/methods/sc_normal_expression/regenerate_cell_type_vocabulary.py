"""Regenerate the pinned cell-type vocabulary snapshot used by test_essential_prefix_vocabulary.py.

    AWS_PROFILE=cbg env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
        python tests/methods/sc_normal_expression/regenerate_cell_type_vocabulary.py

Not a test and not run by the suite (no `test_` prefix): it needs live S3. Run it when a shard
release lands, then read the diff — a shard that GAINS labels can make a previously-inert
safety-essential entry live, and a shard that RENAMES labels can make a live entry inert. Both are
silent in the entry list itself, which is the whole reason this snapshot exists.

Two deliberate properties, both learned the hard way:

  * NO row filter and only a 2-column projection. An earlier probe of this vocabulary reused a
    gene-filtered backtest cache; concluding "this label is absent" from a gene-filtered subset is
    an absence-assertion measured through the wrong aperture.
  * EXPLICIT credential injection, mirroring read.read_gene_celltype_rows (read.py:160-172). An
    implicit botocore chain silently falls back to a role that lacks GetObject on onc-compbio, and
    on SageMaker AWS_CONTAINER_CREDENTIALS_RELATIVE_URI outranks AWS_PROFILE — hence the `env -u`.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import boto3
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from methods.sc_normal_expression import read as rd

SNAPSHOT = pathlib.Path(__file__).with_name("sc_normal_cell_type_vocabulary_20260918.json")


def main() -> None:
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", rd.DEFAULT_AWS_PROFILE))
    creds = session.get_credentials().get_frozen_credentials()
    fs = pafs.S3FileSystem(
        region="us-east-1",
        access_key=creds.access_key,
        secret_key=creds.secret_key,
        session_token=creds.token,
    )

    shards: dict[str, list[str]] = {}
    for tissue in rd.TISSUE_TO_PRODUCT:
        key = rd._s3_key(tissue)
        if not key:
            print(f"  SKIP {tissue}: no s3 key")
            continue
        table = pq.read_table(f"{rd.S3_BUCKET}/{key}", filesystem=fs, columns=["cell_type"])
        labels = sorted({str(x) for x in table.column("cell_type").to_pylist()})
        shards[tissue] = labels
        print(f"  {tissue:18s} rows={table.num_rows:8d}  distinct cell types={len(labels):4d}")

    distinct = set().union(*shards.values())
    print(f"\nTOTAL distinct labels across {len(shards)} shards: {len(distinct)}")

    prior = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {"shards": {}}
    prior_distinct = set().union(*prior["shards"].values()) if prior["shards"] else set()
    print(f"  ADDED since snapshot   ({len(distinct - prior_distinct)}): {sorted(distinct - prior_distinct)}")
    print(f"  REMOVED since snapshot ({len(prior_distinct - distinct)}): {sorted(prior_distinct - distinct)}")

    payload = dict(prior)
    payload["_provenance"] = dict(prior.get("_provenance", {}))
    payload["_provenance"].update(
        measured_utc=subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        n_shards=len(shards),
        n_distinct_labels=len(distinct),
    )
    payload["shards"] = {k: shards[k] for k in sorted(shards)}
    with SNAPSHOT.open("w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=False)
        fh.write("\n")
    print(f"\nwrote {SNAPSHOT}")


if __name__ == "__main__":
    main()
