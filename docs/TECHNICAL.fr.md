# Documentation technique — Mise à jour DNS dynamique OVH

> 🇬🇧 English version : [`TECHNICAL.en.md`](./TECHNICAL.en.md)

## 1. Objectif

Ce microservice maintient un unique **enregistrement A** d'une zone DNS OVH en
cohérence avec l'**adresse IPv4 publique** de l'hôte (ou du réseau) sur lequel il
s'exécute. C'est l'équivalent d'un client « DynDNS » dédié à l'API OVH.

Il est conçu pour tourner dans Docker, être entièrement configuré via un fichier
`.env`, et effectuer sa vérification **à chaque démarrage du conteneur**.

## 2. Comportement général

À chaque exécution, le service réalise un cycle de réconciliation :

1. **Résolution de l'adresse IPv4 publique** en interrogeant un ou plusieurs
   services HTTP externes de type « quelle est mon IP » (bascule automatique).
2. **Lecture de l'enregistrement A** actuellement présent dans la zone OVH pour
   le FQDN configuré.
3. **Comparaison** de l'IP publique avec la cible de l'enregistrement :
   - **Identique** → aucune action. L'enregistrement est déjà correct.
   - **Différente** → l'API OVH met à jour l'enregistrement, puis rafraîchit la zone.
4. Si **aucun enregistrement A n'existe** pour le FQDN et que
   `CREATE_IF_MISSING=true`, l'enregistrement est créé automatiquement au premier
   passage.

```
┌────────────┐    ┌─────────────────┐    ┌──────────────────────────┐
│ IP publique│    │ Enreg. A OVH    │    │ Action                   │
│ (ipify...) │───▶│ (valeur         │───▶│ égales   → aucun chgmt   │
│            │    │  actuelle)      │    │ diffèrent→ PUT + refresh │
└────────────┘    └─────────────────┘    │ absent   → POST + refresh│
                                         └──────────────────────────┘
```

## 3. Arborescence du dépôt

```
ovh-dyndns/
├── app/
│   └── update_dns.py       # Logique applicative (commentaires en anglais)
├── docs/
│   ├── TECHNICAL.en.md
│   ├── TECHNICAL.fr.md      # Ce fichier
│   ├── DEPLOYMENT.en.md
│   └── DEPLOYMENT.fr.md
├── Dockerfile               # Image Python 3.12 slim, exécution non-root
├── docker-compose.yml       # Définition du service, lit le .env
├── requirements.txt         # Dépendance Python : ovh
├── .env.example             # Modèle de configuration
├── .dockerignore
└── .gitignore               # Exclut le vrai .env de Git
```

## 4. Référence de configuration

Toute la configuration est passée en variables d'environnement (via le `.env`).

| Variable | Requise | Défaut | Description |
|---|---|---|---|
| `OVH_ENDPOINT` | non | `ovh-eu` | Région de l'API OVH (`ovh-eu`, `ovh-ca`, `ovh-us`, …). |
| `OVH_APPLICATION_KEY` | **oui** | — | Clé d'application OVH. |
| `OVH_APPLICATION_SECRET` | **oui** | — | Secret d'application OVH. |
| `OVH_CONSUMER_KEY` | **oui** | — | Clé consommateur OVH. |
| `DNS_ZONE` | **oui** | — | Zone gérée par OVH, ex. `mondomaine.fr`. |
| `RECORD_FQDN` | **oui** | — | Hôte à vérifier/modifier, ex. `ext.mondomaine.fr`. Doit appartenir à `DNS_ZONE`. |
| `RECORD_TTL` | non | `60` | TTL utilisé uniquement à la création de l'enregistrement. |
| `CREATE_IF_MISSING` | non | `true` | Crée l'enregistrement A s'il n'existe pas encore. |
| `IP_LOOKUP_URLS` | non | ipify / icanhazip / ifconfig.me | Liste (séparée par des virgules) de points renvoyant l'IPv4 en texte brut. |
| `RUN_INTERVAL` | non | `0` | `0` = passage unique (exécute une fois, puis quitte). `>0` = boucle toutes les N secondes. |
| `LOG_LEVEL` | non | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

