# ovh-dyndns

A small, portable Docker microservice that keeps an **OVH DNS `A` record** in sync
with your **current public IPv4 address** — a DynDNS client for the OVH API.

Un microservice Docker léger et portable qui maintient un **enregistrement `A`
OVH** en cohérence avec votre **adresse IPv4 publique** — un client DynDNS pour
l'API OVH.

## What it does / Ce qu'il fait

On each container start it:
1. resolves the current public IPv4 address,
2. reads the A record for the configured FQDN in the OVH zone,
3. updates the record **only if** it differs (otherwise does nothing).

À chaque démarrage du conteneur :
1. il résout l'adresse IPv4 publique actuelle,
2. il lit l'enregistrement A du FQDN configuré dans la zone OVH,
3. il met à jour l'enregistrement **uniquement si** il diffère (sinon rien).

## Quick start / Démarrage rapide

```bash
cp .env.example .env      # then fill in your OVH tokens and FQDN
docker compose up --build
```

## Documentation

| Language | Technical | Deployment & usage |
|---|---|---|
| 🇬🇧 English | [`docs/TECHNICAL.en.md`](./docs/TECHNICAL.en.md) | [`docs/DEPLOYMENT.en.md`](./docs/DEPLOYMENT.en.md) |
| 🇫🇷 Français | [`docs/TECHNICAL.fr.md`](./docs/TECHNICAL.fr.md) | [`docs/DEPLOYMENT.fr.md`](./docs/DEPLOYMENT.fr.md) |

## Configuration

All settings live in `.env` (see [`.env.example`](./.env.example)):
`OVH_ENDPOINT`, `OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`,
`OVH_CONSUMER_KEY`, `DNS_ZONE`, `RECORD_FQDN`, and a few optional tunables.

> OVH requires **three** API tokens (application key, application secret,
> consumer key), not a single key. See the deployment guide for how to generate
> them.

## License

MIT — see `LICENSE`.
