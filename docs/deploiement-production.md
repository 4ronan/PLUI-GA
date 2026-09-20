# Mise en production sans coût d’hébergement supplémentaire

## Architecture retenue

La production utilise uniquement les services déjà disponibles :

- l’hébergement OVH de `zonage-terrain.fr` sert l’interface et trois petits scripts PHP ;
- GitHub Actions exécute le moteur Python à la demande dans le dépôt public ;
- le workflow renvoie le diagnostic et son statut sur OVH par SFTP ;
- OVH conserve les résultats pendant 24 heures pour éviter les recalculs identiques.

Il n’y a ni serveur applicatif permanent, ni base de données, ni abonnement applicatif tiers à prévoir. Docker et `scripts/diagnostic_web_server.py` restent disponibles uniquement pour le développement local.

## URL publique conseillée

Publier le contenu du dossier `public/` dans un sous-dossier du domaine, par exemple :

`https://www.zonage-terrain.fr/diagnostic-vacance/`

La page utilise des chemins relatifs ; elle fonctionne donc à la racine ou dans ce sous-dossier sans modification.

## Secrets GitHub requis

Créer ces secrets dans les paramètres Actions du dépôt :

- `OVH_SFTP_HOST` : serveur SFTP OVH ;
- `OVH_SFTP_PORT` : port SFTP, généralement `22` ;
- `OVH_SFTP_USER` : utilisateur SFTP ;
- `OVH_SFTP_PASSWORD` : mot de passe SFTP ;
- `OVH_DIAGNOSTIC_PATH` : chemin distant exact du dossier public, par exemple `/www/diagnostic-vacance`.

Le workflow manuel `Deploy vacancy diagnostic interface to OVH` publie l’interface. Le workflow `Generate and publish one vacancy diagnostic to OVH` est ensuite déclenché automatiquement par PHP pour chaque nouvelle demande.

## Configuration privée sur OVH

Copier `config/diagnostic.example.php` vers un emplacement non public, par défaut :

`<dossier-parent-du-document-root>/private-zonage-terrain/diagnostic.php`

Renseigner `github_token` avec un jeton GitHub à durée limitée, restreint au seul dépôt `4ronan/PLUI-GA`, avec le droit Actions en écriture. Ne jamais placer ce jeton dans `public/` ou dans le dépôt.

Si OVH utilise une arborescence différente, définir la variable d’environnement `ZT_CONFIG_FILE` avec le chemin absolu du fichier privé.

## Contrat HTTP

Soumission :

```http
POST api/diagnostics.php
Content-Type: application/json

{"territory":"16015","scale":"france"}
```

La réponse `202` fournit `status_url`. La page interroge cette URL jusqu’à l’état `success` ou `failure`, puis charge les JSON publiés sous `diagnostics/<code_INSEE>/`. Une réponse `200` immédiate indique que le cache OVH a été utilisé.

## Maîtrise de l’usage

Les valeurs par défaut sont :

- 3 nouvelles générations par adresse IP et par heure ;
- 30 nouvelles générations par jour au total ;
- cache de 24 heures ;
- déduplication d’une demande identique déjà en cours ;
- expiration d’un suivi bloqué après 45 minutes.

Ces seuils sont modifiables dans le fichier de configuration privé. Ils protègent les quotas GitHub Actions et l’hébergement sans introduire de service tiers.

## Procédure de mise en ligne

1. Ajouter les cinq secrets SFTP au dépôt GitHub.
2. Créer le fichier privé OVH à partir de l’exemple et y renseigner le jeton GitHub.
3. Exécuter manuellement le workflow `Deploy vacancy diagnostic interface to OVH`.
4. Ouvrir l’URL publique et demander Angoulême (`16015`), puis Cognac (`16102`).
5. Vérifier la création de `diagnostics/16015/`, `diagnostics/16102/` et des statuts dans `jobs/`.

## Vérification locale

```bash
ZT_CONFIG_FILE="$PWD/config/diagnostic.example.php" php -S 127.0.0.1:8768 -t public
```

Puis ouvrir `http://127.0.0.1:8768/`. Sans vrai jeton, une demande valide doit répondre que le moteur n’est pas encore activé ; cela permet de tester le frontal sans déclencher de génération.

## Sécurité

- le jeton GitHub reste hors du document root ;
- les dossiers `jobs/` et `runtime/` sont interdits en accès direct par `.htaccess` ;
- seul `jobs.php` restitue un statut dont l’identifiant respecte le format attendu ;
- l’origine du navigateur est contrôlée ;
- les entrées territoire et échelle sont validées avant tout appel externe ;
- les journaux techniques restent dans GitHub Actions pendant sept jours.
