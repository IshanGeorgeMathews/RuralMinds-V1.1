# Setup prerequisites

## Can be handled locally

- Python 3.12 environment and locked API/worker dependencies.
- Node dependencies and SvelteKit checks.
- Repository layout, tests, linting, and CI scaffolding.
- Local SQLite development database once the migration layer is added.

## Requires the project owner

1. Provide an Ubuntu 24.04/KITE GNU-Linux VM or target machine for systemd, Caddy, `.deb`, firewall, mDNS, and rollback testing.
2. Decide which Gemma 4 quantisation/model files may be downloaded and redistributed; place approved files under `models/` and include their licence/NOTICE files.
3. Provide real, lawfully obtained Malayalam/English documents and Manglish evaluation examples. Do not put copyrighted textbooks in this repository.
4. Provide the intended reference hardware so the M4 performance gate can be measured.
5. Supply external-service credentials only when the portal/deployment phase begins: GitHub Actions, domain/DNS, VPS, Cloudflare/R2, Turnstile, and email.
6. Obtain legal review and any SCERT/KITE/NCERT permissions before real school deployment.

The Windows development machine has Tesseract 5.5.3 with `eng`, `mal`, and `osd` installed. Ollama 0.40.2 is installed with `gemma4:e2b` available, and its bundled `llama-server.exe` is available for local development. Caddy is not installed locally; it is a Linux deployment prerequisite.

The API environment now includes `pypdfium2` and `sqlite-vec`. `RURALMINDS_LLM_BACKEND=ollama` is the current development default; the production configuration can switch to a directly managed `llama-server` later.
