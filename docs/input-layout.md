# Portable WSIMOD staged calibration framework input layout

The notebook does not use the original author's directories. Create a project folder anywhere, set `WSIMOD_STAGED_CALIBRATION_FRAMEWORK_ROOT` to it (or start Jupyter in that folder), and place inputs under this layout. The literal filenames below are portable aliases; they can be copied or renamed from equivalent source data.

```text
<V220_PROJECT_ROOT>/
├── wsimod-staged-calibration-framework_inputs/
│   ├── wsimod-staged-calibration-framework_input_manifest.json
│   ├── baseline/
│   │   ├── corrected_wwtw_routing_baseline.yml
│   │   └── confirmed_wwtw_routing_change_log.csv
│   ├── code/
│   │   ├── node9056_regionalisation_generator_v1_0_0.py
│   │   ├── node9056_regionalisation_generator_v1_1_0.py
│   │   └── regionalisation_rules_v1_1_0.yml
│   ├── mappings/
│   │   ├── official_station_arc_mapping.csv
│   │   └── catchment_outlets.csv
│   ├── model_node_9056/
│   │   ├── config.yml
│   │   ├── unified_data.parquet
│   │   └── visualisation_node_9056/
│   │       ├── model_arcs_index.csv
│   │       └── catchment_model_run_index.csv
│   ├── observations/
│   │   ├── flow/                 # one compatible flow-observation file per catchment
│   │   └── nitrate/              # one compatible nitrate-observation file per catchment
│   ├── static_data/
│   │   ├── soilscapes_fractions.csv
│   │   └── hydrogeology_fractions.csv
│   ├── wsimod_source/            # checked-out WSIMOD source tree containing wsimod/
│   └── wwtw/
│       └── candidate_wwtw_nitrate_parameter_manifest.csv
└── wsimod-staged-calibration-framework_outputs/  # created by the notebook
```

The required columns and semantics remain those enforced by the notebook's existing audits. `wsimod-staged-calibration-framework_input_manifest.json` records dataset provenance, acquisition date, optional checksums and any permitted source-to-alias rename. It is required so that a reproduction can state exactly which input version it used.

The notebook checks every required input path before it generates a scenario. It also hashes immutable inputs before and after simulation, so a changed baseline, mapping, regionalisation rule, model source or static-data file stops the run rather than silently mixing versions.
