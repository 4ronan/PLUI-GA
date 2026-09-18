# 3V-E — Sensibilité du diagnostic au panel comparable

## Cas testé

Commune : Cognac  
Code INSEE : 16102  
Échelle : France  
Date de validation : 18 septembre 2026

Deux diagnostics complets ont été générés avec exactement le même moteur et les mêmes sources métier.

Seule la méthode de sélection des 15 communes du panel diffère :

- fallback 3V-A : proximité de population puis distance population/densité moyenne ;
- 3V-D : même priorité de population, enrichie par la grille de densité Insee et le rôle/taille AAV.

Les deux chaînes atteignent 3T-M avec le statut valide.

## Composition du panel

Intersection entre les deux panels : **2 communes sur 15**.

Le test à l’échelle France montre donc que l’ajout des typologies Insee peut modifier fortement la composition du panel, même lorsque la bande de population reste prioritaire.

## Résultat global

| Élément | 3V-A | 3V-D |
|---|---:|---:|
| KPI | 8 | 8 |
| Facteurs discriminants | 6 | 6 |
| Hypothèses | 0 | 0 |
| Priorités | 1 | 1 |

Le message de synthèse est identique dans les deux cas :

> La vacance privée n’est pas atypique dans le panel ; le diagnostic met en évidence des contextes discriminants distincts à examiner sans causalité automatique.

La priorité opérationnelle reste également identique :

**Qualifier et localiser la vacance privée avant toute intervention ciblée.**

## Facteurs discriminants 3V-A

- évolution de la population 2017-2023 ;
- évolution des ménages 2017-2023 ;
- vacance du parc social ;
- part du parc social âgé de 40 ans ou plus ;
- prix médian DVF ;
- part des appartements parmi les logements vacants INSEE.

## Facteurs discriminants 3V-D

- niveau de vie médian ;
- taux de pauvreté ;
- vacance du parc social ;
- part du parc social âgé de 40 ans ou plus ;
- part des appartements parmi les logements vacants INSEE ;
- part des logements vacants construits entre 1946 et 1990.

## Facteurs discriminants stables dans les deux panels

Trois facteurs restent discriminants dans les deux configurations :

- vacance du parc social ;
- part du parc social âgé de 40 ans ou plus ;
- part des appartements parmi les logements vacants INSEE.

## Facteurs sensibles à la composition du panel

Les autres classifications discriminantes changent selon le panel.

Cela confirme que les percentiles doivent être interprétés comme des positions **relatives au panel choisi**, et non comme des propriétés absolues de la commune.

Cette sensibilité ne remet pas en cause les valeurs brutes communales ; elle concerne uniquement leur position comparative.

## Conséquence méthodologique

La page finale doit :

1. publier la composition du panel ;
2. indiquer la méthode de sélection ;
3. rappeler que les percentiles sont conditionnels à ce panel ;
4. ne jamais présenter un facteur discriminant comme une cause prouvée ;
5. conserver les hypothèses et priorités comme règles déterministes prudentes.

Le test 3V-E ne sert pas à déclarer 3V-D « meilleur » par un score.

Il montre que 3V-D produit un référentiel structurellement différent et que le moteur doit rendre visible cette dépendance du diagnostic relatif au panel.
