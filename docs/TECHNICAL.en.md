# Technical Documentation — OVH Dynamic DNS updater

> 🇫🇷 French version: [`TECHNICAL.fr.md`](./TECHNICAL.fr.md)

## 1. Purpose

This microservice keeps a single **A record** in an OVH DNS zone in sync with the
**public IPv4 address** of the host (or the network) it runs on. It is the
equivalent of a "DynDNS" client, dedicated to the OVH API.

It is designed to run inside Docker, to be fully configured through a `.env`
file, and to perform its check **each time the container is started**.

## 2. High-level behaviour

On every run the service executes one reconciliation cycle:

1. **Resolve the public IPv4 address** by querying one or more external
   "what is my IP" HTTP services (with automatic fallback).
2. **Read the current A record** stored in the OVH zone for the configured FQDN.
3. **Compare** the public IP with the record's target:
   - **Match** → nothing is done. The record is already correct.
   - **Mismatch** → the OVH API updates the record, then refreshes the zone.
4. If **no A record exists** for the FQDN and `CREATE_IF_MISSING=true`, the record
   is created automatically on the first run.

```
┌────────────┐    ┌─────────────────┐    ┌──────────────────────────┐
│ Public IP  │    │ OVH A record    │    │ Action                   │
│ lookup     │───▶│ (current value) │───▶│ equal   → no change      │
│ (ipify...) │    │ via OVH API     │    │ differ  → PUT + refresh  │
└────────────┘    └─────────────────┘    │ missing → POST + refresh │
                                         └──────────────────────────┘
```

## 3. Repository layout

```
ovh-dyndns/
├── app/
│   └── update_dns.py       # Application logic (comments in English)
├── docs/
│   ├── TECHNICAL.en.md      # This file
│   ├── TECHNICAL.fr.md
│   ├── DEPLOYMENT.en.md
│   └── DEPLOYMENT.fr.md
├── Dockerfile               # Slim Python 3.12 image, runs as non-root
├── docker-compose.yml       # Service definition, reads .env
├── requirements.txt         # Python dependency: ovh
├── .env.example             # Configuration template
├── .dockerignore
└── .gitignore               # Excludes the real .env from Git
```

## 4. Configuration reference

All configuration is passed as environment variables (via the `.env` file).

| Variable | Required | Default | Description |
|---|---|---|---|
| `OVH_ENDPOINT` | no | `ovh-eu` | OVH API region (`ovh-eu`, `ovh-ca`, `ovh-us`, …). |
| `OVH_APPLICATION_KEY` | **yes** | — | OVH application key. |
| `OVH_APPLICATION_SECRET` | **yes** | — | OVH application secret. |
| `OVH_CONSUMER_KEY` | **yes** | — | OVH consumer key. |
| `DNS_ZONE` | **yes** | — | The OVH-managed zone, e.g. `mondomaine.fr`. |
| `RECORD_FQDN` | **yes** | — | Host to check/update, e.g. `ext.mondomaine.fr`. Must belong to `DNS_ZONE`. |
| `RECORD_TTL` | no | `60` | TTL used only when the record is first created. |
| `CREATE_IF_MISSING` | no | `true` | Create the A record if it does not exist yet. |
| `IP_LOOKUP_URLS` | no | ipify / icanhazip / ifconfig.me | Comma-separated list of plain-text IPv4 endpoints. |
| `RUN_INTERVAL` | no | `0` | `0` = one-shot (run once, then exit). `>0` = loop every N seconds. |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

### 4.1 FQDN vs. sub-domain

OVH manipulates records by **zone** + **sub-domain**. The service derives the
sub-domain from `RECORD_FQDN` and `DNS_ZONE`:

| `RECORD_FQDN` | `DNS_ZONE` | Derived sub-domain |
|---|---|---|
| `ext.mondomaine.fr` | `mondomaine.fr` | `ext` |
| `a.b.mondomaine.fr` | `mondomaine.fr` | `a.b` |
| `mondomaine.fr` | `mondomaine.fr` | `` (zone apex) |

If `RECORD_FQDN` does not end with `DNS_ZONE`, the service exits with an error.

## 5. OVH API usage

The service relies on the official [`ovh`](https://github.com/ovh/python-ovh)
Python library, which handles request signing (`X-Ovh-Signature`) transparently.

| Step | Method | Endpoint |
|---|---|---|
| List matching A records | `GET` | `/domain/zone/{zone}/record?fieldType=A&subDomain={sub}` |
| Read a record's target | `GET` | `/domain/zone/{zone}/record/{id}` |
| Update a record | `PUT` | `/domain/zone/{zone}/record/{id}` (body: `target`) |
| Create a record | `POST` | `/domain/zone/{zone}/record` |
| Apply changes | `POST` | `/domain/zone/{zone}/refresh` |

> **Note on the "refresh" call.** OVH stages record changes and only publishes
> them to the live zone after a `refresh`. The service always calls `refresh`
> after a create or update.

### 5.1 Required API rights

When generating the token, grant the following rights on your zone:

```
GET    /domain/zone/mondomaine.fr/*
PUT    /domain/zone/mondomaine.fr/*
POST   /domain/zone/mondomaine.fr/*
```

## 6. Execution model

- **One-shot (default, `RUN_INTERVAL=0`).** The container runs `reconcile()` once
  and exits with a status code. This matches the requirement "check on every
  container start". Re-running is done by starting the container again (manually,
  from a host cron job, or a systemd timer).
- **Loop (`RUN_INTERVAL>0`).** The container stays alive and re-checks every
  `RUN_INTERVAL` seconds. Transient errors are logged and do not stop the loop.

### 6.1 Exit codes (one-shot mode)

| Code | Meaning |
|---|---|
| `0` | Success: no change needed, or record updated/created. |
| `1` | Record missing and `CREATE_IF_MISSING=false`. |
| `2` | Configuration error (missing variable, FQDN outside the zone). |
| other | Unhandled runtime error (e.g. IP lookup failed, API error). |

## 7. Security considerations

- The image runs as a **non-root** user (`appuser`, uid 10001).
- Secrets live only in `.env`, which is **git-ignored** and **docker-ignored**.
- The OVH token should be scoped to a **single zone**, not the whole account.
- No inbound port is opened; the container only makes outbound HTTPS calls.

## 8. Dependencies

- **Runtime:** Docker Engine + Docker Compose plugin.
- **Python:** 3.12 (provided by the base image).
- **Library:** `ovh` (pinned in `requirements.txt`).
- **Standard library only** for IP lookup, comparison, and logging.
