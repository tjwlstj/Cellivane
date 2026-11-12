# Source migration provenance

Prepared on 2026-11-12 for a new public Cellivane source baseline.

| Input | Selection | Reference |
|---|---|---|
| AIOS serving working snapshot | 473 source/docs/fixture files: native, hosted, P0/P1a and early Bridge/Seed | aios-kernel base 7d47524867e5f3d49521a0a5f7b1d0e65b5fe395 |
| Independent Seed current files | 117 files under components/seed, including MIT license and 8 public aggregates | local ref b89273b0e2cbb4ec7a61e1efb02f69beb1d529f1 |
| Ego direction | ego_core_design_ko.md, 2026-09-29 design | local uncommitted direction worktree |

References do not attest that all copied bytes were committed or remotely published. Per-file source bytes/SHA256 in source-snapshot.json identify the imported content. Original sources and an additional local recovery copy are preserved. Public documentation replaces entry-point descriptions; technical names and imported runtime bytes remain compatible.

## Scope and exclusions

No original Git history, raw execution/session bundles, private prompts/answers, credentials, model weights, engine/toolchain binaries or disk images are included. Historical runbooks remain; personal workstation paths and private session references are redacted where found. This is a bounded source-pattern review, not a guarantee about every possible secret.

The AIOS README declared MIT intent without a canonical LICENSE. The new root LICENSE formalizes that intent for this project's own code. Seed's MIT file remains unchanged. External resource rows keep code_import=false; upstream redistribution is not authorized by this migration.

## Evidence boundaries

- Native K1/K2 and limited ring3 evidence remain tied to their original execution.
- v0.10 TaskSmoke is a bounded actual-model flow, separate from P1a fixture HTTP.
- P1a's historical source33/hash verification and 1,122 tests do not validate a new operating image or actual Ollama-model compatibility.
- Seed's historical 815-test and fixed-host 900-second results are not this export's CI result.
- Optional CELLIVANE_RUNTIME_SELFTEST_EXE tests can skip without a compiled worker.
- Native/hosted/Seed suites execute separately. The root Cellivane workflow explicitly invokes Seed; nested workflows do not automatically run.

Fresh local results and any verified remote SHA belong in [PREPARATION_20261112.md](PREPARATION_20261112.md). Original failures remain historical facts.
