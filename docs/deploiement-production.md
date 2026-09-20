# Mise en production directe sur OVH

## Architecture retenue

La production fonctionne entièrement sur l’hébergement de `zonage-terrain.fr` :

- OVH sert `public/index.html` et les points d’entrée PHP ;
- `diagnostics.php` valide la demande et écrit un petit fichier JSON dans `runtime/queue/` ;
- une tâche planifiée OVH lance `diagnostic_ovh_worker.py` ;
- ce worker exécute le moteur Python déterministe présent dans `runtime/engine/` ;
- les résultats sont publiés localement dans `diagnostics/<code_INSEE>/<échelle>/` ;
- `jobs.php` fournit au navigateur l’état `queued`, `running`, `success` ou `failure`.

Le calcul ne dépend plus de GitHub Actions. Aucun jeton GitHub n’est requis en production. GitHub reste uniquement le dépôt de code et peut éventuellement servir à déployer les fichiers par SFTP.

## Arborescence distante

Le paquet OVH doit être installé dans le dossier public choisi, par exemple :

```text
www/diagnostic-vacance/
├── index.html
├── api/
├── diagnostics/
├── jobs/
└── runtime/
    ├── .htaccess
    ├── queue/
    ├── cache/
    ├── logs/
    └── engine/
        ├── data/
        ├── output/
        └── scripts/
```

Le `.htaccess` de `runtime/` interdit l’accès HTTP au moteur, aux caches, aux demandes et aux journaux. Le worker y accède directement par le système de fichiers OVH.

## URL publique conseillée

`https://www.zonage-terrain.fr/diagnostic-vacance/`

Tous les appels de l’interface utilisent des chemins relatifs. Le dossier peut donc être renommé ou placé à la racine du domaine.

## Déploiement des fichiers

Le workflow manuel `Deploy vacancy diagnostic and Python engine to OVH` prépare et transfère l’application complète par SFTP. Il ne réalise aucun diagnostic et n’intervient jamais dans le fonctionnement quotidien du site.

Secrets nécessaires uniquement pour ce déploiement automatisé :

- `OVH_SFTP_HOST` ;
- `OVH_SFTP_PORT` ;
- `OVH_SFTP_USER` ;
- `OVH_SFTP_PASSWORD` ;
- `OVH_DIAGNOSTIC_PATH`.

Il est également possible d’envoyer manuellement par SFTP le contenu de `public/`, puis de copier `scripts/` et `data/` dans `public/runtime/engine/`.

## Tâche planifiée OVH obligatoire

Créer dans le panneau OVH une tâche planifiée exécutée toutes les cinq minutes. Le script à lancer est :

`www/diagnostic-vacance/runtime/engine/scripts/diagnostic_ovh_worker.py`

Le fichier possède un shebang Python 3 et peut être appelé directement si OVH le permet. Avec un accès cron classique, utiliser une commande équivalente à :

```bash
/usr/bin/python3 /chemin/absolu/www/diagnostic-vacance/runtime/engine/scripts/diagnostic_ovh_worker.py \
  --site-root /chemin/absolu/www/diagnostic-vacance \
  --max-jobs 1
```

Le chemin de Python et le chemin absolu du compte doivent être vérifiés depuis l’espace client ou en SSH. Une fréquence de cinq minutes signifie qu’une nouvelle demande peut rester quelques minutes dans l’état `queued` avant le début du calcul.

Le verrou `runtime/worker.lock` empêche deux tâches planifiées de calculer simultanément. Une seule demande est traitée par lancement afin de préserver les ressources de l’hébergement mutualisé.

## Configuration PHP facultative

Les valeurs par défaut fonctionnent sans secret. Pour les modifier, copier `config/diagnostic.example.php` vers :

`<dossier-parent-du-document-root>/private-zonage-terrain/diagnostic.php`

Cette configuration permet notamment d’ajuster :

- les origines autorisées ;
- la limite par adresse IP ;
- la limite quotidienne globale ;
- la durée du cache ;
- la taille maximale de la file ;
- le délai avant expiration d’un travail.

## Contrat HTTP

```http
POST api/diagnostics.php
Content-Type: application/json

{"territory":"16015","scale":"france"}
```

Une nouvelle demande reçoit une réponse `202` et un `status_url`. Si un diagnostic récent existe déjà, la réponse est immédiatement `200` avec `cached: true`.

Le navigateur suit ensuite :

```http
GET api/jobs.php?id=<identifiant>
```

À l’état `success`, il charge les fichiers publiés dans `diagnostics/<code_INSEE>/<échelle>/`. Cette séparation empêche le mélange entre un diagnostic comparé au département, à la région ou à la France.

## Maîtrise des ressources

Valeurs par défaut :

- 3 nouvelles générations par IP et par heure ;
- 30 nouvelles générations par jour ;
- 100 demandes au maximum dans la file ;
- cache public et moteur de 24 heures ;
- déduplication d’une demande identique en cours ;
- expiration après deux heures ;
- une génération à la fois.

Lors du contrôle complet réalisé avec Angoulême, la première génération a duré environ 9 min 46 s. La même demande, restaurée depuis le cache, a ensuite été publiée en environ 0,1 s. Ces mesures dépendent du temps de réponse des sources publiques et des ressources attribuées par OVH.

## Vérifications après installation

1. Exécuter manuellement le worker sans demande : il doit afficher `processed: 0`.
2. Ouvrir l’interface et demander Angoulême (`16015`).
3. Vérifier la création d’un fichier dans `runtime/queue/`.
4. Relancer manuellement le worker et suivre le passage de `queued` à `running`, puis `success`.
5. Vérifier `diagnostics/16015/france/diagnostic.json` et la page de résultat.
6. Recommencer avec Cognac (`16102`).
7. Vérifier qu’une seconde demande identique utilise le cache.

## Sécurité

- aucune commande fournie par l’utilisateur n’est exécutée ; territoire et échelle sont validés par PHP puis par Python ;
- les identifiants de travaux sont générés aléatoirement côté serveur ;
- `runtime/` et `jobs/` sont interdits en accès HTTP direct ;
- les écritures JSON et les publications sont atomiques ;
- les calculs sont sérialisés par verrou fichier ;
- aucun secret GitHub n’est présent sur OVH ;
- les journaux techniques restent dans `runtime/logs/`, inaccessible depuis le web.
