# Guide de déploiement et d'utilisation — Mise à jour DNS dynamique OVH

> 🇬🇧 English version : [`DEPLOYMENT.en.md`](./DEPLOYMENT.en.md)

## 1. Prérequis

- Un hôte disposant de **Docker Engine** et du plugin **Docker Compose**.
- Un **compte OVH** gérant la zone DNS à mettre à jour.
- La **zone DNS** déjà créée chez OVH (ex. `mondomaine.fr`).

Vérifiez votre outillage :

```bash
docker --version
docker compose version
```

## 2. Générer vos identifiants API OVH

OVH n'utilise pas une simple « clé API » : il faut **trois** tokens.

1. Ouvrez la page de création de token :
   **https://www.ovh.com/auth/api/createToken**
2. Connectez-vous avec votre compte OVH.
3. Renseignez le formulaire :
   - **Nom / description de l'application :** ex. `ovh-dyndns`.
   - **Validité :** `Illimitée` (ou une durée conforme à votre politique).
   - **Droits :** ajoutez les trois lignes suivantes (remplacez `mondomaine.fr`
     par votre zone) :

     | Méthode | Chemin |
     |---|---|
     | `GET`  | `/domain/zone/mondomaine.fr/*` |
     | `PUT`  | `/domain/zone/mondomaine.fr/*` |
     | `POST` | `/domain/zone/mondomaine.fr/*` |
