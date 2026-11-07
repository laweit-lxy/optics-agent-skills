# optics-agent-skills

[![regression](https://github.com/laweit-lxy/optics-agent-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/laweit-lxy/optics-agent-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Agent skills for optical design that you can check. An AI coding agent (Claude Code, Codex, or anything that reads `SKILL.md`) gets pinned, open-source optics engines, strict read-only handling of your lens files, and a second engine that independently re-derives the numbers before anyone trusts them.

| Skill | Engine | What it does |
| --- | --- | --- |
| [`design-optical-systems`](skills/design-optical-systems/SKILL.md) | [Optiland](https://github.com/optiland/optiland) 0.6.3 | Analyzes a sequential `.zmx` prescription: EFL, F-number, spot, OPD, FFT PSF/MTF, radius sensitivity. Qualifies itself against fixed Cooke, Double-Gauss and Hubble references on every run. |
| [`cross-check-optical-designs`](skills/cross-check-optical-designs/SKILL.md) | [RayOptics](https://github.com/mjhoptics/ray-optics) @ `e25bc57` | Independently loads the same `.zmx`, audits surfaces, stop, fields and glass-catalog resolution, and compares EFL, paraxial and real working F-number against an Optiland or OpticStudio report. Returns `PASS`, `MISMATCH` or `FAIL`. |

## Why cross-check

Every lens-design program imports a `.zmx` file a little differently: glass catalogs, aperture definitions and F-number conventions all vary. A single engine reporting a number is not evidence. Here, three engines meet on the same prescriptions, and the one disagreement stays visible instead of being tuned away:

| Sample | OpticStudio 22.2.2 EFL (mm) | RayOptics EFL (mm) | Optiland EFL (mm) |
| --- | --- | --- | --- |
| Cooke triplet | 50.000394 | 50.000394 | 49.999783 (−1.2e-5, known, glass data suspected) |
| Double-Gauss | 100.003748 | 100.003748 | 100.003748 |
| Hubble | 57600.081 | 57600.081 | 57600.081 |

The OpticStudio values are independent measurements kept in [`tests/data`](tests/data); CI reruns the open-source engines against them on Linux and Windows.

## Install

Each skill runs in its own pinned Python 3.12 environment from its `requirements.txt`:

```bash
git clone https://github.com/laweit-lxy/optics-agent-skills
cd optics-agent-skills
python3.12 -m venv .venv-design && .venv-design/bin/pip install -r skills/design-optical-systems/requirements.txt
python3.12 -m venv .venv-crosscheck && .venv-crosscheck/bin/pip install -r skills/cross-check-optical-designs/requirements.txt
```

On Windows use `.venv-design\Scripts\pip.exe`. The cross-check environment needs Git, because RayOptics is installed from its pinned commit.

Claude Code:

```
/plugin marketplace add laweit-lxy/optics-agent-skills
/plugin install optics-agent-skills@optics-agent-skills
```

Codex: copy or link `skills/design-optical-systems` and `skills/cross-check-optical-designs` into `~/.codex/skills/`.

Tell the agent where the environments are, for example "the Optiland environment is `/path/.venv-design`".

## Try it

```bash
.venv-design/bin/python skills/design-optical-systems/scripts/optiland_regression.py \
  --input-zmx "$PWD/tests/data/cooke/cooke-6cd4da4.zmx" --output "$PWD/out/cooke-optiland.json"

.venv-crosscheck/bin/python skills/cross-check-optical-designs/scripts/rayoptics_crosscheck.py \
  --input-zmx "$PWD/tests/data/cooke/cooke-6cd4da4.zmx" \
  --reference-json "$PWD/tests/data/cooke/cooke-native-reference.json" \
  --output "$PWD/out/cooke-crosscheck.json"
```

Paths must be absolute, the output directory must exist, and existing reports are never overwritten without `--force`. Source files are hashed before and after every run.

## Tests

```bash
.venv-design/bin/pip install pytest && .venv-design/bin/python -m pytest tests/test_design_optical_systems.py
.venv-crosscheck/bin/pip install pytest && .venv-crosscheck/bin/python -m pytest tests/test_cross_check_optical_designs.py
```

## Related

- [ai-zemax-optical-design](https://github.com/Jerry-del975/ai-zemax-optical-design): design loops in Ansys Zemax OpticStudio through ZOS-API. Its reports can serve as cross-check references.

See [ROADMAP.md](ROADMAP.md) for what comes next: wave optics, discrepancy diagnosis, an MCP server, a requirements-to-lens design loop and a lens-design benchmark for agents.

## License

MIT. The engines keep their own licenses (Optiland MIT, RayOptics BSD-3-Clause) and are installed as dependencies, not vendored.
