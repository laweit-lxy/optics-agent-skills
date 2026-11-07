# optics-agent-skills

[![regression](https://github.com/laweit-lxy/optics-agent-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/laweit-lxy/optics-agent-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Agent skills for optical design that you can check. An AI coding agent (Claude Code, Codex, an MCP client, or anything that reads `SKILL.md`) gets pinned, open-source optics engines, strict read-only handling of your lens files, a second engine that independently re-derives the numbers, and a diagnosis that explains why the engines disagree.

| Skill | Engine | What it does |
| --- | --- | --- |
| [`design-optical-systems`](skills/design-optical-systems/SKILL.md) | [Optiland](https://github.com/optiland/optiland) 0.6.3 | Analyzes a sequential `.zmx` prescription: EFL, F-number, spot, OPD, FFT PSF/MTF, radius sensitivity. Qualifies itself against fixed Cooke, Double-Gauss and Hubble references on every run. |
| [`cross-check-optical-designs`](skills/cross-check-optical-designs/SKILL.md) | [RayOptics](https://github.com/mjhoptics/ray-optics) @ `e25bc57` | Independently loads the same `.zmx`, audits surfaces, stop, fields and glass-catalog resolution, and compares EFL, paraxial and real working F-number against an Optiland or OpticStudio report. Returns `PASS`, `MISMATCH` or `FAIL`. |
| [`diagnose-optical-discrepancies`](skills/diagnose-optical-discrepancies/SKILL.md) | Optiland + RayOptics | Explains a disagreement: compares the prescription each engine built, first-order values and real rays, then runs elimination experiments (glass catalog, object distance, ray aiming). Returns `AGREE`, `EXPLAINED` or `UNRESOLVED` with confirmed causes. |
| [`analyze-optical-designs`](skills/analyze-optical-designs/SKILL.md) | [Chromatix](https://github.com/chromatix-team/chromatix) + [Prysm](https://github.com/brandondube/prysm) (JAX) | Scalar wave optics: Fresnel/Fraunhofer/angular-spectrum propagation, pupil- and Zernike-based PSF/MTF/OTF, differentiable inverse design. Qualifies against analytic Airy, Strehl and MTF results. |

## Why cross-check, and why diagnose

Every lens-design program imports a `.zmx` file a little differently. A single engine reporting a number is not evidence. Here three engines meet on the same prescriptions, and the diagnosis traces every difference to a cause it can reproduce:

| Sample | OpticStudio 22.2.2 EFL (mm) | RayOptics EFL (mm) | Optiland EFL (mm) | Diagnosis |
| --- | --- | --- | --- | --- |
| Cooke triplet | 50.000394 | 50.000394 | 49.999783 | The file declares `GCAT HIKARI SCHOTT`. OpticStudio and RayOptics take F2 from Hikari, Optiland from Schott (index Δ ≈ 4.6e-6). With Hikari F2, Optiland gives 50.000394 mm. |
| Double-Gauss | 100.003748 | 100.003748 | 100.003748 | Four glasses resolve to different catalogs with no first-order effect. |
| Hubble | 57600.081 | 57600.081 | 57600.081 | RayOptics puts the infinite object at 1e10 mm. That shifts the image by f²/z = 0.33 mm and moves the F/24 edge rays by 6.9 µm and the working F-number by 4.8e-5. With the same object distance, Optiland matches. |

Off-axis chief rays agree once Optiland aims rays at the real stop. Some pupil-edge rays still differ by up to 0.025 mm (Cooke, 20°); the diagnosis reports them as unresolved instead of explaining them away. The OpticStudio values are independent measurements kept in [`tests/data`](tests/data); CI reruns the open-source engines against them on Linux and Windows.

## Install

Each engine runs in its own pinned Python 3.12 environment, because the engines pin different NumPy versions. Create the ones you need in the repository root:

```bash
git clone https://github.com/laweit-lxy/optics-agent-skills
cd optics-agent-skills
for skill in design-optical-systems cross-check-optical-designs analyze-optical-designs; do
  python3.12 -m venv .venv-$skill && .venv-$skill/bin/pip install -r skills/$skill/requirements.txt
done
```

On Windows use `.venv-<skill>\Scripts\pip.exe`. The cross-check environment needs Git, because RayOptics is installed from its pinned commit. The diagnosis and the MCP server find environments named `.venv-<skill>` in the repository root. For environments elsewhere, set `OPTICS_SKILLS_PYTHON_DESIGN`, `OPTICS_SKILLS_PYTHON_CROSSCHECK` and `OPTICS_SKILLS_PYTHON_ANALYZE` to their interpreters.

Claude Code:

```
/plugin marketplace add laweit-lxy/optics-agent-skills
/plugin install optics-agent-skills@optics-agent-skills
```

Codex: copy or link the folders under `skills/` into `~/.codex/skills/`. The diagnosis skill also needs the repository's `src/` folder next to `skills/`, so link the skill from a full clone.

## MCP server

The shared core in `src/optics_agent_skills` is standard library only. The same code serves the skills, a command line and an MCP server (stdio, `mcp` 2.3.0):

```bash
python3.12 -m venv .venv-mcp && .venv-mcp/bin/pip install -e ".[mcp]"
```

Install from a clone with `pip install -e`. The core runs the scripts under `skills/` and lists the samples in `tests/data`; a regular (non-editable) wheel does not contain them, so the server reports an error instead of running.

```json
{
  "mcpServers": {
    "optics-agent-skills": {
      "command": "/absolute/path/optics-agent-skills/.venv-mcp/bin/optics-agent-skills",
      "args": ["serve"],
      "env": { "OPTICS_SKILLS_OUTPUT_ROOT": "/absolute/path/for/reports" }
    }
  }
}
```

Tools: `list_samples`, `analyze_prescription`, `cross_check_prescription`, `diagnose_discrepancies`, `wave_optics_self_test`, `server_info`. They take absolute local paths, never modify the input, and write every report into a new directory under `OPTICS_SKILLS_OUTPUT_ROOT`.

## Try it

```bash
.venv-design-optical-systems/bin/python skills/design-optical-systems/scripts/optiland_regression.py \
  --input-zmx "$PWD/tests/data/cooke/cooke-6cd4da4.zmx" --output "$PWD/out/cooke-optiland.json"

.venv-cross-check-optical-designs/bin/python skills/cross-check-optical-designs/scripts/rayoptics_crosscheck.py \
  --input-zmx "$PWD/tests/data/cooke/cooke-6cd4da4.zmx" \
  --reference-json "$PWD/tests/data/cooke/cooke-native-reference.json" \
  --output "$PWD/out/cooke-crosscheck.json"

python3 skills/diagnose-optical-discrepancies/scripts/diagnose.py \
  --input-zmx "$PWD/tests/data/cooke/cooke-6cd4da4.zmx" \
  --reference-json "$PWD/tests/data/cooke/cooke-native-reference.json" \
  --output-dir "$PWD/out/cooke-diagnosis"
```

Paths must be absolute. Existing reports and non-empty output directories are never overwritten without `--force`. Source files are hashed before and after every run.

## Tests

Each test file runs in the environment of the skill it covers. The diagnosis tests need the Optiland and RayOptics environments; the core and MCP tests need neither.

```bash
.venv-design-optical-systems/bin/pip install pytest
.venv-design-optical-systems/bin/python -m pytest tests/test_design_optical_systems.py tests/test_diagnosis_core.py tests/test_diagnose_optical_discrepancies.py
.venv-cross-check-optical-designs/bin/python -m pytest tests/test_cross_check_optical_designs.py
.venv-analyze-optical-designs/bin/python -m pytest tests/test_analyze_optical_designs.py
.venv-mcp/bin/pip install -e ".[mcp,test]" && .venv-mcp/bin/python -m pytest tests/test_mcp_server.py
```

## Related

- [ai-zemax-optical-design](https://github.com/Jerry-del975/ai-zemax-optical-design): design loops in Ansys Zemax OpticStudio through ZOS-API. Its reports can serve as cross-check references.

See [ROADMAP.md](ROADMAP.md) for what comes next: radiometric calibration, a starting-point library, a requirements-to-lens design loop and a lens-design benchmark for agents.

## License

MIT. The engines keep their own licenses (Optiland MIT, RayOptics BSD-3-Clause, Chromatix MIT, Prysm MIT) and are installed as dependencies, not vendored.
