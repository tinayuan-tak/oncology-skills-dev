"""depmap_predictability_precompute — batch precompute pipeline for E5.

Trains a per-gene RandomForestRegressor on (own_expression + own_copy_number +
own_mut_hotspot + own_mut_damaging + lineage_one_hot) features to predict
Chronos dependency. Output: a frozen derived parquet on S3, one row per gene,
used by the thin `depmap_predictability` lookup card method.

This method has NO live-read role; it produces a data product. See README in
the data-catalog manifest for the schema.
"""
