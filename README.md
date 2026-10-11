# RuralMinds

Offline-first Malayalam/Manglish learning server for rural schools.

The implementation blueprint is in [`implementation/plan.md`](implementation/plan.md). The repository is being built as a monorepo with a FastAPI API/worker, SvelteKit PWA, evaluation harness, and Linux packaging.

The initial foundation is in place. Model weights, school content, cloud credentials, and Linux appliance validation are intentionally not bundled. See [`docs/setup-prerequisites.md`](docs/setup-prerequisites.md).

## Local checks

```powershell
uv sync --directory apps/api
uv run --directory apps/api pytest
npm --prefix frontend run check
npm --prefix frontend run build
```

