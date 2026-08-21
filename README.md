# WSIMOD staged calibration framework

This repository reproduces the two-phase workflow used in the dissertation: evidence-informed **pre-processing**, separate-domain **Phase A**, combined-intensity **Phase B**, then catchment-level assessment and untouched validation. It intentionally contains no later calibration stage.

## Quick start

```powershell
conda env create -f environment.yml
conda activate wsimod-staged-calibration-framework
python scripts/verify_inputs.py
jupyter lab
```

Open `notebooks/wsimod-staged-calibration-framework.ipynb` and run cells from top to bottom. The notebook finds the repository root automatically when launched from either the repository root or `notebooks/`; alternatively set `WSIMOD_STAGED_CALIBRATION_FRAMEWORK_ROOT` to the repository root.

## Repository contents

- `notebooks/`: executable framework notebook, with code comments mapping each step to dissertation Sections 2.1–2.7.
- `wsimod-staged-calibration-framework_inputs/`: all model, mapping, static, observation and WSIMOD source files read by the notebook.
- `scripts/verify_inputs.py`: SHA-256 verification against the committed data manifest.
- `docs/`: input layout, provenance notes, and a Chinese step-by-step GitHub upload guide.
- `wsimod-staged-calibration-framework_outputs/`: generated on execution and deliberately ignored by Git.

See `docs/input-layout.md` for the exact portable aliases used by the notebook. The original external-data licences and attribution obligations still apply; see `docs/data-provenance.md` before making this repository public.

For the first private-GitHub upload, follow `docs/github-upload.md`.
