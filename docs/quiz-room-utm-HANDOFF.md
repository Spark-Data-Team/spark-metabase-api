# Quiz Room — UTM Tracker : ce qui est corrigé & ce qui reste côté com

**Pour : Robin** — à relayer à l'équipe com (qui maintient le gsheet des liens) et au client.
**Date :** 2026-06-20 · **Dashboard :** Acquisition multi-domaines Quiz Room → onglet *UTM Tracker*.

---

## 1. Résolu côté tech ✅

Le bug « campagnes à 0 / absentes » (métro, Quotidien Matin, Voxe…) est **corrigé et en production**.

| | Avant | Après |
|---|--:|--:|
| Sessions (sur la période) | 1 090 | **6 693** (×6) |
| Réservations | 22 | **78** |

Campagnes récupérées : **Quotidien Matin 2 555**, Story Quotidien 1 545, Leboncoin Lyon 809, **Métro 550**, Voxe 455, L'Équipe 32.

**Cause du bug (pour info) :** le tracker comparait les colonnes UTM *tapées à la main* dans le gsheet aux données GA4. Quand ces colonnes étaient vides, fausses, ou contenaient des accents, le rapprochement ratait silencieusement. **Désormais le tracker lit directement l'URL complète du lien** (= ce que GA4 voit réellement).

> 🔑 **Règle d'or pour la com maintenant :** ce qui compte, c'est que la colonne **`url_complete`** du gsheet contienne **exactement le lien réellement diffusé** (avec tous ses `utm_…`). C'est cette URL qui sert au rapprochement — les colonnes source/medium/campaign séparées ne sont plus la source de vérité. Si l'URL est bonne, ça matchera.

---

## 2. Ce qui reste — actions côté com 🟡

### A) Liens à compléter / ajouter dans le gsheet

Lignes présentes mais **sans URL exploitable** → ajouter l'URL trackée réelle si on veut les suivre :

| Campagne | Type | État actuel |
|---|---|---|
| BRUXELLES SECRETE I ARTICLE | Média Web | URL vide |
| L'ESSENTIEL I NEWSLETTER | Newsletter | URL vide |
| Vivre Bordeaux | Influence | URL vide |
| Voxe - NL hors-série | Newsletter | `même lien qu'en dessous` (placeholder à remplacer) |

Campagnes **vues par GA4 mais absentes du gsheet** → à ajouter :

| Campagne (vue dans GA4) | Sessions | Action |
|---|--:|---|
| `metro / OOH / activite qui fait le buzz` | 123 | ajouter la ligne (variante métro non cataloguée) |
| _(liste exhaustive : voir requête en annexe)_ | — | à compléter |

### B) Liens du gsheet qui ne ramènent rien (0 session) → à vérifier

Ces liens existent dans le gsheet mais GA4 n'a **aucune visite sous leurs UTM exacts**. Deux cas :

**B1 — Le trafic existe, mais sous un libellé différent** → corriger le gsheet pour coller au lien réellement diffusé :

| Campagne | UTM dans le gsheet | Réalité GA4 |
|---|---|---|
| Article Le Bonbon | `…campaign=meilleure_activité_fin_annee` | GA4 a `…meilleure_activité_en_famille` (source `articlelille`) — **libellé différent** |
| Voxe | `…medium=newsletter2` | typo probable (vs `newsletter`) |
| Petit Fûté | lien tagué `petitfûté / ficheSEO / 2026` | son trafic réel arrive en **referral** (non tagué) |

**B2 — Probablement jamais cliqués** (à confirmer ; sinon rien à faire) :
Leboncoin Lyon `nativeadweb` (les 2 autres placements ont bien matché), Sortir à Paris ×3 articles (`sapvillette`, `sapodeon`, `sapbn`), Lyon City Crunch, Culture Quizz.

---

## 3. Non-trackable par nature — à expliquer au client (pas un bug) ℹ️

Le tracker UTM ne montre **que** les liens taggés UTM pointant vers le site Quiz Room. Ne pourront **jamais** y apparaître :

- **Réseaux sociaux** (Lea Influ, Paris Immersif, Sortir à Paris stories…) : pas de lien UTM possible.
- **Articles sur sites tiers** (Quoi faire à Bordeaux…) : c'est du **referral** → visible dans le canal « referral » de GA4, pas dans le tracker UTM.
- ⚠️ **Important pour Le Bonbon / Petit Fûté :** l'essentiel de leur trafic vers Quiz Room est du **referral non taggé** (des milliers de sessions), pas des liens UTM. Ils paraîtront donc *petits* dans le tracker même s'ils performent bien. Pour les suivre réellement : soit regarder le canal referral de GA4, soit taguer systématiquement leurs liens en UTM.

---

## Annexe — requête de réconciliation (à lancer côté Snowflake, accès FIVETRAN)

Liste exhaustive du trafic UTM vu par GA4 **mais absent du gsheet** (= liens à ajouter / réconcilier) :

```sql
WITH ga4 AS (
  SELECT LOWER(session_manual_source) src, LOWER(session_manual_medium) med,
         LOWER(session_campaign_name)  camp, SUM(sessions) sessions
  FROM FIVETRAN_DB.google_analytics_4_20260205_quizzroom.daily_report_per_url_utm
  WHERE event_name = 'session_start'
    AND session_campaign_name IS NOT NULL
    AND session_campaign_name NOT IN ('(not set)', '')
    AND LOWER(session_manual_medium) NOT IN
        ('referral','organic','(none)','(not set)','','cpc','ppc','paid','display','paidsearch','paid_search')
  GROUP BY 1, 2, 3
),
cat AS (
  SELECT DISTINCT LOWER(utm_source) src, LOWER(utm_medium) med, LOWER(utm_campaign) camp
  FROM REPORTING_DB.client_data.stg_quiz_room_utms
)
SELECT g.src AS utm_source, g.med AS utm_medium, g.camp AS utm_campaign, g.sessions
FROM ga4 g
LEFT JOIN cat c ON g.src = c.src AND g.med = c.med AND g.camp = c.camp
WHERE c.src IS NULL
ORDER BY g.sessions DESC;
```
