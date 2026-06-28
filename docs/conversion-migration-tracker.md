# Migration conversions — SUIVI (généré, ne pas éditer à la main)

> Source : `migration/conv-migration-tracker.json` · régénérer : `conv_tracker.py --render`.
> Ancre de campagne : `[conv-2026-06]`. **124 dashboards** · 121 taggés · 0 anciens archivés.
> Clients : Pro Nutrition (4), Goodiespub (4), Father & Sons (4), Shopinvest (7), Rivadouce (4), 100% Print (1), Absolut Cashmere (1), Braxton (1), Cica Manuka (5), AMV Assurance (1), Be Radiance (1), Ecopia (1), Exaprint (1), CapCar (3), Komilfo (2), Osée (2), Solarock (2), Toploc (1), Dedikazio (1), Dermalogica (1), Shining (1), TuneCore (1), Violette_FR (2), Zeplug (1), France Toner (3), Lutèce Cosmetics (1), My Blend (4), Pulse Protein (4), Sports d'époque (4), BYmyCAR (5), Distingo Bank (3), G-Heat (3), Reputation (4), Arrago (2), HomeExchange (4), Merci Walter (2), Walter (2), Yooji (4), Zenchef (3), Comptastar (7), Fauré Le Page (7), Gamin Tout Terrain (1), Redesk (1), Richardson (1), Steel Shed Solutions (6), Figaret (1).

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
| Dedikazio | Reporting SEO \| | 26490 | 17977 | ✅ | migré | — | — |  |
| Dermalogica | Reporting SEO \| Dermalogica | 26491 | 18042 | ✅ | migré | — | — |  |
| Shining | Global \| Shining | 26492 | 67 | ✅ | migré | — | — |  |
| TuneCore | TuneCore - global perf | 26494 | 11915 | ✅ | migré | — | — |  |
| Violette_FR | Google Analytics \| Violette_FR | 26495 | 6524 | ✅ | migré | — | — |  |
| Violette_FR | Global \| Violette FR | 26496 | 6885 | ✅ | migré | — | — |  |
| Zeplug | Zeplug \| Dashboard | 26493 | 17680 | ✅ | migré | — | — |  |
| France Toner | Perfs Google \| FT | 26524 | 12960 | ✅ | migré | — | — |  |
| France Toner | Global \| France Toner | 26532 | 13950 | ✅ | migré | — | — |  |
| France Toner | SEOxSEA synergies template \| France Toner | 26533 | 14911 | ✅ | migré | — | — |  |
| Lutèce Cosmetics | Lutèce Cosmetics - Funnel by campaign | 26523 | 25401 | ✅ | migré | — | — |  |
| My Blend | Campagnes \| MyBlend | 26526 | 11875 | ✅ | migré | — | — |  |
| My Blend | Global \| MyBlend | 26531 | 11876 | ✅ | migré | — | — |  |
| My Blend | Leviers \| MyBlend | 26537 | 11877 | ✅ | migré | — | — |  |
| My Blend | Campagnes \| Séfia | 26543 | 22167 | ✅ | migré | — | — |  |
| Pulse Protein | Google Ads - Performance Max Template \| Pulse Protein | 26525 | 22035 | ✅ | migré | — | — |  |
| Pulse Protein | E-commerce Multi-Channel Performance Template  | 26529 | 22068 | ✅ | migré | — | — |  |
| Pulse Protein | TikTok -  Global Perf \| Pulse Protein | 26536 | 23223 | ✅ | migré | — | — |  |
| Pulse Protein | E-commerce Campaign Performance Template - Pulse | 26539 | 24147 | ✅ | migré | — | — |  |
| Sports d'époque | Global \| Sports D'Époque | 26527 | 266 | ✅ | migré | — | — |  |
| Sports d'époque | Levier & Campagnes \| Sports D'Époque | 26530 | 6835 | ✅ | migré | — | — |  |
| Sports d'époque | Meta - Focus annonces et formats \| Sports d'Epoque | 26534 | 9936 | ✅ | migré | — | — |  |
| Sports d'époque | Global \| Canopea Paris | 26538 | 18999 | ✅ | migré | — | — |  |
| BYmyCAR | Lead Gen (Multichannel) \| BYmyCAR | 26567 | 2761 | ✅ | migré | — | — |  |
| BYmyCAR | Lead Gen Details \| BYmyCAR | 26568 | 3024 | ✅ | migré | — | — |  |
| BYmyCAR | GAds - Performance max | 26569 | 8670 | ✅ | migré | — | — |  |
| BYmyCAR | Lead Gen (Multichannel) \| BYmyCAR - B2B | 26570 | 17745 | ✅ | migré | — | — |  |
| BYmyCAR | Lead Gen (Multichannel) \| BYmyCAR - Avec évolution | 26571 | 21111 | ✅ | migré | — | — |  |
| Distingo Bank | PSA Banque \| Paid Global | 26572 | 6729 | ✅ | migré | — | — |  |
| Distingo Bank | PSA Banque \| SEA Performances par campagne, adgroup & keyword | 26573 | 6731 | ✅ | migré | — | — |  |
| Distingo Bank | PSA Banque \| Breakdown par conversion | 26574 | 8374 | ✅ | migré | — | — |  |
| G-Heat | Shopify  - Overview template \| G-Heat | 26577 | 11738 | ✅ | migré | — | — |  |
| G-Heat | Ads & Audiences Analysis \| G-Heat | 26578 | 11849 | ✅ | migré | — | — |  |
| G-Heat | Reporting SEO \| G-Heat  | 26579 | 20022 | ✅ | migré | — | — |  |
| Goodiespub | Goodies Pub \| Pilotage | 26575 | 12716 | ✅ | migré | — | — |  |
| Goodiespub | Goodies Pub \| Home | 26576 | 12734 | ✅ | migré | — | — |  |
| Reputation | Performances Globales | 26580 | 5038 | ✅ | migré | — | — |  |
| Reputation | Performances \| Google Ads | 26581 | 7216 | ✅ | migré | — | — |  |
| Reputation | Performances multichannel \| Reputation | 26582 | 8175 | ✅ | migré | — | — |  |
| Reputation | Performances \| LinkedIn | 26583 | 8637 | ✅ | migré | — | — |  |
| Arrago | Suivi des conversions \| Arrago | 26655 | 12862 | ✅ | migré | — | — |  |
| Arrago | Reporting SEO \| Arrago | 26688 | 14780 | ✅ | migré | — | — |  |
| HomeExchange | Leadgen - global perf template (multichannel) \| Home Exchange | 26596 | 10650 | ✅ | migré | — | — |  |
| HomeExchange | Leadgen - global perf template (multichannel) - Home Exchange Collection | 26597 | 14183 | ✅ | migré | — | — |  |
| HomeExchange | Comparaison YoY - HomeExchange | 26598 | 15501 | ✅ | migré | — | — |  |
| HomeExchange | Leadgen - global perf template (multichannel) \| Home Exchange - 2 | 26599 | 21078 | ✅ | migré | — | — |  |
| Merci Walter | Global Overview - Duplicate | 26594 | 13029 | ✅ | migré | — | — |  |
| Merci Walter | Shopify  - Overview template | 26595 | 13356 | ✅ | migré | — | — |  |
| Walter | Homepage Performance \| Walter | 26592 | 20682 | ✅ | migré | — | — |  |
| Walter | Homepage Performance \| Walter FR | 26593 | 21705 | ✅ | migré | — | — |  |
| Yooji | Home - Yooji specific | 26589 | 13818 | ✅ | migré | — | — |  |
| Yooji | Equity - Yooji Specific | 26590 | 13918 | ✅ | migré | — | — |  |
| Yooji | 2. Leviers \| Yooji | 26591 | 16921 | ✅ | migré | — | — |  |
| Zenchef | Zenchef \| Performances Globales | 26600 | 9932 | ✅ | migré | — | — |  |
| Zenchef | Zenchef \| SEA Performances par campagne, adgroup & keyword | 26601 | 9934 | ✅ | migré | — | — |  |
| Zenchef | Zenchef \| Social Performances | 26622 | 9935 | ✅ | migré | — | — |  |
| Comptastar | Global - Comptastar - Lead | 26726 | 411 | ✅ | migré | — | — |  |
| Comptastar | Fb Lead Gen \| Comptastar | 26727 | 682 | ✅ | migré | — | — |  |
| Comptastar | Produits - Comptastar | 26728 | 6789 | ✅ | migré | — | — |  |
| Comptastar | Ad, Adsets Performances_All dim | 26729 | 8901 | ✅ | migré | — | — |  |
| Comptastar | Leviers \| Comptastar - VF | 26730 | 9627 | ✅ | migré | — | — |  |
| Comptastar | Annonce & Adset - Comptastar | 26731 | 9727 | ✅ | migré | — | — |  |
| Comptastar | Global - Comptastar - Purchase | 26732 | 13059 | ✅ | migré | — | — |  |
| Fauré Le Page | Global \| Fauré Le Page | 26733 | 194 | ✅ | migré | — | — |  |
| Fauré Le Page | Google \| Fauré Le Page - Global Perf | 26734 | 6988 | ✅ | migré | — | — |  |
| Fauré Le Page | TikTok -  Global Perf \| Fauré Le Page | 26735 | 10947 | ✅ | migré | — | — |  |
| Fauré Le Page | Global \| Fauré le Page | 26736 | 11858 | ✅ | migré | — | — |  |
| Fauré Le Page | Leviers \| Fauré le Page | 26737 | 11859 | ✅ | migré | — | — |  |
| Fauré Le Page | Campagnes \| Fauré le Page | 26738 | 11860 | ✅ | migré | — | — |  |
| Gamin Tout Terrain | Home \| GTT | 26739 | 14511 | ✅ | migré | — | — |  |
| Redesk | Global - Redesk | 26741 | 20616 | ✅ | migré | — | — |  |
| Richardson | Mattout \| Performances Globales | 26740 | 15999 | ✅ | migré | — | — |  |
| Steel Shed Solutions | Facebook Global \| BMC (Steel Shed Solutions) | 26689 | 436 | ✅ | migré | — | — |  |
| Steel Shed Solutions | Home - Steel Shed Solutions | 26721 | 529 | ✅ | migré | — | — |  |
| Steel Shed Solutions | Leadgen Social - Steel Shed Solutions | 26722 | 10882 | ✅ | migré | — | — |  |
| Steel Shed Solutions | Leadgen - standard dash | 26723 | 11952 | ✅ | migré | — | — |  |
| Steel Shed Solutions | Ecomm - standard dash | 26724 | 12961 | ✅ | migré | — | — |  |
| Steel Shed Solutions | Lead Generation - All Data | 26725 | 24975 | ✅ | migré | — | — |  |
| Fauré Le Page | Consideration \| Fauré le Page | 26745 | 13852 | ✅ | migré | — | — |  |
| Figaret | Global \| Figaret | 26743 | 15336 | ✅ | migré | — | — |  |
| Yooji | Global - Yooji Blended | 26744 | 14313 | ✅ | migré | — | — |  |
