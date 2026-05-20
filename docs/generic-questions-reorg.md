# Réorganisation — Collection `215` « 2. Generic Questions »

> Document de spécification. **Aucune modification appliquée à Metabase** : il décrit
> l'état actuel, la structure cible et le plan de migration.
> Instance : `https://spark.metabaseapp.com/collection/215`

> **Périmètre — Phase 1.** Cette réorganisation couvre **tout sauf la collection
> `18. Nouvelles Conversions`** (`id 11673`), qui reste **inchangée** pour l'instant.
> Elle sera traitée dans une Phase 2 distincte (voir §5). La Phase 1 touche donc
> ~1 212 cartes ; les 1 969 cartes de `Nouvelles Conversions` ne sont pas déplacées.

---

## 1. État actuel (constat)

Relevé via l'API (`/api/collection/{id}/items`, parcours récursif complet) :

- **3 181 cartes** dans **222 collections**, jusqu'à **4 niveaux** de profondeur.
- `18. Nouvelles Conversions` (1 969 cartes) + `01. Global` (585) = **80 % du contenu**.

Répartition des collections de tête :

| Cartes | Collection            | Cartes | Collection            |
|-------:|-----------------------|-------:|-----------------------|
|   1969 | 18. Nouvelles Conversions | 50 | 13. Brand Monitoring  |
|    585 | 01. Global            |     40 | 03. Meta              |
|    128 | 05. Google Analytics 4|     40 | 08. Adjust            |
|    112 | 12. SEO               |      6 | 14. Amazon            |
|    103 | 02. Google            |      5 | 15. Magento           |
|     73 | 06. Industry benchmarks|     4 | 17. Business Plan     |
|      1 | 00. AI / 07. Client Goals | 9  | To sort               |
|      0 | 04. Microsoft, 09. Appsflyer, 10. Pinterest, 16. Spotify | | |

### Problèmes identifiés

1. **Préfixes numériques manuels (`00.`→`18.`)** — hack pour forcer l'ordre.
   Fragile (toute insertion oblige à renuméroter) et incohérent (`00. AI` = 1 carte).
2. **Deux axes de classement mélangés au niveau 1** — plateformes (Google, Meta,
   Microsoft, GA4, Adjust, Appsflyer, Pinterest, Shopify, Amazon, Magento, Spotify)
   ET thèmes transverses (Global, Conversions, Benchmarks, Client Goals, Business
   Plan, AI, SEO, Brand Monitoring). On ne sait pas si on cherche par source ou par sujet.
3. **4 collections plateformes vides** (Microsoft, Appsflyer, Pinterest, Spotify)
   + sous-collections vides (`Correlation cost & key metrics`, `Attribution windows`).
4. **`To sort`** — fourre-tout assumé, jamais vidé (9 cartes orphelines).
5. **Profondeur incohérente** — certaines plateformes découpées par entité
   (Account/Campaign/Adgroup/Ad), d'autres en tas plats : GA4 = 128 cartes à plat,
   Shopify = 55, Industry benchmarks = 73, Adjust = 40.
6. **Cartes en vrac à la racine** — `01. Global` : 214 cartes posées directement à la
   racine + 211 dans `2. Campaign`, alors que les sous-collections par entité existent.
7. **`Nouvelles Conversions` — explosion combinatoire `Conversion × Type de graphique`**
   (détail §5). 1 969 cartes, ~180 collections, dont 15 placeholders `Custom Conversion N`.
8. **Nommage chaotique** — `snake_case` vs espaces (`App_installs` vs `App installs`),
   noms cryptiques (`Cac3`, `Conv3`, `Perifit_check`), espaces en début/fin de nom,
   22 noms de cartes en doublon (44 instances), collection résiduelle `old`.

---

## 2. Principes de la cible

- **Un seul axe au niveau 1** : par usage/famille, pas un mélange.
- **Pas de préfixes numériques.** Metabase trie alphabétiquement ; on ne préfixe
  (`1. `, `2. `…) que là où un ordre métier est réellement nécessaire (entités
  Account→Campaign→Adgroup→Ad).
