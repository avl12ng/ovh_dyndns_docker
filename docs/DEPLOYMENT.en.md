# Deployment & Usage Guide — OVH Dynamic DNS updater

> 🇫🇷 French version: [`DEPLOYMENT.fr.md`](./DEPLOYMENT.fr.md)

## 1. Prerequisites

- A host with **Docker Engine** and the **Docker Compose** plugin installed.
- An **OVH account** managing the DNS zone you want to update.
- The **DNS zone** already created at OVH (e.g. `mondomaine.fr`).

Check your tooling:

```bash
docker --version
docker compose version
```

## 2. Generate your OVH API credentials

OVH does not use a single "API key" — it uses **three** tokens.

1. Open the token creation page:
   **https://www.ovh.com/auth/api/createToken**
2. Log in with your OVH account.
3. Fill in the form:
   - **Application name / description:** e.g. `ovh-dyndns`.
   - **Validity:** `Unlimited` (or a duration that suits your policy).
   - **Rights:** add the following three lines (replace `mondomaine.fr` with your
     own zone):

     | Method | Path |
     |---|---|
     | `GET`  | `/domain/zone/mondomaine.fr/*` |
     | `PUT`  | `/domain/zone/mondomaine.fr/*` |
     | `POST` | `/domain/zone/mondomaine.fr/*` |
4. Click **Create keys**. OVH shows three values **once**:
   - **Application Key**
   - **Application Secret**
   - **Consumer Key**

   Copy them immediately.

## 3. Get the project

```bash
git clone https://github.com/avl12ng/ovh-dyndns.git
cd ovh-dyndns
```

## 4. Configure the service

Copy the template and edit it:

```bash
cp .env.example .env
vim .env       # or your editor of choice
```

Minimum values to set:

```dotenv
OVH_ENDPOINT=ovh-eu
OVH_APPLICATION_KEY=xxxxxxxxxxxxxxxx
OVH_APPLICATION_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OVH_CONSUMER_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DNS_ZONE=mondomaine.fr
RECORD_FQDN=ext.mondomaine.fr
```

> ⚠️ `RECORD_FQDN` must belong to `DNS_ZONE`. For the domain root itself, set
> `RECORD_FQDN=mondomaine.fr`.

The `.env` file is listed in `.gitignore`, so it will **not** be pushed to GitHub.

## 5. First run (one-shot mode)

Build the image and run the check once:

```bash
docker compose up --build
```

Expected output when the record is already correct:

```
[INFO] Current public IPv4 address: 203.0.113.42
[INFO] DNS A record for ext.mondomaine.fr currently points to: 203.0.113.42
[INFO] No change required: DNS already matches the public IP.
```

Expected output when the IP changed:

```
[INFO] Current public IPv4 address: 203.0.113.42
[INFO] DNS A record for ext.mondomaine.fr currently points to: 198.51.100.7
[INFO] IP mismatch detected: 198.51.100.7 -> 203.0.113.42. Updating OVH record...
[INFO] A record updated to 203.0.113.42 and zone refreshed.
```

The container exits after the check. This is normal in one-shot mode.

To run without attaching to the logs:

```bash
docker compose up --build -d
docker compose logs ovh-dyndns      # inspect the result
```

## 6. Re-running automatically

Because a public IP can change at any time, you will usually want the check to
run regularly. Two options:

### Option A — Loop inside the container

Set an interval in `.env` (e.g. every 5 minutes):

```dotenv
RUN_INTERVAL=300
```

Then start it once and let it keep running:

```bash
docker compose up --build -d
```

Also switch `docker-compose.yml` to `restart: unless-stopped` so the loop
survives reboots:

```yaml
    restart: unless-stopped
```

### Option B — One-shot triggered by the host scheduler

Keep the default one-shot mode (`RUN_INTERVAL=0`) and let the host run it on a
schedule.

**cron** (every 5 minutes):

```cron
*/5 * * * * cd /path/to/ovh-dyndns && /usr/bin/docker compose up -d >> /var/log/ovh-dyndns.log 2>&1
```

**systemd timer** (alternative to cron):

`/etc/systemd/system/ovh-dyndns.service`
```ini
[Unit]
Description=OVH DynDNS update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/ovh-dyndns
ExecStart=/usr/bin/docker compose up
```

`/etc/systemd/system/ovh-dyndns.timer`
```ini
[Unit]
Description=Run OVH DynDNS update every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ovh-dyndns.timer
```

## 7. Updating the service

```bash
git pull
docker compose up --build -d
```

## 8. Uninstalling

```bash
docker compose down
docker image rm ovh-dyndns   # image name may vary
```

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Missing required environment variable` | A mandatory value is empty in `.env`. | Fill in the missing key. |
| `RECORD_FQDN ... does not belong to DNS_ZONE` | FQDN/zone mismatch. | Ensure the FQDN ends with the zone. |
| `Could not resolve public IPv4 address` | No outbound internet / all lookup URLs blocked. | Check connectivity or set `IP_LOOKUP_URLS`. |
| HTTP 403 from OVH | Token lacks rights or wrong endpoint. | Re-generate the token with GET/PUT/POST on the zone; verify `OVH_ENDPOINT`. |
| Record updated but not visible | Waiting on propagation/TTL. | The zone is refreshed automatically; allow the TTL to expire. |
| Container keeps restarting | Loop mode + `restart` policy with a failing config. | Fix `.env`, then `docker compose up`. |

To increase verbosity, set `LOG_LEVEL=DEBUG` in `.env`.

