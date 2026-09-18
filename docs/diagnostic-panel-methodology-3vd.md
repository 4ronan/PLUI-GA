# Sélection automatique du panel comparable — 3V-D

## Objet

Le panel comparable sert uniquement à construire des références statistiques communales pour le diagnostic de vacance.

Il ne constitue ni un classement des communes, ni un score territorial, ni une mesure de performance.

L’utilisateur fournit uniquement :

- le code INSEE de la commune cible ;
- l’échelle de comparaison souhaitée : département, région ou France.

Le nom officiel de la commune et les 15 communes de référence sont résolus automatiquement.

## Taille et périmètre

Le panel comprend exactement 15 communes distinctes, commune cible exclue.

L’échelle demandée est utilisée tant qu’elle contient au moins 15 communes exploitables.

En cas d’effectif insuffisant :

- département → région → France ;
- région → France ;
- France → pas d’élargissement supplémentaire.

L’échelle demandée et l’échelle effectivement utilisée sont toutes deux conservées dans les sorties.

## Sources de sélection

### Socle administratif

API Découpage administratif — communes  
Producteur : DINUM / Etalab

Données utilisées :

- code INSEE ;
- nom ;
- département ;
- région ;
- population ;
- surface.

Population et surface servent uniquement à calculer des proximités relatives entre communes.

### Grille communale de densité Insee

Fichier : grille de densité au 1er janvier 2026  
Source officielle Insee : `fichier_diffusion_2026.xlsx`

Variables utilisées :

- `DENS7` ;
- `LIBDENS7`.

La grille Insee est préférée à une simple densité moyenne car elle prend en compte la concentration spatiale de la population.

### Aires d’attraction des villes

Base AAV 2020 au 1er janvier 2026  
Source officielle Insee : `AAV2020_au_01-01-2026.zip`

Variables utilisées :

- `AAV2020` ;
- `CATEAAV2020` ;
- `TAAV2017` ;
- `TDAAV2017`.

Les catégories communales sont notamment :

- 11 : commune-centre ;
- 12 : autre commune du pôle principal ;
- 13 : commune d’un pôle secondaire ;
- 20 : commune de la couronne ;
- 30 : commune hors attraction des villes.

## Règle de sélection 3V-D

Le tri est déterministe.

### 1. Proximité de population

La population reste le premier filtre.

- bande 0 : 70 % à 130 % de la population de la cible ;
- bande 1 : 50 % à 200 % ;
- bande 2 : autres communes.

Une commune d’une bande plus éloignée ne peut pas évincer une commune disponible dans une bande plus proche tant que la bande proche suffit à remplir le panel.

### 2. Proximité de densité Insee

À bande de population identique, la distance entre classes `DENS7` est minimisée.

### 3. Rôle dans l’AAV

À proximité de densité identique, la sélection privilégie le même rôle territorial.

Les différentes catégories de pôles sont considérées plus proches entre elles que d’une couronne ; une commune hors attraction est la catégorie la plus éloignée d’une commune appartenant à une AAV.

### 4. Taille de l’AAV

La tranche de taille officielle de l’AAV est ensuite utilisée comme critère de proximité.

### 5. Distance structurelle continue

Les derniers départages utilisent :

`0,65 × |log(ratio population)| + 0,35 × |log(ratio densité moyenne)|`

Cette distance sert seulement au choix des communes de référence.

Elle ne constitue jamais un score du territoire cible.

### 6. Départage final

Le code INSEE assure un ordre entièrement déterministe en cas d’égalité parfaite.

## Fallback 3V-A

Si les zonages Insee 2026 ne sont temporairement pas disponibles, le diagnostic n’est pas bloqué.

Le sélecteur revient à la méthode validée 3V-A :

1. bande de population ;
2. distance structurelle population / densité moyenne ;
3. code INSEE.

La sortie indique alors explicitement :

`algorithm = 3V-A-structural-v1`

Lorsque les zonages Insee sont utilisés :

`algorithm = 3V-D-insee-typology-v2`

## Séparation avec le diagnostic

Les variables suivantes servent uniquement à choisir le panel :

- DENS7 ;
- rôle AAV ;
- taille AAV ;
- distance de sélection.

Elles ne deviennent jamais :

- des facteurs discriminants ;
- des hypothèses explicatives ;
- des leviers ;
- des priorités ;
- un score global.

Le diagnostic continue d’utiliser ses univers métiers propres : LOVAC, INSEE RP, Filosofi, DVF, Sitadel et RPLS.

## Données manquantes

Une donnée métier manquante n’est jamais transformée en zéro.

Les effectifs de référence sont calculés par indicateur.

Un facteur n’est classé discriminant que si au moins deux tiers du panel demandé sont réellement disponibles pour cet indicateur.

## Traçabilité

La sortie `output/diagnostic-3v-panel.json` conserve notamment :

- la commune cible ;
- l’échelle demandée ;
- l’échelle effective ;
- l’algorithme ;
- les 15 codes du panel ;
- leur rang de sélection ;
- population et surface ;
- DENS7 et libellé ;
- catégorie et aire AAV ;
- distances de sélection ;
- hashes des fichiers Insee utilisés ;
- compte des communes par bande de population ;
- statut de qualité.

La page 3R publie la composition du panel dans un bloc méthodologique repliable.

## Cache

Le cache de production dépend de :

- la commune ;
- l’échelle ;
- les 15 codes ;
- l’algorithme et les métadonnées du panel ;
- les hashes des zonages Insee ;
- l’empreinte du moteur ;
- les snapshots locaux du diagnostic.

Une modification du panel ou de ses sources invalide donc le cache.

## Principe d’interprétation

Une évolution de la composition du panel peut modifier les percentiles, donc les facteurs discriminants et les hypothèses déterministes.

Cela ne prouve pas qu’un panel est « meilleur » au sens causal.

La validation 3V-E compare les sorties 3V-A et 3V-D sur un même territoire et une même échelle afin de documenter cet effet sans produire de classement des méthodes.
