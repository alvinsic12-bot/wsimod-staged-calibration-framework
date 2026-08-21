"""Versioned Stage-0 regionalisation generator for the Node 9056 framework.

The generator is deliberately independent of KGE. It performs four auditable
steps: static extraction, fraction weighting, rule-table expansion, and YAML
construction. The original base YAML is never edited.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


GENERATOR_VERSION = "1.0.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(value: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def fraction_columns(frame: pd.DataFrame, prefix: str, suffix: str) -> list[str]:
    return sorted(column for column in frame.columns if column.startswith(prefix) and column.endswith(suffix))


def numeric_fraction_frame(frame: pd.DataFrame, columns: list[str], source_name: str) -> pd.DataFrame:
    if not columns:
        raise RuntimeError(f"No fraction columns found in {source_name}")
    values = frame[columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if ((values < -1e-10) | (values > 1 + 1e-10)).any().any():
        raise RuntimeError(f"Fractions outside [0, 1] in {source_name}")
    return values.clip(0.0, 1.0)


def expand_rule_table(rules: dict, soil_columns: list[str], hydro_columns: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    soil_defaults = rules["soil"]["defaults"]
    soil_overrides = rules["soil"].get("overrides", {})
    for column in soil_columns:
        override = soil_overrides.get(column, {})
        rows.append({
            "domain": "soil",
            "fraction_column": column,
            "class_label": override.get("class_label", "explicit baseline/default class"),
            "storage_multiplier": float(override.get("storage_multiplier", soil_defaults["storage_multiplier"])),
            "percolation_multiplier": float(override.get("percolation_multiplier", soil_defaults["percolation_multiplier"])),
            "capacity_multiplier": np.nan,
            "residence_time_multiplier": np.nan,
            "rule_status": "override" if column in soil_overrides else "explicit_default",
            "rationale": override.get("rationale", "not assigned a directional change; multiplier fixed at 1.0"),
        })
    hydro_defaults = rules["hydrogeology"]["defaults"]
    hydro_overrides = rules["hydrogeology"].get("overrides", {})
    for column in hydro_columns:
        override = hydro_overrides.get(column, {})
        rows.append({
            "domain": "hydrogeology",
            "fraction_column": column,
            "class_label": override.get("class_label", "explicit baseline/default class"),
            "storage_multiplier": np.nan,
            "percolation_multiplier": np.nan,
            "capacity_multiplier": float(override.get("capacity_multiplier", hydro_defaults["capacity_multiplier"])),
            "residence_time_multiplier": float(override.get("residence_time_multiplier", hydro_defaults["residence_time_multiplier"])),
            "rule_status": "override" if column in hydro_overrides else "explicit_default",
            "rationale": override.get("rationale", "not assigned a directional change; multiplier fixed at 1.0"),
        })
    return pd.DataFrame(rows)


def weighted_multiplier(
    fractions: pd.DataFrame,
    columns: list[str],
    multiplier_by_column: dict[str, float],
    coverage: pd.Series,
    uncovered_multiplier: float,
) -> pd.Series:
    covered_sum = fractions[columns].sum(axis=1)
    if (covered_sum <= 0).any():
        bad = fractions.index[covered_sum <= 0].tolist()
        raise RuntimeError(f"Rows with no classified fractions: {bad[:10]}")
    normalised = fractions[columns].div(covered_sum, axis=0)
    covered_effective = sum(normalised[column] * multiplier_by_column[column] for column in columns)
    coverage = pd.to_numeric(coverage, errors="coerce").fillna(0.0).clip(0.0, 1.0)
    return coverage * covered_effective + (1.0 - coverage) * float(uncovered_multiplier)


def extract_and_weight(
    soil_path: Path,
    hydro_path: Path,
    catchment_index_path: Path,
    rules: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    soil = pd.read_csv(soil_path, dtype={"wb_id": str})
    hydro = pd.read_csv(hydro_path, dtype={"wb_id": str})
    catchments = pd.read_csv(catchment_index_path, dtype={"wb_id": str})[["wb_id"]].dropna().drop_duplicates()
    if catchments["wb_id"].duplicated().any():
        raise RuntimeError("Catchment index contains duplicate wb_id values")

    soil_spec = rules["soil"]
    hydro_spec = rules["hydrogeology"]
    soil_columns = fraction_columns(soil, soil_spec["fraction_prefix"], soil_spec["fraction_suffix"])
    hydro_columns = fraction_columns(hydro, hydro_spec["fraction_prefix"], hydro_spec["fraction_suffix"])
    soil_values = numeric_fraction_frame(soil, soil_columns, str(soil_path))
    hydro_values = numeric_fraction_frame(hydro, hydro_columns, str(hydro_path))
    soil.loc[:, soil_columns] = soil_values
    hydro.loc[:, hydro_columns] = hydro_values

    if soil["wb_id"].duplicated().any() or hydro["wb_id"].duplicated().any():
        raise RuntimeError("Static source tables must contain one row per wb_id")
    source_membership = catchments.copy()
    source_membership["present_in_soil_source"] = source_membership["wb_id"].isin(set(soil["wb_id"]))
    source_membership["present_in_hydro_source"] = source_membership["wb_id"].isin(set(hydro["wb_id"]))
    excluded = source_membership[
        ~(source_membership["present_in_soil_source"] & source_membership["present_in_hydro_source"])
    ].copy()
    excluded["exclusion_reason"] = "model boundary/pseudo catchment without both spatial source records"
    catchments = source_membership[
        source_membership["present_in_soil_source"] & source_membership["present_in_hydro_source"]
    ][["wb_id"]].copy()

    extracted = catchments.merge(soil, on="wb_id", how="left", validate="one_to_one")
    extracted = extracted.merge(hydro, on="wb_id", how="left", validate="one_to_one", suffixes=("_soil", "_hydro"))
    missing_soil = extracted[soil_columns].isna().all(axis=1)
    missing_hydro = extracted[hydro_columns].isna().all(axis=1)
    if missing_soil.any() or missing_hydro.any():
        raise RuntimeError(
            "Missing static fractions for model catchments: "
            f"soil={extracted.loc[missing_soil, 'wb_id'].tolist()}, "
            f"hydro={extracted.loc[missing_hydro, 'wb_id'].tolist()}"
        )

    rule_table = expand_rule_table(rules, soil_columns, hydro_columns)
    soil_rule = rule_table[rule_table["domain"].eq("soil")].set_index("fraction_column")
    hydro_rule = rule_table[rule_table["domain"].eq("hydrogeology")].set_index("fraction_column")
    uncovered = float(rules.get("uncovered_area_multiplier", 1.0))
    soil_fraction_values = extracted[soil_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    hydro_fraction_values = extracted[hydro_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    extracted["soil_storage_effective_multiplier"] = weighted_multiplier(
        soil_fraction_values, soil_columns, soil_rule["storage_multiplier"].to_dict(),
        extracted[soil_spec["coverage_column"]], uncovered,
    )
    extracted["soil_percolation_effective_multiplier"] = weighted_multiplier(
        soil_fraction_values, soil_columns, soil_rule["percolation_multiplier"].to_dict(),
        extracted[soil_spec["coverage_column"]], uncovered,
    )
    extracted["groundwater_capacity_effective_multiplier"] = weighted_multiplier(
        hydro_fraction_values, hydro_columns, hydro_rule["capacity_multiplier"].to_dict(),
        extracted[hydro_spec["coverage_column"]], uncovered,
    )
    extracted["groundwater_residence_time_effective_multiplier"] = weighted_multiplier(
        hydro_fraction_values, hydro_columns, hydro_rule["residence_time_multiplier"].to_dict(),
        extracted[hydro_spec["coverage_column"]], uncovered,
    )
    extracted["weighting_mode"] = "fraction_with_explicit_uncovered_default"

    audit_rows: list[dict] = []
    for row in extracted.itertuples(index=False):
        for domain, columns, table in [
            ("soil", soil_columns, soil_rule),
            ("hydrogeology", hydro_columns, hydro_rule),
        ]:
            for column in columns:
                fraction = float(getattr(row, column))
                if fraction <= 0:
                    continue
                rule = table.loc[column]
                audit_rows.append({
                    "wb_id": row.wb_id,
                    "domain": domain,
                    "fraction_column": column,
                    "fraction": fraction,
                    "rule_status": rule["rule_status"],
                    "storage_multiplier": rule["storage_multiplier"],
                    "percolation_multiplier": rule["percolation_multiplier"],
                    "capacity_multiplier": rule["capacity_multiplier"],
                    "residence_time_multiplier": rule["residence_time_multiplier"],
                })
    return extracted, rule_table, pd.DataFrame(audit_rows), excluded


def match_wfd(node_name: str, wfds: list[str]) -> str | None:
    matches = [wfd for wfd in wfds if wfd in str(node_name)]
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous WFD match for node {node_name}: {matches}")
    return matches[0] if matches else None


def iter_surfaces(node: dict):
    surfaces = node.get("surfaces", {})
    if isinstance(surfaces, dict):
        yield from surfaces.items()
    else:
        for index, surface in enumerate(surfaces):
            yield str(surface.get("surface", index)), surface


def apply_multiplier(target: dict, parameter: str, multiplier: float) -> tuple[float, float]:
    if parameter not in target:
        raise KeyError(parameter)
    old = float(target[parameter])
    new = old * float(multiplier)
    target[parameter] = new
    return old, new


def physical_constraint_failures(config: dict) -> list[dict]:
    failures: list[dict] = []
    for node_name, node in config.get("nodes", {}).items():
        node_type = node.get("type_")
        if node_type == "Land":
            for surface_name, surface in iter_surfaces(node):
                if all(key in surface for key in ["wilting_point", "field_capacity", "total_porosity"]):
                    wp, fc, tp = (float(surface[key]) for key in ["wilting_point", "field_capacity", "total_porosity"])
                    if not (0 < wp < fc < tp <= 1):
                        failures.append({"node": node_name, "surface": surface_name, "failure": "not 0 < wilting_point < field_capacity < total_porosity <= 1"})
                if "percolation_coefficient" in surface and not (0 <= float(surface["percolation_coefficient"]) <= 1):
                    failures.append({"node": node_name, "surface": surface_name, "failure": "percolation_coefficient outside [0, 1]"})
        elif node_type == "Groundwater":
            capacity = float(node["capacity"])
            initial = float(node["initial_storage"])
            residence = float(node["residence_time"])
            if not (capacity > 0 and 0 <= initial <= capacity and residence > 0):
                failures.append({"node": node_name, "surface": "", "failure": "invalid groundwater storage or residence time"})
    return failures


def construct_configs(
    base_config: dict, weighted: pd.DataFrame, rules: dict, output_dir: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_wfd = weighted.set_index("wb_id")
    wfds = sorted(by_wfd.index.astype(str))
    composition = rules["scenario_composition"]
    component_parameters = {
        "soil_storage": ("Land", ["wilting_point", "field_capacity", "total_porosity"], "soil_storage_effective_multiplier"),
        "soil_percolation": ("Land", ["percolation_coefficient"], "soil_percolation_effective_multiplier"),
        "groundwater_capacity": ("Groundwater", ["capacity", "initial_storage"], "groundwater_capacity_effective_multiplier"),
        "groundwater_residence_time": ("Groundwater", ["residence_time"], "groundwater_residence_time_effective_multiplier"),
    }
    labels = {
        "R01": "soil_type_regionalised_storage",
        "R02": "soil_type_regionalised_percolation",
        "R03": "hydrogeology_regionalised_groundwater_capacity",
        "R04": "soil_storage_plus_percolation",
        "R05": "storage_percolation_groundwater_capacity",
        "R06": "hydrogeology_regionalised_residence_time",
        "R07": "full_framework_plus_residence_time",
    }
    change_rows: list[dict] = []
    constraint_rows: list[dict] = []
    configs_dir = output_dir / "configs"
    for rule_id, components in composition.items():
        config = copy.deepcopy(base_config)
        for node_name, node in config.get("nodes", {}).items():
            wfd = match_wfd(node_name, wfds)
            if wfd is None:
                continue
            for component in components:
                expected_type, parameters, multiplier_column = component_parameters[component]
                if node.get("type_") != expected_type:
                    continue
                multiplier = float(by_wfd.loc[wfd, multiplier_column])
                targets = list(iter_surfaces(node)) if expected_type == "Land" else [("", node)]
                for surface_name, target in targets:
                    for parameter in parameters:
                        if parameter not in target:
                            continue
                        old, new = apply_multiplier(target, parameter, multiplier)
                        change_rows.append({
                            "rule_id": rule_id,
                            "component": component,
                            "wb_id": wfd,
                            "node": node_name,
                            "surface": surface_name,
                            "parameter": parameter,
                            "effective_multiplier": multiplier,
                            "old_value": old,
                            "new_value": new,
                        })
        failures = physical_constraint_failures(config)
        constraint_rows.append({
            "rule_id": rule_id,
            "constraint_engine": f"independent_physical_constraint_engine_v{GENERATOR_VERSION}",
            "constraints": "soil ordering and bounds; percolation [0,1]; groundwater capacity/initial/residence bounds",
            "passed": not failures,
            "failure_count": len(failures),
            "failure_details_json": json.dumps(failures, sort_keys=True),
        })
        if failures:
            raise RuntimeError(f"{rule_id} violates physical constraints: {failures[:5]}")
        write_yaml(config, configs_dir / f"{rule_id}_{labels[rule_id]}.yml")
    return pd.DataFrame(change_rows), pd.DataFrame(constraint_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-config", required=True, type=Path)
    parser.add_argument("--soil-fractions", required=True, type=Path)
    parser.add_argument("--hydro-fractions", required=True, type=Path)
    parser.add_argument("--catchment-index", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in [args.base_config, args.soil_fractions, args.hydro_fractions, args.catchment_index, args.rules]:
        if not path.exists():
            raise FileNotFoundError(path)
    rules = read_yaml(args.rules)
    if str(rules.get("generator_version")) != GENERATOR_VERSION:
        raise RuntimeError("Rule-table generator_version does not match this generator")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = args.output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    weighted, expanded_rules, contribution_audit, excluded_catchments = extract_and_weight(
        args.soil_fractions, args.hydro_fractions, args.catchment_index, rules
    )
    excluded_catchments.to_csv(tables_dir / "00_excluded_nonspatial_model_catchments.csv", index=False)
    weighted.to_csv(tables_dir / "01_static_extraction_and_effective_multipliers.csv", index=False)
    expanded_rules.to_csv(tables_dir / "02_expanded_class_fraction_rule_table.csv", index=False)
    contribution_audit.to_csv(tables_dir / "03_fraction_contribution_audit.csv", index=False)
    change_log, constraint_audit = construct_configs(read_yaml(args.base_config), weighted, rules, args.output_dir)
    change_log.to_csv(tables_dir / "04_R01_R07_yaml_change_log.csv", index=False)
    constraint_audit.to_csv(tables_dir / "05_independent_physical_constraint_audit.csv", index=False)

    outputs = sorted((args.output_dir / "configs").glob("R*.yml"))
    if len(outputs) != 7:
        raise RuntimeError(f"Expected 7 regionalised YAMLs, found {len(outputs)}")
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "schema_version": str(rules.get("schema_version")),
        "weighting_mode": str(rules.get("weighting_mode")),
        "dominance_thresholds": rules.get("dominance_thresholds", {}),
        "sources": {str(path): sha256(path) for path in [args.base_config, args.soil_fractions, args.hydro_fractions, args.catchment_index, args.rules]},
        "model_catchment_count": int(weighted["wb_id"].nunique()),
        "excluded_nonspatial_model_catchments": excluded_catchments["wb_id"].astype(str).tolist(),
        "yaml_change_rows": int(len(change_log)),
        "physical_constraint_engine": {
            "independent_from_regionalisation_rules": True,
            "scenario_count": int(len(constraint_audit)),
            "all_passed": bool(constraint_audit["passed"].all()),
            "audit_table": str(tables_dir / "05_independent_physical_constraint_audit.csv"),
        },
        "outputs": {path.name: sha256(path) for path in outputs},
    }
    (args.output_dir / "GENERATOR_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
