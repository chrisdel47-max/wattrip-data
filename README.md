# wattrip-data

Données trafic de l'appli **Wattrip** (planificateur d'itinéraire pour
véhicule électrique). Ce dépôt est **public** uniquement pour servir un
fichier statique ; le code de l'appli reste privé.

## `traffic.geojson`

Événements routiers (accidents, fermetures, bouchons, travaux) en France,
au format GeoJSON compact. **Régénéré chaque heure** par la GitHub Action
[`refresh.yml`](.github/workflows/refresh.yml) à partir du flux officiel :

> **Source** : [Événements routiers sur le réseau routier national non
> concédé](https://transport.data.gouv.fr/datasets/evenements-routiers-sur-le-reseau-routier-national-non-concede)
> — DATEX II, **Licence Ouverte 2.0**.

URL brute consommée par l'appli :

```
https://raw.githubusercontent.com/chrisdel47-max/wattrip-data/main/traffic.geojson
```

Chaque `feature` est un point avec `{cat, sev, road, desc}` où `cat` ∈
`accident | fermeture | bouchon | travaux`.

Le trafic est une **surcouche en ligne** : l'appli le récupère si le réseau
répond, mais son calcul d'itinéraire reste hors-ligne.