- **Profondeur homogène : 3 niveaux max** (`Famille / Source / Entité`).
- **Découpage par entité identique pour toutes les plateformes** comparables.
- **Pas de collection vide, pas de fourre-tout.**
- **Le type de graphique n'est jamais un dossier** — c'est une propriété de la carte.
- Une fois la cible atteinte : **figer la structure via le module IaC** (export YAML,
  versionné en git) pour empêcher la dérive de revenir.

---

## 3. Structure cible

```
2. Generic Questions
├── Cross-platform/                  questions génériques multi-plateformes
│   ├── 1. Account
│   ├── 2. Campaign
│   ├── 3. Ad group
│   ├── 4. Ad
│   └── (Conversions/  — Phase 2, voir §5 ; non créée en Phase 1)
│
├── Ad platforms/
│   ├── Google Ads/   1.Account 2.Campaign 3.Ad group 4.Ad · Keyword · Shopping
│   │                 · PMax · Auction Insights
│   ├── Meta/         1.Campaign 2.Ad set 3.Ad · Product (DPA)
│   ├── Microsoft Ads/   (à recréer à la demande)
│   ├── Pinterest/       (à recréer à la demande)
│   ├── Amazon Ads/
│   ├── Spotify/         (à recréer à la demande)
│   ├── Adjust/          (MMP)
│   └── Appsflyer/       (MMP, à recréer à la demande)
│
├── Web & Analytics/
│   ├── Google Analytics 4/   à sous-découper (voir §4)
│   ├── SEO/                  URL Groups · SERP
│   ├── Shopify/              à sous-découper
│   └── Magento/
│
└── Benchmarks & Strategy/
    ├── Industry benchmarks/
    ├── Brand Monitoring/     Brand Monitoring · SEA / SEO synergies
    ├── Client Goals/
    ├── Business Plan/
    └── AI/                   1 carte — à statuer (merger ou archiver)
```

> Pendant la Phase 1, `18. Nouvelles Conversions` **reste telle quelle à la racine de
> la collection 215**, à côté des 4 familles. Elle migrera sous
> `Cross-platform/Conversions/` en Phase 2.

---

## 4. Mapping ancien → nouveau

| Collection actuelle        | Cartes | Destination cible                                   | Action |
|----------------------------|-------:|-----------------------------------------------------|--------|
| 00. AI                     |      1 | `Benchmarks & Strategy/AI/`                         | Déplacer ; statuer (1 carte) |
| 01. Global                 |    585 | `Cross-platform/` (entités)                         | Déplacer + **ranger les 425 cartes en vrac** dans Account/Campaign/Adgroup/Ad |
| 02. Google                 |    103 | `Ad platforms/Google Ads/`                          | Déplacer (structure entités conservée) |
| 03. Meta                   |     40 | `Ad platforms/Meta/`                                | Déplacer |
| 04. Microsoft              |      0 | —                                                   | **Supprimer** (vide) |
| 05. Google Analytics 4     |    128 | `Web & Analytics/Google Analytics 4/`               | Déplacer + **sous-découper** (128 à plat) |
| 06. Industry benchmarks    |     73 | `Benchmarks & Strategy/Industry benchmarks/`        | Déplacer + sous-découper recommandé |
| 07. Client Goals           |      1 | `Benchmarks & Strategy/Client Goals/`               | Déplacer |
| 08. Adjust                 |     40 | `Ad platforms/Adjust/`                              | Déplacer + sous-découper recommandé |
| 09. Appsflyer              |      0 | —                                                   | **Supprimer** (vide) |
| 10. Pinterest              |      0 | —                                                   | **Supprimer** (vide) |
| 11. Shopify                |     55 | `Web & Analytics/Shopify/`                          | Déplacer + sous-découper recommandé |
| 12. SEO                    |    112 | `Web & Analytics/SEO/`                              | Déplacer (URL Groups, SERP conservés) |
| 13. Brand Monitoring       |     50 | `Benchmarks & Strategy/Brand Monitoring/`           | Déplacer |
| 14. Amazon                 |      6 | `Ad platforms/Amazon Ads/`                          | Déplacer |
| 15. Magento                |      5 | `Web & Analytics/Magento/`                          | Déplacer |
| 16. Spotify                |      0 | —                                                   | **Supprimer** (vide) |
| 17. Business Plan          |      4 | `Benchmarks & Strategy/Business Plan/`              | Déplacer |
| 18. Nouvelles Conversions  |   1969 | — (reste à la racine de 215)                        | **Inchangée — hors périmètre Phase 1**, traitée en Phase 2 (§5) |
| To sort                    |      9 | dispatch dans les collections cibles                | Trier les 9 cartes puis **supprimer** la collection |