### 4.1 FQDN et sous-domaine

OVH manipule les enregistrements par **zone** + **sous-domaine**. Le service
déduit le sous-domaine à partir de `RECORD_FQDN` et `DNS_ZONE` :

| `RECORD_FQDN` | `DNS_ZONE` | Sous-domaine déduit |
|---|---|---|
| `ext.mondomaine.fr` | `mondomaine.fr` | `ext` |
| `a.b.mondomaine.fr` | `mondomaine.fr` | `a.b` |
| `mondomaine.fr` | `mondomaine.fr` | `` (apex de la zone) |

Si `RECORD_FQDN` ne se termine pas par `DNS_ZONE`, le service s'arrête en erreur.

## 5. Utilisation de l'API OVH

Le service s'appuie sur la bibliothèque officielle
[`ovh`](https://github.com/ovh/python-ovh), qui gère de manière transparente la
signature des requêtes (`X-Ovh-Signature`).

| Étape | Méthode | Point d'entrée |
|---|---|---|
| Lister les enregistrements A correspondants | `GET` | `/domain/zone/{zone}/record?fieldType=A&subDomain={sous-domaine}` |
| Lire la cible d'un enregistrement | `GET` | `/domain/zone/{zone}/record/{id}` |
| Mettre à jour un enregistrement | `PUT` | `/domain/zone/{zone}/record/{id}` (corps : `target`) |
| Créer un enregistrement | `POST` | `/domain/zone/{zone}/record` |
| Appliquer les modifications | `POST` | `/domain/zone/{zone}/refresh` |

> **À propos du « refresh ».** OVH prépare les modifications d'enregistrements et
> ne les publie dans la zone active qu'après un `refresh`. Le service appelle
> donc systématiquement `refresh` après une création ou une mise à jour.

### 5.1 Droits API requis

Lors de la génération du token, accordez les droits suivants sur votre zone :

```
GET    /domain/zone/mondomaine.fr/*
PUT    /domain/zone/mondomaine.fr/*
POST   /domain/zone/mondomaine.fr/*
```

## 6. Modèle d'exécution

- **Passage unique (par défaut, `RUN_INTERVAL=0`).** Le conteneur exécute
  `reconcile()` une fois puis quitte avec un code de sortie. Cela répond à
  l'exigence « vérification à chaque démarrage du conteneur ». La ré-exécution se
  fait en relançant le conteneur (manuellement, via un cron de l'hôte ou un timer
  systemd).
- **Boucle (`RUN_INTERVAL>0`).** Le conteneur reste actif et re-vérifie toutes
  les `RUN_INTERVAL` secondes. Les erreurs transitoires sont journalisées sans
  interrompre la boucle.

### 6.1 Codes de sortie (mode passage unique)

| Code | Signification |
|---|---|
| `0` | Succès : aucun changement nécessaire, ou enregistrement mis à jour/créé. |
| `1` | Enregistrement absent et `CREATE_IF_MISSING=false`. |
| `2` | Erreur de configuration (variable manquante, FQDN hors zone). |
| autre | Erreur d'exécution non gérée (échec de résolution IP, erreur API…). |

## 7. Sécurité

- L'image s'exécute avec un utilisateur **non-root** (`appuser`, uid 10001).
- Les secrets résident uniquement dans `.env`, **exclu de Git** et **de l'image**.
- Le token OVH doit être limité à une **seule zone**, et non à tout le compte.
- Aucun port entrant n'est ouvert ; le conteneur ne fait que des appels HTTPS
  sortants.

## 8. Dépendances

- **Exécution :** Docker Engine + plugin Docker Compose.
- **Python :** 3.12 (fourni par l'image de base).
- **Bibliothèque :** `ovh` (version figée dans `requirements.txt`).
- **Bibliothèque standard uniquement** pour la résolution d'IP, la comparaison et
  la journalisation.
