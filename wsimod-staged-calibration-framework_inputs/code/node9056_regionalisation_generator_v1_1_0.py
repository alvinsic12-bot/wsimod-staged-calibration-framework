"""Stage-0 v1.1.0: three-stage dominant functional-group regionalisation.

This version reuses the validated v1.0 YAML construction and independent
physical-constraint engine, but replaces pure fraction weighting with the
historical transparent 0.60/0.80 threshold rule.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import node9056_regionalisation_generator_v1_0_0 as base


GENERATOR_VERSION = "1.1.0"


def thresholded_multiplier(
    fractions: pd.DataFrame,
    columns: list[str],
    multiplier_by_column: dict[str, float],
    coverage: pd.Series,
    uncovered_multiplier: float,
    functional_groups: dict[str, list[str]],
    uncovered_group: str,
    mixture_threshold: float,
    dominant_threshold: float,
) -> tuple[pd.Series, pd.DataFrame]:
    mapped = [column for members in functional_groups.values() for column in members]
    if sorted(mapped) != sorted(columns) or len(mapped) != len(set(mapped)):
        missing = sorted(set(columns) - set(mapped))
        duplicate = sorted({column for column in mapped if mapped.count(column) > 1})
        extra = sorted(set(mapped) - set(columns))
        raise RuntimeError(f"Functional-group mapping must cover every fraction once; missing={missing}, duplicate={duplicate}, extra={extra}")

    raw_sum = fractions[columns].sum(axis=1)
    if (raw_sum <= 0).any():
        raise RuntimeError("At least one spatial row has no classified fractions")
    covered_normalised = fractions[columns].div(raw_sum, axis=0)
    coverage = pd.to_numeric(coverage, errors="coerce").fillna(0.0).clip(0.0, 1.0)
    whole = covered_normalised.mul(coverage, axis=0)
    uncovered = 1.0 - coverage

    # Classification confidence follows the historical rule and is calculated
    # within the spatially classified area. Coverage still enters the mixture
    # multiplier separately, with uncovered area assigned the explicit default.
    group_share = pd.DataFrame(index=fractions.index)
    for group, members in functional_groups.items():
        group_share[group] = covered_normalised[members].sum(axis=1)
    if not np.allclose(group_share.sum(axis=1), 1.0, atol=1e-10):
        raise RuntimeError("Functional-group shares do not sum to one")

    mixture = sum(whole[column] * float(multiplier_by_column[column]) for column in columns)
    mixture = mixture + uncovered * float(uncovered_multiplier)
    dominant_group = group_share.idxmax(axis=1)
    dominant_share = group_share.max(axis=1)

    dominant_value = pd.Series(index=fractions.index, dtype=float)
    for index in fractions.index:
        group = dominant_group.loc[index]
        members = functional_groups.get(group, [])
        if not members:
            dominant_value.loc[index] = float(uncovered_multiplier)
            continue
        member_share = covered_normalised.loc[index, members]
        denominator = float(member_share.sum())
        if denominator <= 0:
            dominant_value.loc[index] = float(uncovered_multiplier)
        else:
            dominant_value.loc[index] = sum(
                float(member_share[column]) * float(multiplier_by_column[column]) for column in members
            ) / denominator

    alpha = ((dominant_share - mixture_threshold) / (dominant_threshold - mixture_threshold)).clip(0.0, 1.0)
    stage = np.select(
        [dominant_share < mixture_threshold, dominant_share < dominant_threshold],
        ["mixture_aware", "transitional"],
        default="dominant_functional_behavior",
    )
    final = (1.0 - alpha) * mixture + alpha * dominant_value
    audit = pd.DataFrame({
        "dominant_functional_group": dominant_group,
        "dominant_functional_group_share": dominant_share,
        "threshold_stage": stage,
        "dominant_blend_alpha": alpha,
        "mixture_multiplier": mixture,
        "dominant_multiplier": dominant_value,
        "thresholded_multiplier": final,
    })
    for group in group_share:
        audit[f"functional_group_share__{group}"] = group_share[group]
    return final, audit


def extract_and_weight(soil_path, hydro_path, catchment_index_path, rules):
    soil = pd.read_csv(soil_path, dtype={"wb_id": str})
    hydro = pd.read_csv(hydro_path, dtype={"wb_id": str})
    catchments = pd.read_csv(catchment_index_path, dtype={"wb_id": str})[["wb_id"]].dropna().drop_duplicates()
    soil_spec, hydro_spec = rules["soil"], rules["hydrogeology"]
    soil_columns = base.fraction_columns(soil, soil_spec["fraction_prefix"], soil_spec["fraction_suffix"])
    hydro_columns = base.fraction_columns(hydro, hydro_spec["fraction_prefix"], hydro_spec["fraction_suffix"])
    soil.loc[:, soil_columns] = base.numeric_fraction_frame(soil, soil_columns, str(soil_path))
    hydro.loc[:, hydro_columns] = base.numeric_fraction_frame(hydro, hydro_columns, str(hydro_path))
    if soil["wb_id"].duplicated().any() or hydro["wb_id"].duplicated().any():
        raise RuntimeError("Static source tables must contain one row per wb_id")

    membership = catchments.copy()
    membership["present_in_soil_source"] = membership["wb_id"].isin(set(soil["wb_id"]))
    membership["present_in_hydro_source"] = membership["wb_id"].isin(set(hydro["wb_id"]))
    excluded = membership[~(membership["present_in_soil_source"] & membership["present_in_hydro_source"])].copy()
    excluded["exclusion_reason"] = "model boundary/pseudo catchment without both spatial source records"
    spatial = membership[membership["present_in_soil_source"] & membership["present_in_hydro_source"]][["wb_id"]]
    extracted = spatial.merge(soil, on="wb_id", how="left", validate="one_to_one")
    extracted = extracted.merge(hydro, on="wb_id", how="left", validate="one_to_one", suffixes=("_soil", "_hydro"))

    rule_table = base.expand_rule_table(rules, soil_columns, hydro_columns)
    soil_rule = rule_table[rule_table["domain"].eq("soil")].set_index("fraction_column")
    hydro_rule = rule_table[rule_table["domain"].eq("hydrogeology")].set_index("fraction_column")
    uncovered = float(rules.get("uncovered_area_multiplier", 1.0))
    thresholds = rules["dominance_thresholds"]
    low = float(thresholds["mixture_upper_exclusive"])
    high = float(thresholds["dominant_lower_inclusive"])
    if not (0 < low < high <= 1):
        raise RuntimeError("Dominance thresholds must satisfy 0 < low < high <= 1")

    soil_values = extracted[soil_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    hydro_values = extracted[hydro_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    soil_storage, soil_audit = thresholded_multiplier(
        soil_values, soil_columns, soil_rule["storage_multiplier"].to_dict(), extracted[soil_spec["coverage_column"]],
        uncovered, soil_spec["functional_groups"], soil_spec["uncovered_group"], low, high,
    )
    soil_percolation, soil_audit_2 = thresholded_multiplier(
        soil_values, soil_columns, soil_rule["percolation_multiplier"].to_dict(), extracted[soil_spec["coverage_column"]],
        uncovered, soil_spec["functional_groups"], soil_spec["uncovered_group"], low, high,
    )
    hydro_capacity, hydro_audit = thresholded_multiplier(
        hydro_values, hydro_columns, hydro_rule["capacity_multiplier"].to_dict(), extracted[hydro_spec["coverage_column"]],
        uncovered, hydro_spec["functional_groups"], hydro_spec["uncovered_group"], low, high,
    )
    hydro_residence, hydro_audit_2 = thresholded_multiplier(
        hydro_values, hydro_columns, hydro_rule["residence_time_multiplier"].to_dict(), extracted[hydro_spec["coverage_column"]],
        uncovered, hydro_spec["functional_groups"], hydro_spec["uncovered_group"], low, high,
    )
    if not soil_audit[["dominant_functional_group", "threshold_stage", "dominant_blend_alpha"]].equals(
        soil_audit_2[["dominant_functional_group", "threshold_stage", "dominant_blend_alpha"]]
    ):
        raise RuntimeError("Soil threshold classification changed between parameters")
    if not hydro_audit[["dominant_functional_group", "threshold_stage", "dominant_blend_alpha"]].equals(
        hydro_audit_2[["dominant_functional_group", "threshold_stage", "dominant_blend_alpha"]]
    ):
        raise RuntimeError("Hydrogeology threshold classification changed between parameters")

    extracted["soil_storage_effective_multiplier"] = soil_storage
    extracted["soil_percolation_effective_multiplier"] = soil_percolation
    extracted["groundwater_capacity_effective_multiplier"] = hydro_capacity
    extracted["groundwater_residence_time_effective_multiplier"] = hydro_residence
    extracted["soil_dominant_functional_group"] = soil_audit["dominant_functional_group"].values
    extracted["soil_dominant_share"] = soil_audit["dominant_functional_group_share"].values
    extracted["soil_threshold_stage"] = soil_audit["threshold_stage"].values
    extracted["soil_dominant_blend_alpha"] = soil_audit["dominant_blend_alpha"].values
    extracted["hydro_dominant_class"] = hydro_audit["dominant_functional_group"].values
    extracted["hydro_dominant_share"] = hydro_audit["dominant_functional_group_share"].values
    extracted["hydro_threshold_stage"] = hydro_audit["threshold_stage"].values
    extracted["hydro_dominant_blend_alpha"] = hydro_audit["dominant_blend_alpha"].values
    extracted["weighting_mode"] = "three_stage_functional_group_threshold_0.60_0.80"

    contribution_rows = []
    for index, row in extracted.iterrows():
        for domain, columns, table in [("soil", soil_columns, soil_rule), ("hydrogeology", hydro_columns, hydro_rule)]:
            for column in columns:
                fraction = float(row[column])
                if fraction <= 0:
                    continue
                rule = table.loc[column]
                contribution_rows.append({
                    "wb_id": row["wb_id"], "domain": domain, "fraction_column": column, "fraction": fraction,
                    "rule_status": rule["rule_status"], "storage_multiplier": rule["storage_multiplier"],
                    "percolation_multiplier": rule["percolation_multiplier"], "capacity_multiplier": rule["capacity_multiplier"],
                    "residence_time_multiplier": rule["residence_time_multiplier"],
                    "dominant_group": row["soil_dominant_functional_group"] if domain == "soil" else row["hydro_dominant_class"],
                    "dominant_share": row["soil_dominant_share"] if domain == "soil" else row["hydro_dominant_share"],
                    "threshold_stage": row["soil_threshold_stage"] if domain == "soil" else row["hydro_threshold_stage"],
                })
    return extracted, rule_table, pd.DataFrame(contribution_rows), excluded


if __name__ == "__main__":
    base.GENERATOR_VERSION = GENERATOR_VERSION
    base.extract_and_weight = extract_and_weight
    base.main()
