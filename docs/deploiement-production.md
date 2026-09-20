# Mise en production du diagnostic de vacance

## Architecture retenue

Le service réunit dans un même conteneur :

- l’interface publique `public/index.html` ;
- l’API asynchrone `scripts/diagnostic_web_server.py` ;
- le moteur déterministe appelé par `scripts/diagnostic_request.py` ;
- le cache persistant placé dans `DIAG_CACHE_DIR`.

Une seule génération est exécutée à la fois. Cette contrainte est volontaire : les étapes historiques utilisent encore des fichiers intermédiaires communs dans `output/`. La file HTTP absorbe les demandes concurrentes et déduplique les requêtes identiques déjà en cours.

## Déploiement rapide avec Docker

```bash
docker build -t zonage-terrain-vacance .
docker run --rm -p 8765:8765 -v diagnostic-cache:/data zonage-terrain-vacance
```

Vérifications :

```bash
curl --fail http://127.0.0.1:8765/api/health
curl --fail http://127.0.0.1:8765/api/ready
```

Le fichier `render.yaml` fournit un déploiement Render avec disque persistant de 5 Go. Le plan doit permettre un processus toujours actif : une mise en veille pendant une génération interromprait le travail en mémoire.

## Contrat HTTP public

Soumission :

```http
POST /api/diagnostics
Content-Type: application/json

{"territory":"16015","scale":"france"}
```

La réponse HTTP 202 fournit `status_url`. Cette URL est interrogée jusqu’à l’état `success` ou `failure`. Après succès, `result_url` pointe vers la page publiée sous `/diagnostics/16015/`.

## Variables principales

- `PORT` : port d’écoute, 8765 par défaut ;
- `DIAG_CACHE_DIR` : cache persistant ;
- `DIAG_CACHE_TTL_HOURS` : durée de validité, 24 heures par défaut ;
- `DIAG_JOB_QUEUE_LIMIT` : nombre maximal de demandes en attente ;
- `DIAG_RATE_LIMIT_PER_MINUTE` : limite de soumissions par adresse ;
- `DIAG_GENERATION_TIMEOUT_SECONDS` : délai maximal d’une génération.

## Conditions avant ouverture au public

1. Les workflows Angoulême et Cognac doivent rester verts pour les sorties HTML et JSON.
2. Le test du service web doit valider `/api/health`, `/api/ready`, les en-têtes de sécurité et les erreurs d’entrée.
3. Le répertoire monté sur `DIAG_CACHE_DIR` doit être persistant et accessible en écriture.
4. Le domaine public doit terminer HTTPS et transmettre les requêtes au port du conteneur.
5. Après déploiement, lancer un diagnostic Angoulême puis Cognac et vérifier leurs pages publiées.
