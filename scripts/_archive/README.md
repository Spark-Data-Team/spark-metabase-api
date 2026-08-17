# Campagnes closes

41 scripts de campagnes terminées, conservés pour la trace et pour les
artefacts qu'ils ont produits.

**Ne pas s'en inspirer.** Ils datent d'avant le noyau et portent les vieux
idiomes : leur propre `def connect()`, des `sys.path.insert`, des `mb.put(...)`
dont la valeur de retour ment. Pour écrire un nouveau script, partir de
`CLAUDE.md` à la racine.

Vérifié avant déplacement : aucun script actif ni aucun test n'en importe un.

Leurs imports mutuels fonctionnent toujours (dossier plat), mais **ils ne sont
plus exécutables tels quels** : chacun calcule la racine du dépôt par
`Path(__file__).resolve().parent.parent`, qui pointe désormais sur `scripts/`.
Concrètement ils chercheraient `scripts/.env` et écriraient dans
`scripts/migration/`. Pour en relancer un, il faut passer à `parent.parent.parent`.

Rien du travail courant n'en dépend.

Campagnes concernées : SEO manucurist, Quiz Room, correction brand, anti-patterns
SQL, réorganisation de la collection 215, HubSpot Comptastar 28899.