4. Cliquez sur **Créer les clés**. OVH affiche trois valeurs **une seule fois** :
   - **Application Key** (clé d'application)
   - **Application Secret** (secret d'application)
   - **Consumer Key** (clé consommateur)

   Copiez-les immédiatement.

## 3. Récupérer le projet

```bash
git clone https://github.com/avl12ng/ovh_dyndns_docker.git
cd ovh_dyndns_docker
```

## 4. Configurer le service

Copiez le modèle et éditez-le :

```bash
cp .env.example .env
vim .env       # ou l'éditeur de votre choix
```

Valeurs minimales à renseigner :

```dotenv
OVH_ENDPOINT=ovh-eu
OVH_APPLICATION_KEY=xxxxxxxxxxxxxxxx
OVH_APPLICATION_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OVH_CONSUMER_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DNS_ZONE=mondomaine.fr
RECORD_FQDN=ext.mondomaine.fr
```

> ⚠️ `RECORD_FQDN` doit appartenir à `DNS_ZONE`. Pour la racine du domaine,
> mettez `RECORD_FQDN=mondomaine.fr`.

Le fichier `.env` figure dans `.gitignore` : il **ne sera pas** poussé sur GitHub.

## 5. Premier lancement (mode passage unique)

Construisez l'image et lancez la vérification une fois :

```bash
docker compose up --build
```

Sortie attendue quand l'enregistrement est déjà correct :

```
[INFO] Current public IPv4 address: 203.0.113.42
[INFO] DNS A record for ext.mondomaine.fr currently points to: 203.0.113.42
[INFO] No change required: DNS already matches the public IP.
```

Sortie attendue quand l'IP a changé :

```
[INFO] Current public IPv4 address: 203.0.113.42
[INFO] DNS A record for ext.mondomaine.fr currently points to: 198.51.100.7
[INFO] IP mismatch detected: 198.51.100.7 -> 203.0.113.42. Updating OVH record...
[INFO] A record updated to 203.0.113.42 and zone refreshed.
```

Le conteneur se termine après la vérification. C'est normal en mode passage
unique.

Pour lancer sans rester attaché aux logs :

```bash
docker compose up --build -d
docker compose logs ovh-dyndns      # consulter le résultat
```

## 6. Ré-exécution automatique

Une IP publique peut changer à tout moment : vous voudrez généralement lancer la
vérification régulièrement. Deux options.

### Option A — Boucle dans le conteneur

Définissez un intervalle dans `.env` (ex. toutes les 5 minutes) :

```dotenv
RUN_INTERVAL=300
```

Puis démarrez-le une fois et laissez-le tourner :

```bash
docker compose up --build -d
```

Passez aussi `docker-compose.yml` en `restart: unless-stopped` pour que la boucle
survive aux redémarrages :

```yaml
    restart: unless-stopped
```

### Option B — Passage unique déclenché par l'ordonnanceur de l'hôte

Conservez le mode passage unique par défaut (`RUN_INTERVAL=0`) et laissez l'hôte
le lancer selon une planification.

**cron** (toutes les 5 minutes) :

```cron
*/5 * * * * cd /chemin/vers/ovh-dyndns && /usr/bin/docker compose up -d >> /var/log/ovh-dyndns.log 2>&1
```

**timer systemd** (alternative à cron) :

`/etc/systemd/system/ovh-dyndns.service`
```ini
[Unit]
Description=Mise a jour OVH DynDNS
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/chemin/vers/ovh-dyndns
ExecStart=/usr/bin/docker compose up
```

`/etc/systemd/system/ovh-dyndns.timer`
```ini
[Unit]
Description=Lance la mise a jour OVH DynDNS toutes les 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

Activez-le :

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ovh-dyndns.timer
```

## 7. Mettre à jour le service

```bash
git pull
docker compose up --build -d
```

## 8. Désinstaller

```bash
docker compose down
docker image rm ovh-dyndns-ovh-dyndns   # le nom de l'image peut varier
```

## 9. Dépannage

| Symptôme | Cause probable | Correction |
|---|---|---|
| `Missing required environment variable` | Une valeur obligatoire est vide dans `.env`. | Renseignez la clé manquante. |
| `RECORD_FQDN ... does not belong to DNS_ZONE` | FQDN/zone incohérents. | Vérifiez que le FQDN se termine par la zone. |
| `Could not resolve public IPv4 address` | Pas d'accès Internet sortant / URLs bloquées. | Vérifiez la connectivité ou définissez `IP_LOOKUP_URLS`. |
| HTTP 403 renvoyé par OVH | Token sans droits ou mauvais endpoint. | Régénérez le token avec GET/PUT/POST sur la zone ; vérifiez `OVH_ENDPOINT`. |
| Enregistrement mis à jour mais non visible | Propagation/TTL en cours. | La zone est rafraîchie automatiquement ; attendez l'expiration du TTL. |
| Le conteneur redémarre en boucle | Mode boucle + politique `restart` avec une config invalide. | Corrigez `.env`, puis `docker compose up`. |

Pour augmenter la verbosité, définissez `LOG_LEVEL=DEBUG` dans `.env`.
/ovh-dyndns.git
cd ovh-dyndns
```

## 4. Configurer le service

Copiez le modèle et éditez-le :

```bash
cp .env.example .env
vim .env       # ou l'éditeur de votre choix
```

Valeurs minimales à renseigner :

```dotenv
OVH_ENDPOINT=ovh-eu
OVH_APPLICATION_KEY=xxxxxxxxxxxxxxxx
OVH_APPLICATION_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OVH_CONSUMER_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DNS_ZONE=mondomaine.fr
RECORD_FQDN=ext.mondomaine.fr
```

> ⚠️ `RECORD_FQDN` doit appartenir à `DNS_ZONE`. Pour la racine du domaine,
> mettez `RECORD_FQDN=mondomaine.fr`.

Le fichier `.env` figure dans `.gitignore` : il **ne sera pas** poussé sur GitHub.

## 5. Premier lancement (mode passage unique)

Construisez l'image et lancez la vérification une fois :

```bash
docker compose up --build
```

Sortie attendue quand l'enregistrement est déjà correct :

```
[INFO] Current public IPv4 address: 203.0.113.42
[INFO] DNS A record for ext.mondomaine.fr currently points to: 203.0.113.42
[INFO] No change required: DNS already matches the public IP.
```

Sortie attendue quand l'IP a changé :

```
[INFO] Current public IPv4 address: 203.0.113.42
[INFO] DNS A record for ext.mondomaine.fr currently points to: 198.51.100.7
[INFO] IP mismatch detected: 198.51.100.7 -> 203.0.113.42. Updating OVH record...
[INFO] A record updated to 203.0.113.42 and zone refreshed.
```

Le conteneur se termine après la vérification. C'est normal en mode passage
unique.

Pour lancer sans rester attaché aux logs :

```bash
docker compose up --build -d
docker compose logs ovh-dyndns      # consulter le résultat
```

## 6. Ré-exécution automatique

Une IP publique peut changer à tout moment : vous voudrez généralement lancer la
vérification régulièrement. Deux options.

### Option A — Boucle dans le conteneur

Définissez un intervalle dans `.env` (ex. toutes les 5 minutes) :

```dotenv
RUN_INTERVAL=300
```

Puis démarrez-le une fois et laissez-le tourner :

```bash
docker compose up --build -d
```

Passez aussi `docker-compose.yml` en `restart: unless-stopped` pour que la boucle
survive aux redémarrages :

```yaml
    restart: unless-stopped
```

### Option B — Passage unique déclenché par l'ordonnanceur de l'hôte

Conservez le mode passage unique par défaut (`RUN_INTERVAL=0`) et laissez l'hôte
le lancer selon une planification.

**cron** (toutes les 5 minutes) :

```cron
*/5 * * * * cd /chemin/vers/ovh-dyndns && /usr/bin/docker compose up -d >> /var/log/ovh-dyndns.log 2>&1
```

**timer systemd** (alternative à cron) :

`/etc/systemd/system/ovh-dyndns.service`
```ini
[Unit]
Description=Mise a jour OVH DynDNS
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/chemin/vers/ovh-dyndns
ExecStart=/usr/bin/docker compose up
```

`/etc/systemd/system/ovh-dyndns.timer`
```ini
[Unit]
Description=Lance la mise a jour OVH DynDNS toutes les 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

Activez-le :

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ovh-dyndns.timer
```

## 7. Mettre à jour le service

```bash
git pull
docker compose up --build -d
```

## 8. Désinstaller

```bash
docker compose down
docker image rm ovh-dyndns   # le nom de l'image peut varier
```

## 9. Dépannage

| Symptôme | Cause probable | Correction |
|---|---|---|
| `Missing required environment variable` | Une valeur obligatoire est vide dans `.env`. | Renseignez la clé manquante. |
| `RECORD_FQDN ... does not belong to DNS_ZONE` | FQDN/zone incohérents. | Vérifiez que le FQDN se termine par la zone. |
| `Could not resolve public IPv4 address` | Pas d'accès Internet sortant / URLs bloquées. | Vérifiez la connectivité ou définissez `IP_LOOKUP_URLS`. |
| HTTP 403 renvoyé par OVH | Token sans droits ou mauvais endpoint. | Régénérez le token avec GET/PUT/POST sur la zone ; vérifiez `OVH_ENDPOINT`. |
| Enregistrement mis à jour mais non visible | Propagation/TTL en cours. | La zone est rafraîchie automatiquement ; attendez l'expiration du TTL. |
| Le conteneur redémarre en boucle | Mode boucle + politique `restart` avec une config invalide. | Corrigez `.env`, puis `docker compose up`. |

Pour augmenter la verbosité, définissez `LOG_LEVEL=DEBUG` dans `.env`.
