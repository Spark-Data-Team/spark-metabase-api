# Migration conversions — SUIVI (généré, ne pas éditer à la main)

> Source : `migration/conv-migration-tracker.json` · régénérer : `conv_tracker.py --render`.
> Ancre de campagne : `[conv-2026-06]`. **43 dashboards** · 40 taggés · 0 anciens archivés.
> Clients : Pro Nutrition (4), Goodiespub (2), Father & Sons (4), Shopinvest (7), Rivadouce (4), 100% Print (1), Absolut Cashmere (1), Braxton (1), Cica Manuka (5), AMV Assurance (1), Be Radiance (1), Ecopia (1), Exaprint (1), CapCar (3), Komilfo (2), Osée (2), Solarock (2), Toploc (1).

Statuts : `migré` (copie faite) · `validé` (consultant OK) · `archive_old:true` (opt-in pour archiver l'ancien) · `old_archived` (ancien archivé). L'archivage des anciens est piloté par `archive_superseded.py` et ne touche QUE les lignes `archive_old:true`.

| Client | Dashboard | Copie | Original | Taggé | Statut | Archiver ancien | Ancien archivé | Notes |
|---|---|---|---|---|---|---|---|---|
| Pro Nutrition | Home | 25566 | 14118 | ✅ | validé (Lucas) | — | — | pilote étape 1 |
| Pro Nutrition | Ecommerce Sopral | 25567 | 16557 | ✅ | validé (Lucas) | — | — | pilote étape 1 |
| Pro Nutrition | Global perf (14016) | 25632 | 14016 | ✅ | validé (Lucas) | — | — | pilote étape 1 |
| Goodiespub | Home | 25764 | 12734 | ✅ | migré | — | — |  |
| Goodiespub | Pilotage | 25765 | 12716 | ✅ | migré | — | — |  |
| Father & Sons | Ecomm \| Home | 25831 | 13323 | ✅ | migré | — | — | le plus complet, tout est migré |
| Father & Sons | Ecomm \| Pilotage | 25833 | 11804 | ✅ | migré | — | — |  |
| Father & Sons | Noto \| Home | 25834 | 15963 | ✅ | migré | — | — |  |
| Father & Sons | Shopify | 25836 | 22860 | ✅ | migré | — | — | à onglets |
| Shopinvest | Global | 25896 | 422 | ✅ | migré | — | — |  |
| Shopinvest | Focus Marge | 25897 | 8803 | ✅ | migré | — | — |  |
| Shopinvest | Verticales | 25900 | 918 | ✅ | migré | — | — |  |
| Shopinvest | Focus levier | 25901 | 6855 | ✅ | migré | — | — |  |
| Shopinvest | Global (2) | 25902 | 23 | ✅ | migré | — | — |  |
| Shopinvest | MOAS | 25929 | 8703 | ✅ | migré | — | — |  |
| Rivadouce | Perfs globales | 25931 | 16458 | ✅ | migré | — | — |  |
| Rivadouce | Perfs par levier | 25932 | 16459 | ✅ | migré | — | — |  |
| Rivadouce | Perf par campagne | 25937 | 17780 | ✅ | migré | — | — |  |
| Pro Nutrition | Google Analytics 4 - Spec |  | 14049 | — | GA4 — à migrer (bloqué amont) | — | — | 8 tuiles GA4 — rattraper quand analytics.* aura les colonnes nommées |
| Rivadouce | GA4 Overview |  | 15372 | — | GA4 — à migrer (bloqué amont) | — | — | 4 tuiles GA4 — rattraper quand analytics.* aura les colonnes nommées |
| Shopinvest | Analytics - Main |  | 863 | — | GA4 — à migrer (bloqué amont) | — | — | 5 tuiles GA4 — rattraper quand analytics.* aura les colonnes nommées |
| 100% Print | 100% Print \| Home | 26127 | 13983 | ✅ | migré (étape 3) | — | — | 8/8 tuiles new. Avant/après IDENTIQUE sur fenêtre large (953.4 conv / 225 340€ rev / CAC 171.77 / ROAS 5.69). slot Main→Purchases (live Airtable OK). 1 carte générée 49590 (sandbox 13950). Staging coll 14016. À valider. |
| Absolut Cashmere | Performances par marché | 26164 | 14116 | ✅ | migré+basculé ✅ | — | — | Absolut Cashmere: 13/16 reuse + bascule OK. 3 tuiles slots non mappés (1/3-5-6) sur tableau by-location. Avant/après à confirmer. |
| Braxton | Braxton Indivision - Global Perf | 26193 | 9336 | ✅ | migré+basculé ✅ | — | — | Braxton: 8/14 + bascule OK (débloqué par fix LATERAL sur carte 4854). Restent tables 2-dim/multi-slot + Conversions 3 sur ancien. |
| Cica Manuka | Home | 26197 | 11245 | ✅ | migré+basculé ✅ | — | — | Cica Home: 6/8 → 100%. |
| Cica Manuka | PMax | 26198 | 11248 | ✅ | migré+basculé ✅ | — | — | Cica PMax: 2/5 + bascule OK. 1 gen 'search terms' rendu KO. |
| Cica Manuka | Meta \| Cica Manuka - Focus annonces et formats | 26325 | 6846 | ✅ | migré | — | — |  |
| Cica Manuka | Meta \| Cica Manuka - Focus annonces et formats | 26358 | 6846 | ✅ | migré | — | — |  |
| Cica Manuka | Meta \| Cica Manuka - Focus annonces et formats | 26391 | 6846 | ✅ | migré | — | — |  |
| AMV Assurance | Social Ads - Overview Template \| Lead Generation | 26424 | 22794 | ✅ | migré | — | — |  |
| Be Radiance | Performances \| Overview \| BeRadiance | 26428 | 10155 | ✅ | migré | — | — | subagent a lancé 2x; copie orpheline 26425 archivée; 0 table swappable (slots non mappes -> Gaby) |
| Ecopia | Ecopia \| Home | 26426 | 11744 | ✅ | migré | — | — |  |
| Exaprint | Reporting SEO \| Exaprint | 26427 | 18544 | ✅ | migré | — | — |  |
| CapCar | CapCar - Homepage | 26461 | 16195 | ✅ | migré | — | — |  |
| CapCar | Recrutement Agents | 26464 | 16260 | ✅ | migré | — | — |  |
| CapCar | CapCar - Performances by adset/ad | 26466 | 16689 | ✅ | migré | — | — |  |
| Komilfo | Home - Komilfo | 26458 | 25005 | ✅ | migré | — | — |  |
| Komilfo | SEA -- Overview (leadgen) - Komilfo | 26463 | 25071 | ✅ | migré | — | — |  |
| Osée | Blended Overview \| Osée | 26460 | 15767 | ✅ | migré | — | — |  |
| Osée | Osée \| Home | 26465 | 16392 | ✅ | migré | — | — |  |
| Solarock | Solarock - performance par adset meta  | 26459 | 18207 | ✅ | migré | — | — |  |
| Solarock | Solarock - Perf par adset | 26462 | 19857 | ✅ | migré | — | — |  |
| Toploc | Lead  Overview \| Toploc | 26457 | 16755 | ✅ | migré | — | — |  |
