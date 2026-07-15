# Handoff conversions → Lucas (team lead)

**But du doc :** la migration des conversions (positionnel → nommé) est faite à **76 % au niveau carte**
(scan complet des 370 paires de dashboards : **3104 / 4077 tuiles migrées, 973 restantes**).
Le reste, ce sont les décisions **qui demandent un regard humain**. Tu es le point de centralisation : tu
**routes** vers les bonnes personnes et tu **arbitres** le point stratégique. On ne contacte personne en direct,
tout passe par toi.

> Source live des chiffres : `migration/HANDOFF-consultants.csv`, `migration/CONVERSIONS-A-REVOIR-valeur.csv`.
> État global du chantier : `docs/conversion-migration-PROGRESS.md`.

---

## Ce que tu as à faire (vue d'ensemble)

| # | Décision | Volume | Tu routes vers | Fichier à transmettre |
|---|----------|--------|----------------|------------------------|
| **A** | Conversions ambiguës (quel nom ?) | **80 décisions / 33 clients** | les **consultants** (par client) | `HANDOFF-consultants.csv` |
| **B** | Écarts de valeur (chiffre suspect) | **21 lignes / 8 clients** | l'**équipe data** | `CONVERSIONS-A-REVOIR-valeur.csv` |
| **C** | Modèle de mise en prod (liens Nanga) | **1 arbitrage** | **toi + Louis** | ce doc, §C |

**Pas pour toi (info seulement) :** la **couverture technique** (189 cartes « tables larges » / KPIs-evolution)
= notre **dette d'outillage**, on la traite en interne, ça n'attend aucune réponse humaine.

```
76 % des tuiles conversion migrées (3104/4077)
└── 24 % restant (973 tuiles) = ce doc
      ├── A  consultants   80 décisions / 33 clients   ← le gros
      ├── B  équipe data   21 écarts / 8 clients
      └── C  arbitrage prod (toi + Louis)
   (+ couverture technique 189 cartes = NOUS, hors handoff)
```

---

## A. Conversions à trancher → CONSULTANTS

Les anciens dashboards comptaient les conversions **par position** (1ʳᵉ, 2ᵉ…). On passe à des conversions
**nommées** (Purchases, Leads, Sign ups, Custom n…). Pour certaines positions, le nom n'est pas déductible
automatiquement : **seul le consultant qui gère le compte sait**. Deux types de questions :

| Type | Sens | Réponse attendue |
|------|------|------------------|
| **nom?** | la position est utilisée mais **aucune** conversion nommée ne lui correspond | écrire le nom de la conversion |
| **choix** | **plusieurs** noms possibles selon le compte pub | choisir la bonne option |
| **OR** | un « X OR Y » a été saisi dans Airtable, non tranché | choisir X ou Y |

**Comment ça marche :** chaque consultant remplit **seulement les lignes de ses marques** dans
`HANDOFF-consultants.csv` (colonne `client`), écrit sa réponse dans **« ✍️ TA RÉPONSE »**, renvoie le fichier.
On parse en automatique (`parse_consultant_answers.py`) → on re-migre ses dashboards. **2 min par client.**

**Priorité = nombre de dashboards débloqués** (colonne `priorité`). Commencer par le haut.

### Par client (trié par impact)

> 🔥 = ≥ 10 dashboards impactés · 🔸 = 4 à 9 · ▫️ = 1 à 3
> `slots` = nombre de conversions à trancher pour ce client · `dash` = dashboards débloqués

| Client | slots | dash | type |
|--------|:-----:|:----:|------|
| 🔥 Welcome to the Jungle | 3 | 21 | nom? |
| 🔥 24S | 1 | 19 | nom? |
| 🔥 Quitoque | 7 | 16 | nom? |
| 🔥 Lunii | 4 | 16 | nom? |
| 🔥 900.care | 1 | 15 | nom? |
| 🔥 Rivadouce | 3 | 12 | choix |
| 🔥 Jerome Dreyfuss | 1 | 10 | nom? |
| 🔸 Shopinvest | 2 | 9 | nom? |
| 🔸 Les petits culottés | 15 | 8 | nom? |
| 🔸 Quiz Room | 2 | 8 | choix |
| 🔸 Dougs | 2 | 7 | nom? |
| 🔸 Enlaps | 1 | 7 | choix |
| 🔸 U2P | 4 | 6 | choix + nom? |
| 🔸 En Voiture Simone (EVS) | 2 | 6 | nom? |
| 🔸 BeneBono | 1 | 6 | choix |
| 🔸 Father and Sons | 1 | 6 | choix |
| 🔸 Zenchef | 4 | 5 | nom? |
| 🔸 BYmyCAR | 1 | 5 | choix |
| 🔸 Cirque du Soleil | 1 | 5 | nom? |
| 🔸 HomeExchange | 3 | 4 | choix + nom? |
| 🔸 Reputation | 1 | 4 | OR + choix |
| ▫️ Distingo Bank | 3 | 3 | choix + nom? |
| ▫️ Yooji | 3 | 3 | OR + choix + nom? |
| ▫️ CapCar | 1 | 3 | choix |
| ▫️ Goodiespub | 1 | 2 | choix |
| ▫️ Arrago | 2 | 1 | choix |
| ▫️ Be Radiance | 2 | 1 | nom? |
| ▫️ Ecopia | 2 | 1 | choix + nom? |
| ▫️ Richardson | 2 | 1 | nom? |
| ▫️ Absolut Cashmere | 1 | 1 | nom? |
| ▫️ Braxton | 1 | 1 | nom? |
| ▫️ Gamin Tout Terrain | 1 | 1 | choix |
| ▫️ Redesk | 1 | 1 | nom? |