Sous-collections vides à supprimer aussi : `01. Global / 5. Correlation cost & key
metrics`, `03. Meta / 1. Campaign / Attribution windows`, et `… / Tables / old`.

> **Tas plats à sous-découper** (GA4 128, Industry benchmarks 73, Shopify 55,
> Adjust 40) : le découpage exact dépend du contenu des cartes — il demande une passe
> de lecture des noms/requêtes, hors périmètre de ce document. Suggestion par défaut :
> reprendre le découpage par entité quand il s'applique, sinon par sujet métier.

---

## 5. Phase 2 (hors périmètre actuel) — `Nouvelles Conversions`

> **Cette section ne fait pas partie de la Phase 1.** `18. Nouvelles Conversions` n'est
> **pas touchée** maintenant — ni déplacée, ni renommée, ni régénérée. Elle est
> documentée ici uniquement pour préparer la Phase 2, à mener une fois la Phase 1
> stabilisée. Détail conservé pour mémoire ; à valider/affiner avant exécution.

Le sous-arbre est **produit par un script/template** (confirmé). Inutile de réparer
l'arbre à la main : **la correction se fait dans le générateur**.

### Anti-pattern actuel

```
Conversions {custom|génériques}/
   └── <conversion>/                 29 conversions (15 "Custom Conversion N" + 14 nommées)
         ├── Bar/        ~16 cartes
         ├── Combo/      ~8
         ├── Line/       ~27           ← un dossier par TYPE DE GRAPHIQUE
         ├── Pie/        ~16
         └── Smartscalar/ ~9
```

Deux défauts :
1. **Dossier par type de graphique** — le type est déjà une propriété de la carte
   (et déjà répété dans son nom, ex. `… (Bar Stack - 100%)`). Cela multiplie les
   collections par 5 (~145 dossiers de type au lieu de 0).
2. **Placeholders `Custom Conversion 1…15`** — noms non signifiants ; le générateur
   devrait recevoir le **vrai nom** de la conversion personnalisée du client.

### Cible générateur

```
Cross-platform/Conversions/
   ├── Standard/                       conversions standard
   │     └── <conversion>/             Leads, Purchases, Add to carts, Sign ups, …
   │           └── (toutes les cartes, à plat — ~76 max, sans dossier de type)
   └── Custom/
         └── <nom réel de la conversion>/   plus de "Custom Conversion N"
               └── (toutes les cartes, à plat)
```

Changements à porter dans le script de génération :
- **Supprimer le niveau `Bar/Combo/Line/Pie/Smartscalar`** — émettre les cartes
  directement dans le dossier de la conversion.
- **Paramétrer le nom de conversion** en entrée (remplacer `Custom Conversion N`).
- Conserver le suffixe de désambiguïsation dans le nom de carte **uniquement** quand
  deux cartes partagent métrique + dimensions et ne diffèrent que par la viz.
- Appliquer la convention de nommage §6 à la sortie du générateur.

Effet : ~180 collections → ~31 (2 familles + 29 conversions), 0 perte de carte.

