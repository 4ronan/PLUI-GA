# Point d’entrée de production du diagnostic — 3W

## Commande minimale

Le moteur peut désormais être appelé avec deux informations seulement :

```bash
python scripts/diagnostic_request.py <code_INSEE> <échelle>
```

Exemple :

```bash
python scripts/diagnostic_request.py 16102 france
```

L’utilisateur n’a pas à fournir :

- le nom de la commune ;
- les 15 communes du panel ;
- les codes département/région ;
- les paramètres des sources métier.

Le nom officiel et le panel comparable sont résolus automatiquement.

## Échelles acceptées

Les valeurs suivantes sont acceptées :

### Département

- `département`
- `departement`
- `department`
- `dept`

Valeur interne normalisée :

`department`

### Région

- `région`
- `region`

Valeur interne :

`region`

### France

- `france`
- `national`
- `nationale`

Valeur interne :

`france`

## Résolution du panel

Le point d’entrée supprime volontairement de son environnement :

- `DIAG_COMMUNE_NAME` ;
- `DIAG_PANEL_CODES` ;
- les marqueurs de provenance correspondants.

Il impose donc la résolution automatique du nom et du panel.

Par défaut, le panel est sélectionné avec :

`3V-D-insee-typology-v2`

Si les zonages Insee 2026 sont temporairement indisponibles :

`3V-A-structural-v1`

est utilisé comme fallback déterministe.

## Cache

Le cache est activé par défaut.

Premier appel :

```json
{
  "cache": {
    "hit": false,
    "reason": "cache_absent"
  }
}
```

Appel identique ultérieur avec cache valide :

```json
{
  "cache": {
    "hit": true,
    "reason": "request_index_valid_cache",
    "fast_path": true
  }
}
```

Pour une requête utilisateur minimale `territoire + échelle`, ce chemin rapide intervient **avant** toute nouvelle résolution du panel. Un diagnostic encore valide peut donc être servi même si l’API administrative est temporairement indisponible.

Le fast cache reste désactivé lorsqu’un override technique `DIAG_PANEL_CODES` ou `DIAG_COMMUNE_NAME` est fourni.

La clé dépend notamment :

- du territoire ;
- de l’échelle ;
- du nom résolu ;
- des 15 codes du panel ;
- des métadonnées 3V-D du panel ;
- des hashes des zonages Insee ;
- de l’empreinte du moteur ;
- des snapshots locaux.

Le cache conserve également une copie hashée du fichier `diagnostic-3v-panel.json` et du manifeste 3U-A. Les cinq fichiers publiés, le panel et le manifeste sont tous contrôlés avant réutilisation.

## Recalcul forcé

```bash
python scripts/diagnostic_request.py 16102 france --force-refresh
```

Le cache existant n’est pas utilisé pour répondre à cet appel.

## Exécution sans cache

```bash
python scripts/diagnostic_request.py 16102 france --no-cache
```

Le runner 3U-A est appelé directement.

## Réponse de succès

La sortie standard contient un seul objet JSON exploitable par un service appelant.

Exemple de structure :

```json
{
  "status": "success",
  "territory": "16102",
  "commune_name": "Cognac",
  "comparison_scale_requested": "france",
  "comparison_scale_effective": "france",
  "panel_source": "3V-D-insee-typology-v2",
  "panel_reference_n": 15,
  "cache": {
    "hit": false,
    "reason": "cache_absent",
    "fast_path": false,
    "key": "..."
  },
  "quality": {
    "status": "ok"
  },
  "published": {
    "html": "output/published/16102/index.html",
    "diagnostic": "output/published/16102/diagnostic.json",
    "synthesis": "output/published/16102/synthesis.json",
    "levers": "output/published/16102/levers.json",
    "priorities": "output/published/16102/priorities.json"
  }
}
```

## Validation locale des entrées

Les erreurs de forme sont rejetées avant tout appel réseau.

### Code INSEE invalide

```json
{
  "status": "failure",
  "phase": "input_validation",
  "territory": "ABC",
  "error": {
    "type": "invalid_territory",
    "message": "code INSEE communal attendu sur 5 caractères alphanumériques"
  }
}
```

### Échelle invalide

```json
{
  "status": "failure",
  "phase": "input_validation",
  "territory": "16102",
  "comparison_scale": "invalide",
  "error": {
    "type": "invalid_scale",
    "message": "échelle attendue: département, région ou France"
  }
}
```

Le code de retour est non nul.

## Échec de résolution du panel

Si la commune ne peut pas être résolue ou si les données nécessaires au préflight sont indisponibles, les manifests 3U-A/3U-B conservent :

```json
{
  "status": "failure",
  "phase": "panel_selection"
}
```

