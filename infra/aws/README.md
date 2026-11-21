# AWS deployment (Lightsail)

The whole stack — Postgres, FastAPI, nginx-served SPA, backup agent and Caddy —
runs on one Lightsail instance. This is the cheapest shape that still behaves
like production: one static IP, one TLS origin, one box to reason about.

```
                 Route 53  nirvaah.deployone.cloud
                              │
                    Lightsail static IP (52.66.75.183)
                              │
                    ┌─────────▼──────────┐
                    │  Caddy  :80/:443   │  Let's Encrypt, HTTP→HTTPS
                    └─────────┬──────────┘
                              │ app network
                    ┌─────────▼──────────┐
                    │ frontend nginx:8080│  SPA + /api proxy
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐      ┌──────────────┐
                    │ backend uvicorn    │─────▶│ Postgres 16  │
                    └────────────────────┘      └──────┬───────┘
                                                       │ data network
                                                ┌──────▼───────┐
                                                │ backup agent │──▶ S3
                                                └──────────────┘
```

Only 80/443 are public. SSH is limited to the CIDR in `ssh_cidr`. The database
has no published port, and the backend is bound to loopback.

## Cost

| Line item | USD / month | ≈ INR / month |
|---|---|---|
| Lightsail `micro_3_1` (1 GB RAM, 2 vCPU, 40 GB SSD, 1 TB transfer) | 7.00 | ₹655 |
| S3 backups (a few MB, 14-day + monthly retention) | ~0.10 | ₹10 |
| Route 53 hosted zone (already exists, shared) | 0.50 | ₹47 |
| Let's Encrypt certificate | 0 | ₹0 |
| **Total** | **~7.60** | **~₹710** |

At ₹93.5/USD. Data transfer beyond the included 1 TB is $0.09/GB. The
DeepSeek assistant usage is billed separately by the API provider.

Cheaper is possible but not advisable: `nano_3_1` ($5) has 512 MB RAM and the
stack's declared limits already total ~1.4 GB; the IPv6-only plans cannot serve
a PWA to IPv4-only phones and break ACME HTTP-01. Going up to `small_3_1`
($12, 2 GB) removes the swap dependency.

## First apply

```bash
cd infra/aws
terraform init
terraform apply            # ~2 min, then user data installs Docker
```

Set `ssh_cidr` to your own address first (`ssh_cidr = "1.2.3.4/32"`), and
`hostname` if this is not `nirvaah.deployone.cloud`.

Then deploy the images:

```powershell
# Windows
./deploy/deploy.ps1

# any shell with terraform + ssh
pwsh ./deploy/deploy.ps1
```

`deploy.ps1` reads `infra/aws` outputs, writes the instance key to
`~/.ssh/nirvaah-app.pem` once, builds `/opt/nirvaah/.env` from the local `.env`,
uploads the compose files, pulls the public images and waits for
`https://<hostname>/api/health`.

## Day-2 operations

```bash
ssh -i ~/.ssh/nirvaah-app.pem ubuntu@<static-ip>
cd /opt/nirvaah

docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart backend
```

Release a new frontend:

```bash
./release.sh 1.1.3                 # build + push all images
./deploy/deploy.ps1                # or -FrontendTag 1.1.3 for UI-only
```

Backups: the agent dumps every 4 h, verifies a restore, and ships to
`nirvaah-backups-<account-id>` (see `infra/terraform`). Check it directly:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backup --once
```

### Things to know

- **No Ollama on this box.** 1 GB of RAM cannot hold `qwen2.5:3b`; the
  assistant uses the DeepSeek-compatible fallback configured in `.env`
  (`FALLBACK_API_KEY`). Local-only inference would need a GPU instance at
  ~$200+/month.
- **Swap is load-bearing.** 2 GB swap is created by user data. Without it a
  cold start under a burst can OOM-kill the API.
- **The instance is replaceable; the data is not.** Postgres lives in a Docker
  volume on the instance disk. `terraform apply -replace` destroys that disk —
  take a backup first (`backup --once`, confirm the S3 object) or move the
  database to RDS before treating the box as cattle.
- **Terraform generates the SSH key** and keeps it in state. State is
  git-ignored; if you rotate operators, replace the key pair.
- `docker compose` requires the `!override` tag (Compose ≥ 2.24). The image on
  the host satisfies this.
