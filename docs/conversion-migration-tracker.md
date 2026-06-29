# Migration conversions — SUIVI (généré, ne pas éditer à la main)

> Source : `migration/conv-migration-tracker.json` · régénérer : `conv_tracker.py --render`.
> Ancre de campagne : `[conv-2026-06]`. **373 dashboards** · 370 taggés · 0 anciens archivés.
> Clients : Pro Nutrition (4), Goodiespub (4), Father & Sons (4), Shopinvest (17), Rivadouce (19), 100% Print (1), Absolut Cashmere (1), Braxton (1), Cica Manuka (5), AMV Assurance (1), Be Radiance (1), Ecopia (1), Exaprint (1), CapCar (3), Komilfo (2), Osée (2), Solarock (2), Toploc (1), Dedikazio (1), Dermalogica (1), Shining (1), TuneCore (1), Violette_FR (2), Zeplug (1), France Toner (3), Lutèce Cosmetics (1), My Blend (4), Pulse Protein (4), Sports d'époque (4), BYmyCAR (5), Distingo Bank (3), G-Heat (3), Reputation (4), Arrago (2), HomeExchange (4), Merci Walter (2), Walter (2), Yooji (4), Zenchef (3), Comptastar (7), Fauré Le Page (7), Gamin Tout Terrain (1), Redesk (1), Richardson (1), Steel Shed Solutions (6), Figaret (1), Inoui Editions (8), Inter Invest (3), Superdiet (6), Virgil (8), Bambinos (1), Belveo (9), Funkie (2), 24S (14), 900.care (15), BeneBono (6), Cirque du Soleil (7), Dougs (8), En Voiture Simone (EVS) (6), Enlaps (8), Father and Sons (6), Gestion immobilière Walter inc. (4), Jerome Dreyfuss (11), LA Bruket (8), Les petits culottés (10), LocaBoat Group (7), Lunii (17), Perifit (10), Quitoque (18), Quiz Room (10), Tradis (1), U2P (6), Welcome to the Jungle (15).

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
| Inoui Editions | Global \| Inoui Editions | 26754 | 329 | ✅ | migré | — | — |  |
| Inoui Editions | Global 2025 \| Inoui Editions | 26787 | 14445 | ✅ | migré | — | — |  |
| Inoui Editions | Inoui \| GA4 Audiences | 26788 | 15601 | ✅ | migré | — | — |  |
| Inoui Editions | Inoui Editions \| Global PoP | 26789 | 15865 | ✅ | migré | — | — |  |
| Inoui Editions | Inoui \| Noto | 26790 | 15930 | ✅ | migré | — | — |  |
| Inoui Editions | SEA Global Overview (Google & Microsoft) Template - Inoui | 26791 | 20288 | ✅ | migré | — | — |  |
| Inoui Editions | Multi-Country Performance  - Inoui | 26792 | 23124 | ✅ | migré | — | — |  |
| Inoui Editions | E-commerce Campaign Performance Template - Inoui | 26793 | 24609 | ✅ | migré | — | — |  |
| Inter Invest | Global \| Inter Invest | 26808 | 15 | ✅ | migré | — | — |  |
| Inter Invest | Inter Invest \| SEA | 26809 | 4080 | ✅ | migré | — | — |  |
| Inter Invest | Inter Invest \| Focus PER | 26810 | 5173 | ✅ | migré | — | — |  |
| Superdiet | Perf by channel  SD | 26802 | 12928 | ✅ | migré | — | — |  |
| Superdiet | Leviers \| Superdiet | 26803 | 13125 | ✅ | migré | — | — |  |
| Superdiet | Google Analytics 4 - Global template  - Duplicate | 26804 | 18768 | ✅ | migré | — | — |  |
| Superdiet | Google Ads - Performance Max Template \| E-commerce | 26805 | 21375 | ✅ | migré | — | — |  |
| Superdiet | Google Ads - Performance Max Template \| E-commerce  \| NEW \| Superdiet  | 26806 | 23256 | ✅ | migré | — | — |  |
| Superdiet | Performances \| Overview \| ATC \| Superdiet | 26807 | 24312 | ✅ | migré | — | — |  |
| Virgil | Virgil - Pilotage | 26794 | 10585 | ✅ | migré | — | — |  |
| Virgil | Virgil - Home | 26795 | 11783 | ✅ | migré | — | — |  |
| Virgil | Virgil - Spoune | 26796 | 11951 | ✅ | migré | — | — |  |
| Virgil | Template SEO \| Overview - Pages - Keywords - Virgil | 26797 | 15175 | ✅ | migré | — | — |  |
| Virgil | Virgil - Search | 26798 | 19231 | ✅ | migré | — | — |  |
| Virgil | Reporting SEO \| Virgil | 26799 | 19560 | ✅ | migré | — | — |  |
| Virgil | Suivi des conversions \| Virgil | 26800 | 19626 | ✅ | migré | — | — |  |
| Virgil | Reporting SEO - ROI \| Virgil | 26801 | 19758 | ✅ | migré | — | — |  |
| Bambinos | Bambinos \| Homepage | 26867 | 25038 | ✅ | migré | — | — |  |
| Belveo | Lead Generation Multi-Channel Performance Belveo | 26853 | 20849 | ✅ | migré | — | — |  |
| Belveo | Homepage Performance  - Belveo | 26854 | 20850 | ✅ | migré | — | — |  |
| Belveo | Performances all countries - Belveo | 26855 | 21276 | ✅ | migré | — | — |  |
| Belveo | Performances France - Belveo | 26856 | 21342 | ✅ | migré | — | — |  |
| Belveo | Performances Espagne - Belveo | 26857 | 21343 | ✅ | migré | — | — |  |
| Belveo | Performances UK - Belveo | 26858 | 21344 | ✅ | migré | — | — |  |
| Belveo | E-commerce Social Overview - Belveo | 26859 | 21345 | ✅ | migré | — | — |  |
| Belveo | SEA Global Overview (Google & Microsoft) - Belveo | 26860 | 21346 | ✅ | migré | — | — |  |
| Belveo | Performances Hubspot - Belveo | 26861 | 22497 | ✅ | migré | — | — |  |
| Funkie | Performances annonces | 26862 | 14876 | ✅ | migré | — | — |  |
| Funkie | E-commerce Multi-Channel Performance Funkie (with COS) | 26863 | 17449 | ✅ | migré | — | — |  |
| 24S | Audiences Performances \| 24S | 26969 | 2634 | ✅ | migré | — | — |  |
| 24S | Performances Créas \| 24S | 26970 | 5764 | ✅ | migré | — | — |  |
| 24S | Home \| 24S | 26971 | 6661 | ✅ | migré | — | — |  |
| 24S | Pilotage Global - Haut de funnel \| 24S | 26973 | 6953 | ✅ | migré | — | — |  |
| 24S | Pilotage Global - ROIste \| 24S | 26977 | 6954 | ✅ | migré | — | — |  |
| 24S | Pilotage Global - App \| 24S | 26978 | 7912 | ✅ | migré | — | — |  |
| 24S | Evolution WoW - YoY \| 24S | 26981 | 7978 | ✅ | migré | — | — |  |
| 24S | Performances COMM \| 24S | 26982 | 9928 | ✅ | migré | — | — |  |
| 24S | Performances Capsules \| 24S | 26983 | 11211 | ✅ | migré | — | — |  |
| 24S | Home Paid \| 24S 2 | 26985 | 11409 | ✅ | migré | — | — |  |
| 24S | Capsule - Social adsets, ads & products | 26987 | 11410 | ✅ | migré | — | — |  |
| 24S | App Installs Home (Adjust)  \| 24S | 26988 | 11862 | ✅ | migré | — | — |  |
| 24S | Organic Search Visit | 26991 | 13786 | ✅ | migré | — | — |  |
| 24S | Campagne de marque \| 24S | 26992 | 25963 | ✅ | migré | — | — |  |
| 900.care | 01. Global (V2) \| 900.care | 26951 | 673 | ✅ | migré | — | — |  |
| 900.care | 05. Ads_Analysis \| 900.Care | 26954 | 677 | ✅ | migré | — | — |  |
| 900.care | Audiences Performances \| 900.care | 26955 | 843 | ✅ | migré | — | — |  |
| 900.care | 02. Leviers \| 900.Care - VF | 26957 | 6560 | ✅ | migré | — | — |  |
| 900.care | 03. Campagnes \| 900.Care VF | 26958 | 6563 | ✅ | migré | — | — |  |
| 900.care | Meta \| 900.Care | 26961 | 7512 | ✅ | migré | — | — |  |
| 900.care | GA4 - Analytics Acquisition - 900 care | 26963 | 7710 | ✅ | migré | — | — |  |
| 900.care | 04. Performances par pays \| 900.care | 26965 | 11664 | ✅ | migré | — | — |  |
| 900.care | Meta  \| Internal ad analysis | 26967 | 11779 | ✅ | migré | — | — |  |
| 900.care | 09. GAds - Pmax template  | 26968 | 11863 | ✅ | migré | — | — |  |
| 900.care | 07. Trendsssssss | 26972 | 11950 | ✅ | migré | — | — |  |
| 900.care | DNVB benchmark \| 900.care | 26974 | 13719 | ✅ | migré | — | — |  |
| 900.care | My dashboard | 26975 | 16128 | ✅ | migré | — | — |  |
| 900.care | 08. Global (V2) \| 900.care - QBR | 26976 | 18009 | ✅ | migré | — | — |  |
| 900.care | 06. Produits \| 900.Care | 26979 | 18241 | ✅ | migré | — | — |  |
| BeneBono | Bene Bono \| Performances Globales | 26933 | 20550 | ✅ | migré | — | — |  |
| BeneBono | Bene Bono \| Performances par Levier & Campagne | 26938 | 20551 | ✅ | migré | — | — |  |
| BeneBono | Bene Bono \| Home & Goals | 26940 | 20553 | ✅ | migré | — | — |  |
| BeneBono | Bene Bono \| Social Performances | 26943 | 20554 | ✅ | migré | — | — |  |
| BeneBono | Bene Bono \| SEA Performances par campagne, adgroup & keyword | 26945 | 20555 | ✅ | migré | — | — |  |
| BeneBono | Bene Bono \| Focus Lead Gen Géo | 26949 | 20913 | ✅ | migré | — | — |  |
| Cirque du Soleil | Home \| ALEGRIA | 27076 | 6987 | ✅ | migré | — | — |  |
| Cirque du Soleil | [OLD]  Social Overview \| Cirque du Soleil | 27080 | 6990 | ✅ | migré | — | — |  |
| Cirque du Soleil | [OLD] Social Adsets and Ads  \| Cirque du Soleil | 27083 | 7152 | ✅ | migré | — | — |  |
| Cirque du Soleil | [OLD] Home \| Cirque du Soleil | 27084 | 7323 | ✅ | migré | — | — |  |
| Cirque du Soleil | [OLD]  Overview \| ALEGRIA | 27085 | 14248 | ✅ | migré | — | — |  |
| Cirque du Soleil | TikTok -  Global Perf \| CDS | 27089 | 19692 | ✅ | migré | — | — |  |
| Cirque du Soleil | Home \| OVO | 27090 | 21045 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Lead Generation Campaign Performance | 27036 | 17943 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Global | 27042 | 19923 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Global \| 2026 | 27044 | 20583 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Manual Export | 27046 | 20979 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Factu \| 2026 | 27048 | 21144 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Cold Leads \| 2026 | 27049 | 21145 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Focus Brand | 27051 | 21507 | ✅ | migré | — | — |  |
| Dougs | Dougs \| Evolutions Macro | 27053 | 22464 | ✅ | migré | — | — |  |
| En Voiture Simone (EVS) | Overview EVS | 27079 | 5301 | ✅ | migré | — | — |  |
| En Voiture Simone (EVS) | Ads & Audiences Analysis \| EVS | 27081 | 7479 | ✅ | migré | — | — |  |
| En Voiture Simone (EVS) | EVS \| Focus Notoriété | 27082 | 11785 | ✅ | migré | — | — |  |
| En Voiture Simone (EVS) | NEW DASH EVS | 27086 | 11855 | ✅ | migré | — | — |  |
| En Voiture Simone (EVS) | Conversions Comparison \| EVS | 27087 | 16855 | ✅ | migré | — | — |  |
| En Voiture Simone (EVS) | Global \| EVS | 27088 | 19694 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Demo - Home | 27055 | 24083 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Demo - Campagnes | 27057 | 24084 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Demo - Performances Globales | 27060 | 24085 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Achat - Performances par campagne | 27064 | 24103 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Achat - Performance Globale | 27066 | 24104 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Perf par Pays | 27070 | 24105 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Achat - Home | 27072 | 24477 | ✅ | migré | — | — |  |
| Enlaps | Enlaps - Home Global - Démos x Achats | 27073 | 24478 | ✅ | migré | — | — |  |
| Father and Sons | Ecomm \| Pilotage | 26916 | 11804 | ✅ | migré | — | — |  |
| Father and Sons | Annonces Meta \| Father & Sons | 26920 | 12861 | ✅ | migré | — | — |  |
| Father and Sons | Ecomm \| Home | 26921 | 13323 | ✅ | migré | — | — |  |
| Father and Sons | Sponso \| Home | 26923 | 13556 | ✅ | migré | — | — |  |
| Father and Sons | Noto \| Home | 26926 | 15963 | ✅ | migré | — | — |  |
| Father and Sons | Shopify | 26929 | 22860 | ✅ | migré | — | — |  |
| Gestion immobilière Walter inc. | Walter - Lead Generation - Campaign Performance  | 26904 | 20517 | ✅ | migré | — | — |  |
| Gestion immobilière Walter inc. | Walter FR \| Homepage | 26908 | 21706 | ✅ | migré | — | — |  |
| Gestion immobilière Walter inc. | Walter FR \| Per City | 26909 | 24741 | ✅ | migré | — | — |  |
| Gestion immobilière Walter inc. | Walter FR \| Focus par ville | 26911 | 24807 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | Multi-Country Performance  | 26993 | 20055 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | SEA Global Overview | 26995 | 20089 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | E-commerce Mono Channel Performance Template - Meta | 26997 | 20091 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | JD - Breakdowns | 26999 | 21738 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | Overview \| Jerôme Dreyfuss | 27001 | 22398 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | Focus Noto - JD | 27004 | 22729 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | E-commerce Multi-Channel Performance Template - JD | 27005 | 25500 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | Google Ads - Performance Max Template \| JD | 27008 | 25665 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | Shopify  - Overview template - JD | 27010 | 25698 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | E-commerce Campaign Performance Template - JD | 27012 | 25731 | ✅ | migré | — | — |  |
| Jerome Dreyfuss | E-commerce Mono Channel Performance Template - TikTok | 27014 | 25995 | ✅ | migré | — | — |  |
| LA Bruket | Peformances Facebook \| L:A Bruket | 27067 | 3519 | ✅ | migré | — | — |  |
| LA Bruket | Ads & Audiences Analysis \| LAB | 27068 | 9528 | ✅ | migré | — | — |  |
| LA Bruket | Shopify  - LA Bruket - old | 27069 | 11688 | ✅ | migré | — | — |  |
| LA Bruket | NEW Performances Globales \| L:A Bruket | 27071 | 15073 | ✅ | migré | — | — |  |
| LA Bruket | Performances filtrées par pays \| L:A Bruket | 27074 | 15075 | ✅ | migré | — | — |  |
| LA Bruket | NEW Performances filtrées par pays \| L:A Bruket | 27075 | 15205 | ✅ | migré | — | — |  |
| LA Bruket | Shopify Overview \| LA Bruket | 27077 | 15699 | ✅ | migré | — | — |  |
| LA Bruket | Test - Adset performance - LAB | 27078 | 21441 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Perfs globales (shared) | 27013 | 7248 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Perfs par levier (shared) | 27015 | 7249 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Perfs par campagne (shared) | 27016 | 7250 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Home (shared) | 27018 | 9339 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Perfs par produits Google  (shared) | 27020 | 10387 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Perf par annonces | 27021 | 10919 | ✅ | migré | — | — |  |
| Les petits culottés | Google Analytics \| LPC | 27022 | 10980 | ✅ | migré | — | — |  |
| Les petits culottés | GAds - Pmax \| LPC (shared) | 27023 | 11686 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Perfs par produits Meta (shared) | 27027 | 13521 | ✅ | migré | — | — |  |
| Les petits culottés | LPC \| Perfs par produits | 27028 | 13554 | ✅ | migré | — | — |  |
| LocaBoat Group | Locaboat - Home | 26886 | 11784 | ✅ | migré | — | — |  |
| LocaBoat Group | Leadgen - global perf template (monochannel) - Locaboat group | 26889 | 12828 | ✅ | migré | — | — |  |
| LocaBoat Group | Locaboat - Home - Bas de funnel | 26890 | 13455 | ✅ | migré | — | — |  |
| LocaBoat Group | Report Locaboat Spec | 26892 | 14941 | ✅ | migré | — | — |  |
| LocaBoat Group | Media performance vs météo \| Locaboat | 26893 | 17448 | ✅ | migré | — | — |  |
| LocaBoat Group | Riverly - Home | 26896 | 19792 | ✅ | migré | — | — |  |
| LocaBoat Group | Détail Performance Max | 26902 | 21012 | ✅ | migré | — | — |  |
| Lunii | [OLD] Performances France \| Lunii | 26888 | 2774 | ✅ | migré | — | — |  |
| Lunii | [OLD] Ads Analysis | 26894 | 2775 | ✅ | migré | — | — |  |
| Lunii | Youtube Analysis Lunii | 26895 | 4973 | ✅ | migré | — | — |  |
| Lunii | [OLD] Perfs Meta \| Lunii | 26898 | 6896 | ✅ | migré | — | — |  |
| Lunii | Détail Performance Max \| Network | 26901 | 7151 | ✅ | migré | — | — |  |
| Lunii | [OLD] Perfs Plateforme \| Lunii | 26903 | 7745 | ✅ | migré | — | — |  |
| Lunii | Lunii \| Devices | 26906 | 8274 | ✅ | migré | — | — |  |
| Lunii | [OLD] Ads & Audiences Analysis \| Lunii | 26913 | 9298 | ✅ | migré | — | — |  |
| Lunii | [OLD] Perfs par produit \| Lunii | 26914 | 11750 | ✅ | migré | — | — |  |
| Lunii | Perfs Lunii+ | 26918 | 17019 | ✅ | migré | — | — |  |
| Lunii | Lunii \| MPL | 26925 | 17317 | ✅ | migré | — | — |  |
| Lunii | FAH - Devices - NC \| Lunii | 26928 | 18933 | ✅ | migré | — | — |  |
| Lunii | Purchases & trafic \| Lunii | 26931 | 18934 | ✅ | migré | — | — |  |
| Lunii | Levier & Perf campagnes + search lift \| Lunii | 26934 | 18935 | ✅ | migré | — | — |  |
| Lunii | Lunii Global | 26936 | 20451 | ✅ | migré | — | — |  |
| Lunii | Lunii \| Devices \| VFinale | 26939 | 20848 | ✅ | migré | — | — |  |
| Lunii | Lunii+ \| Performances | 26947 | 20851 | ✅ | migré | — | — |  |
| Perifit | Perifit  - Global | 27030 | 11691 | ✅ | migré | — | — |  |
| Perifit | Perifit  - Meta | 27033 | 11692 | ✅ | migré | — | — |  |
| Perifit | Perifit  - Sandbox | 27037 | 11693 | ✅ | migré | — | — |  |
| Perifit | Perifit - Benchmarks | 27038 | 11694 | ✅ | migré | — | — |  |
| Perifit | Perifit  - Global - New | 27039 | 11704 | ✅ | migré | — | — |  |
| Perifit | Perifit  - Country | 27040 | 11705 | ✅ | migré | — | — |  |
| Perifit | Perifit  - Google | 27041 | 11706 | ✅ | migré | — | — |  |
| Perifit | Perifit  - Global - Nanga | 27043 | 12008 | ✅ | migré | — | — |  |
| Perifit | Perifit \| Google \| Home | 27045 | 14214 | ✅ | migré | — | — |  |
| Perifit | Global \| Perifit | 27047 | 18636 | ✅ | migré | — | — |  |
| Quitoque | Acquisition \| Quitoque | 26887 | 571 | ✅ | migré | — | — |  |
| Quitoque | Lead Gen - Version \| Quitoque | 26891 | 580 | ✅ | migré | — | — |  |
| Quitoque | Auction Insights \| Quitoque | 26897 | 768 | ✅ | migré | — | — |  |
| Quitoque | Fidélisation \| Quitoque | 26899 | 1039 | ✅ | migré | — | — |  |
| Quitoque | Strategic Review \| Quitoque | 26900 | 2467 | ✅ | migré | — | — |  |
| Quitoque | Home [S2 2022] \| Quitoque | 26905 | 2598 | ✅ | migré | — | — |  |
| Quitoque | Focus \| Quitoque | 26907 | 2723 | ✅ | migré | — | — |  |
| Quitoque | Quitoque \| SEA \| Overview | 26910 | 3256 | ✅ | migré | — | — |  |
| Quitoque | Performances by device \| Quitoque | 26912 | 3357 | ✅ | migré | — | — |  |
| Quitoque | Video ads \| Quitoque | 26915 | 3430 | ✅ | migré | — | — |  |
| Quitoque | Quitoque \| All Ad & Ad Set Performances | 26917 | 3820 | ✅ | migré | — | — |  |
| Quitoque | QTQ \| Client VS Industry VS Global | 26919 | 4082 | ✅ | migré | — | — |  |
| Quitoque | Quitoque \| SEA \| Focus | 26922 | 4344 | ✅ | migré | — | — |  |
| Quitoque | Home Macro \| Quitoque | 26924 | 5631 | ✅ | migré | — | — |  |
| Quitoque | Focus Données Leviers \| Quitoque | 26927 | 6897 | ✅ | migré | — | — |  |
| Quitoque | Focus Evolution \| Quitoque | 26930 | 6898 | ✅ | migré | — | — |  |
| Quitoque | Home par phase \| Quitoque (shared) | 26932 | 11873 | ✅ | migré | — | — |  |
| Quitoque | Voucher Exploration \| Quitoque | 26935 | 15736 | ✅ | migré | — | — |  |
| Quiz Room | SEO Overview \| Quiz Room | 27017 | 11680 | ✅ | migré | — | — |  |
| Quiz Room | Global Paid \| Quiz Room | 27019 | 11682 | ✅ | migré | — | — |  |
| Quiz Room | Quiz Room - Benchmark | 27024 | 11683 | ✅ | migré | — | — |  |
| Quiz Room | Quiz Room - Franchises - Paid | 27025 | 11685 | ✅ | migré | — | — |  |
| Quiz Room | SEO Overview \| Quiz Room | 27026 | 14577 | ✅ | migré | — | — |  |
| Quiz Room | Google Analytics 4 - Global per account | 27029 | 16986 | ✅ | migré | — | — |  |
| Quiz Room | Reporting SEO \| Quiz Room | 27031 | 17481 | ✅ | migré | — | — |  |
| Quiz Room | Franchisés \| Quiz Room (FR) | 27032 | 24576 | ✅ | migré | — | — |  |
| Quiz Room | Acquisition multi-domaines \| Quiz Room | 27034 | 24642 | ✅ | migré | — | — |  |
| Quiz Room | Franchises \| Quiz Room (EN) | 27035 | 25467 | ✅ | migré | — | — |  |
| Rivadouce | Ecommerce - global perf template (multichannel) | 26937 | 15240 | ✅ | migré | — | — |  |
| Rivadouce | Nouveaux Clients | 26941 | 15303 | ✅ | migré | — | — |  |
| Rivadouce | Home \| Rivadouce | 26942 | 15370 | ✅ | migré | — | — |  |
| Rivadouce | Traffic | 26944 | 15371 | ✅ | migré | — | — |  |
| Rivadouce | GA4 Overview | 26946 | 15372 | ✅ | migré | — | — |  |
| Rivadouce | Focus ROIste | 26948 | 15374 | ✅ | migré | — | — |  |
| Rivadouce | Performances Globales | 26950 | 15375 | ✅ | migré | — | — |  |
| Rivadouce | Home Rivadouce Custom | 26952 | 15732 | ✅ | migré | — | — |  |
| Rivadouce | Rivadouce \| Perfs par campagne | 26953 | 16434 | ✅ | migré | — | — |  |
| Rivadouce | Rivadouce \| Perfs globales | 26956 | 16458 | ✅ | migré | — | — |  |
| Rivadouce | Perfs par levier  \| Rivadouce | 26959 | 16459 | ✅ | migré | — | — |  |
| Rivadouce | Rivadouce \| Perf par annonces | 26960 | 16491 | ✅ | migré | — | — |  |
| Rivadouce | Perf par campagne \| Rivadouce | 26962 | 17780 | ✅ | migré | — | — |  |
| Rivadouce | Ads & Audiences Analysis \| Rivadouce | 26964 | 19263 | ✅ | migré | — | — |  |
| Rivadouce | Rivadis \| Home (Gaby) | 26966 | 20253 | ✅ | migré | — | — |  |
| Shopinvest | Global \| Shopinvest | 27050 | 23 | ✅ | migré | — | — |  |
| Shopinvest | Home \| Shopinvest | 27052 | 186 | ✅ | migré | — | — |  |
| Shopinvest | Facebook - Main \| Shopinvest | 27054 | 421 | ✅ | migré | — | — |  |
| Shopinvest | Global V2 - Main \| Shopinvest | 27056 | 422 | ✅ | migré | — | — |  |
| Shopinvest | Analytics \| Shopinvest - Main | 27058 | 863 | ✅ | migré | — | — |  |
| Shopinvest | Verticales \| Shopinvest | 27059 | 918 | ✅ | migré | — | — |  |
| Shopinvest | Global V2 - Focus levier, network, campaign type \| Shopinvest | 27061 | 6855 | ✅ | migré | — | — |  |
| Shopinvest | MOAS \| Shopinvest | 27062 | 8703 | ✅ | migré | — | — |  |
| Shopinvest | Focus Marge \| Shopinvest | 27063 | 8803 | ✅ | migré | — | — |  |
| Shopinvest | GAds - Shopping & PMax product focus Maroquinerie | 27065 | 11840 | ✅ | migré | — | — |  |
| Tradis | Global \| Tradis | 27091 | 21937 | ✅ | migré | — | — |  |
| U2P | Google - Créer reprendre | 27092 | 11650 | ✅ | migré | — | — |  |
| U2P | Google - Vision Globale | 27093 | 11777 | ✅ | migré | — | — |  |
| U2P | Meta - Performances Globales | 27094 | 12118 | ✅ | migré | — | — |  |
| U2P | Google - Youtube | 27095 | 12120 | ✅ | migré | — | — |  |
| U2P | Google Analytics 4 - Home | 27096 | 21672 | ✅ | migré | — | — |  |
| U2P | Google Analytics 4 - Home - Duplicate | 27097 | 26028 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Performances Globales | 26980 | 13588 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Performances par Levier & Campagne | 26984 | 13589 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| SEA Performances par campagne, adgroup & keyword | 26986 | 13820 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Performances par tailles de leads | 26989 | 14711 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Home B2C FR | 26990 | 15237 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Home UK | 26994 | 15238 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Home US | 26996 | 16001 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Overview | 26998 | 16326 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| SEA Performances  UK | 27000 | 20319 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Social Performances UK | 27002 | 20320 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Home UK B2C | 27003 | 20914 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| SEA Performances  UK B2C | 27006 | 20946 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Social Performances UK B2C | 27007 | 20947 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Performances Globales UK B2B | 27009 | 21408 | ✅ | migré | — | — |  |
| Welcome to the Jungle | WTTJ \| Performances par Levier & Campagne UK B2B | 27011 | 21540 | ✅ | migré | — | — |  |