Le dernier diagnostic publié antérieurement n’est pas effacé.

## Échec pendant le diagnostic

Le point d’entrée retourne :

- la phase disponible dans le manifest ;
- le type et le message de l’erreur ;
- les dernières lignes utiles du journal ;
- un code de retour non nul.

Une génération défaillante n’est jamais publiée par-dessus une publication valide.

## Invariants avant publication

Le runner n’écrit les cinq artefacts publiés qu’après :

1. exécution des contrats sources ;
2. assemblage et interprétation ;
3. détection des facteurs ;
4. hypothèses, synthèse, leviers et priorités ;
5. génération 3R ;
6. validation 3T-M.

Chaque étape doit avoir produit une sortie fraîche, non vide.

## Concurrence

La chaîne utilise encore des fichiers intermédiaires globaux dans `output/`.

Les exécutions de production sont donc sérialisées par verrou fichier afin d’éviter le mélange de deux territoires exécutés simultanément dans le même espace de travail.

Les identifiants de runs restent uniques.

## Publication

Les cinq fichiers canoniques sont :

- `index.html` ;
- `diagnostic.json` ;
- `synthesis.json` ;
- `levers.json` ;
- `priorities.json`.

Ils sont remplacés atomiquement.

Un cache hit restaure également les fichiers sans supprimer préalablement le dossier publié.

## Page test interactive locale

Une interface de test est disponible dans :

`tests/diagnostic-vacance-page-test.html`

Le serveur local standard-library se lance avec :

```bash
python scripts/diagnostic_test_server.py
```

Puis ouvrir :

`http://127.0.0.1:8765/`

La page appelle :

`/api/diagnostic?territory=<code>&scale=<échelle>`

Le serveur délègue intégralement le calcul à `diagnostic_request.py`. Le navigateur ne calcule ni facteur, ni percentile, ni hypothèse.

Sans serveur, la page peut lire des JSON déjà publiés. Pour Cognac/France seulement, une démonstration validée est embarquée afin que la page reste consultable hors ligne.

## Provenance des sources et millésimes

La page 3R expose désormais sept blocs de provenance :

- LOVAC : taux 2025, volumes 2026 ;
- INSEE LOG1 : 2023 ;
- DVF : fenêtre 2021–2025, avec dernier millésime exploitable ;
- INSEE démographie/logement : évolution 2017–2023 ;
- Filosofi : 2021 ;
- Sitadel : millésimes distincts pour autorisations et mises en chantier ;
- RPLS : 2025.

Chaque bloc conserve également son statut qualité et sa politique de disponibilité. Les millésimes restent distincts : ils ne sont jamais fusionnés pour construire un indicateur synthétique.

## Principe de sécurité méthodologique

Le point d’entrée n’ajoute aucune intelligence générative au diagnostic.

Il orchestre exclusivement le moteur déterministe existant.

Les règles restent notamment :

- aucune valeur manquante convertie en zéro ;
- aucun score global ;
- aucun lien causal automatique ;
- séparation des univers statistiques ;
- seuil minimal de panel comparable ;
- transparence de la composition du panel ;
- ordre opérationnel distinct d’un classement d’efficacité.


## Batch multi-communes

Le moteur peut désormais traiter plusieurs communes séquentiellement avec le même contrat de production :

```bash
python scripts/diagnostic_batch.py 16102,16015,19031 france
```

Un fichier texte ou CSV simple peut également être passé à la place de la liste.

Le batch :

- déduplique les codes ;
- valide les codes avant toute génération ;
- appelle le point d’entrée unitaire pour chaque commune ;
- réutilise le cache lorsque disponible ;
- conserve l’ordre de la demande ;
- retourne un résumé JSON avec le nombre de succès et d’échecs ;
- reste séquentiel afin de respecter le verrou de l’espace de travail et de limiter la pression sur les API externes.

Exemple de réponse :

```json
{
  "status": "success",
  "requested_n": 3,
  "processed_n": 3,
  "success_n": 3,
  "failure_n": 0,
  "comparison_scale": "france",
  "territories": ["16102", "16015", "19031"],
  "results": []
}
```

### Endpoint HTTP de batch

Le serveur de test expose également :

`POST /api/batch`

Corps JSON :

```json
{
  "territories": ["16102", "16015", "19031"],
  "scale": "france",
  "refresh": false,
  "stop_on_error": false
}
```

Le serveur retourne HTTP 200 lorsque toutes les communes ont été générées, ou 207 lorsque le traitement est partiel.

Le batch ne parallélise volontairement pas les diagnostics complets : la chaîne de production utilise encore un espace intermédiaire partagé et certaines sources externes appliquent des limitations de débit.