**Total : 80 conversions à trancher, 33 clients.** Les 7 du haut (🔥) débloquent à eux seuls ~100 dashboards.
**Cas le plus lourd : Les petits culottés (15 slots)** mais sur 8 dashboards. Détail ligne à ligne = le CSV.

---

## B. Écarts de valeur → ÉQUIPE DATA

Ici le mapping **existe**, mais notre garde-fou a détecté que la conversion **nommée ≠ le positionnel** qu'elle
remplace. On a **gardé ces tuiles sur l'ancien** (jamais poussé une valeur douteuse). Question pour la data :
**l'écart est-il normal** (le nommé est la « bonne » nouvelle définition → on migre) **ou un bug** de table ?

| Client | Colonne | Positionnel → Nommé | Écart |
|--------|---------|---------------------|:-----:|
| BYmyCAR | CONVERSIONS_5 | 1907,8 → 218 | **−89 %** |
| Lutèce Cosmetics | CONVERSIONS → PURCHASES | 16,6 → 5,3 | **−68 %** |
| Yooji | CONVERSIONS_3 (current) | 9674 → 3744 | **−61 %** |
| Yooji | CONVERSIONS_3 (previous) | 11208 → 4932 | **−56 %** |
| Comptastar | CONVERSIONS → LEADS | 1257,5 → 618 | **−51 %** |
| BYmyCAR | CAC_5 | 2134,8 → 1189 | −44 % |
| Comptastar | CONV_RATE (×8 lignes) | ~0,14 → ~0,08 | −36 à −52 % |
| Comptastar | CAC | 237,9 → 139,7 | −41 % |
| Toploc | CONVERSIONS_1 → CURRENT_LEADS | 38 → 25 | −34 % (systématique) |
| HomeExchange | CONVERSIONS_3 / CR_3 | −7 % | faible |
| TuneCore | CONVERSIONS → PURCHASES | 12381 → 11961 | −3 % (quasi nul) |
| Distingo Bank | CAC_6 | 0 → 284,9 | positionnel **vide** |

**Lectures utiles pour la data (pour ne pas traiter 21 problèmes là où il y en a moins) :**
- **Comptastar = ~1 cause, pas 10.** Ses CONV_RATE / CAC sont **dérivés** du compte de conversions. Si
  `CONVERSIONS → LEADS` est faux (−51 %), tous les ratios suivent mécaniquement. **Trancher LEADS d'abord.**
- **BYmyCAR** : pareil, `CAC_5` découle de `CONVERSIONS_5`. Un seul sujet.
- **Distingo `CAC_6`** : le positionnel valait **0** (slot vide). La valeur nommée n'est pas un « écart »,
  probablement un **faux positif** → à confirmer puis migrer.
- **TuneCore (−3 %) et HomeExchange (−7 %)** : écarts faibles, sans doute attribution/arrondi → migrables.
- **Les gros (BYmyCAR −89 %, Lutèce −68 %, Yooji −56/61 %)** = vrais sujets à creuser avant migration.

> ⚠️ Si la data conclut « ce n'est pas un bug, c'est un **mapping slot→nom faux** », alors la ligne **bascule
> vers le consultant** (panier A) pour re-choisir le bon nom.

---

## C. Arbitrage à trancher (toi + Louis) — mise en prod

Tout est migré sur des **copies** (collection 14016). Une fois 100 % propre, on les **passe en prod**. Deux voies,
une seule à choisir :

| Option | Avantage | Coût |
|--------|----------|------|
| **1. Déplacer les copies** dans les collections clients | aucune retouche des dashboards, propre | **nouveaux ids** → les liens / partages **Nanga** (qui pointent sur les anciens) sont à **re-partager à la main par les GM** |
| **2. Écraser le contenu des originaux** (garde les ids, donc les liens Nanga) | rien à re-partager | = **« refaire »** le contenu sur les originaux — **écarté par Louis** |

➡️ **Décision attendue :** valide-t-on **l'option 1 + re-partage manuel GM** ? (C'est la voie privilégiée ;
le re-partage Nanga reste de toute façon une action GM manuelle, par responsabilisation.)

---

## Hors périmètre (pour info, rien à faire)

- 🔧 **Couverture technique — 189 cartes** (tables « performances » larges + KPIs-evolution + benchmark).
  C'est **notre dette d'outillage** (cascade plus robuste ou carte générique dédiée). **N'attend aucune
  réponse humaine.** Détail : `migration/coverage-cards.json`.
- 🚫 **Exclus du chantier :** 21 clients **inactifs**, + **Vestiaire Collective / Polène / Ray Studios**
  (gérés à la main par Louis), + 11 clients « tout-Gaby » (0 slot mappé).

---

## Fichiers à transmettre

| Destinataire | Fichier | Notice |
|--------------|---------|--------|
| Consultants | `migration/HANDOFF-consultants.csv` | `migration/HANDOFF-consultants-LISEZMOI.md` |
| Équipe data | `migration/CONVERSIONS-A-REVOIR-valeur.csv` | `migration/CONVERSIONS-A-REVOIR-valeur-LISEZMOI.md` |

Round-trip consultant : CSV rempli → `parse_consultant_answers.py` → `consultant-decisions.json` → re-run des
dashboards du client = débloqués.