---

## 6. Convention de nommage des cartes

| Règle                       | ✓ Faire                              | ✗ Éviter |
|-----------------------------|--------------------------------------|----------|
| Séparateur                  | espaces                              | `snake_case` (`App_installs`) |
| Casse                       | Sentence case                        | `CAC` vs `Cac` mélangés |
| Espaces parasites           | trim début/fin                       | `« Leads by campaign category »` |
| Suffixe dimensionnel        | `<métrique> by <dim1>, <dim2>`       | ordre/ponctuation variables |
| Noms explicites             | `CAC by date, campaign channel`      | `Cac3`, `Conv3`, `Perifit_check` |
| Type de viz dans le nom     | seulement si désambiguïsation requise | systématique |

À l'issue : **dédoublonner les 22 noms en double** (44 instances). Pour chaque paire :
comparer le `dataset_query` ; si identique → archiver la copie après vérification des
dashboards qui la référencent ; si différente → renommer pour les distinguer.

---

## 7. Nettoyage

- **Supprimer** : `04. Microsoft`, `09. Appsflyer`, `10. Pinterest`, `16. Spotify`
  (vides), `5. Correlation cost & key metrics`, `Attribution windows`, `Tables/old`.
- **Vider `To sort`** : dispatcher les 9 cartes, puis supprimer la collection.
- **Dédoublonner** les 22 noms de cartes répétés (§6).
- Recréer une collection plateforme uniquement quand du contenu existe pour elle.

---

## 8. Plan de migration & sécurité

Ordre conseillé (chaque étape réversible, validée avant la suivante) :

1. **Sauvegarde** — exporter l'état actuel de la collection 215 via le module IaC
   (`spark-metabase export "2. Generic Questions" specs/generic-questions.yaml`),
   commit git. Filet de sécurité pour tout revert.
2. **Créer la nouvelle arborescence vide** (les 4 familles + sous-collections).
3. **Déplacer les collections** existantes vers leur destination (§4). Les IDs de
   cartes ne changent pas → **les dashboards ne sont pas impactés** par un déplacement.
   `18. Nouvelles Conversions` **n'est pas déplacée** (hors périmètre Phase 1).
4. **Ranger les cartes en vrac** de `01. Global` (425 cartes) dans les entités.
5. **Nettoyage** (§7) — suppressions et dédoublonnage en dernier.
6. **Figer** : ré-exporter la structure finale en YAML IaC, versionner en git ; toute
   évolution future passe par `plan`/`apply`.

> **Phase 2** (ultérieure, §5) : correction du générateur de `Conversions`, puis
> migration de `18. Nouvelles Conversions` sous `Cross-platform/Conversions/`.

### Précautions

- **Déplacer une carte/collection** conserve son ID → sans risque pour les dashboards.
- **Archiver/supprimer un doublon** : d'abord vérifier les dashboards qui référencent
  la carte (sinon dashcard cassé).
- **Renommer une carte** n'affecte pas les dashboards (référence par ID) mais casse
  les liens/bookmarks humains — communiquer les renommages.
- Pour toute modification de carte : sauvegarder, tester en différentiel avant/après,
  procéder par échantillon avant traitement en masse, et en cas de régression
  revenir en arrière puis rejouer pour isoler la cause.

---

## 9. Points ouverts

- **`00. AI`** (1 carte) : merger ailleurs, archiver, ou conserver comme amorce ?
- **Découpage des tas plats** (GA4, Industry benchmarks, Shopify, Adjust) : nécessite
  une passe de lecture du contenu — à cadrer dans un second temps.
- **`Standard` vs `Custom`** sous `Conversions` : confirmer que la distinction
  ex-`Conversions génériques` / `Conversions custom` correspond bien.
- **MMP** (Adjust, Appsflyer) : placés sous `Ad platforms/` ; les regrouper dans un
  sous-dossier `MMP/` si leur nombre croît.
