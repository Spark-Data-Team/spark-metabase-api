export const meta = {
  name: 'sql-antipattern-audit',
  description: 'Classify Metabase native cards for 2 SQL anti-patterns (kp JOIN missing language/zone; eaten regex escape), then adversarially verify every BUG',
  phases: [
    { title: 'Analyze', detail: 'one auditor per candidate card reads its SQL and renders a verdict' },
    { title: 'Verify', detail: 'diverse-lens skeptics try to refute each BUG' },
  ],
}

// Task list injected by build_antipattern_workflow.py (metadata only, no SQL —
// each agent reads its own .sql file from disk).
const TASKS = __TASKS_JSON__;

const ANALYSIS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['card_id', 'antipattern', 'verdict', 'confidence', 'evidence',
             'reasoning', 'fix_find', 'fix_replace', 'review_question', 'inflation_note'],
  properties: {
    card_id: { type: 'integer' },
    antipattern: { type: 'string', enum: ['A', 'B'] },
    verdict: { type: 'string', enum: ['BUG', 'OK', 'REVIEW'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    evidence: { type: 'string', description: 'Exact SQL extract that is the crux (the JOIN..ON for A, the REGEXP pattern literal for B)' },
    reasoning: { type: 'string', description: 'Why this verdict, citing the SQL' },
    fix_find: { type: 'string', description: 'Exact substring to find for a copy-paste fix; empty string if not BUG' },
    fix_replace: { type: 'string', description: 'Exact replacement substring; empty string if not BUG' },
    review_question: { type: 'string', description: 'For REVIEW: the precise question a human must resolve; else empty' },
    inflation_note: { type: 'string', description: 'For A BUG: which displayed metric inflates and rough factor; else empty' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['refuted', 'corrected_verdict', 'reason'],
  properties: {
    refuted: { type: 'boolean', description: 'true if the BUG claim is WRONG / does not hold' },
    corrected_verdict: { type: 'string', enum: ['BUG', 'OK', 'REVIEW'] },
    reason: { type: 'string', description: 'Concise justification citing the SQL' },
  },
}

const TEMPLATING_NOTE =
  'The SQL is Snowflake dialect and contains Metabase templating: {{client}}, {{date}}, ' +
  '{{corpus_name}}, and optional [[ ... ]] blocks. Treat every template tag as an opaque ' +
  'filter; NEVER try to execute the SQL. Base your verdict only on the static structure.'

function analyzePromptA(t) {
  return [
    'You are a meticulous SQL auditor. Analyze EXACTLY ONE Metabase card for SQL anti-pattern A.',
    '',
    'Read the file (it starts with comment metadata, then the full native SQL): ' + t.path,
    TEMPLATING_NOTE,
    '',
    'ANTI-PATTERN A — cartesian JOIN on keyword-planner tables.',
    'The tables google_keyword_planner.kp__keyword_monthly_metrics and kp__keyword_aggregated_metrics',
    'store the SAME keyword under MULTIPLE (language, zone) pairs (one client can have corpora for',
    'France, Germany, Netherlands, UK...). Joining such a table ON the keyword column ALONE — without',
    'also matching the kp table language AND zone columns — produces a cartesian fan-out: each source',
    'row matches N kp rows, so SUM/aggregates of volume/traffic/cost inflate (x2-3) for multi-zone clients.',
    '',
    'VERDICT RUBRIC (judge the CURRENT SQL in the file):',
    '- BUG: a JOIN to a kp__ table whose ON clause matches the keyword column but matches NEITHER the kp',
    '       language NOR the kp zone column, and nothing upstream guarantees a single (language,zone) per keyword.',
    '- OK:  every kp__ JOIN matches keyword AND language AND zone (a month/date equality may also appear).',
    '       Calibration: card 15946 currently matches keyword+language+zone -> OK. Its historical BUG form',
    '       matched the keyword only.',
    '- REVIEW: genuinely ambiguous — the kp table is reached via subquery/implicit join; OR the rows feeding',
    '       the join are already reduced to one (language,zone) per keyword upstream (QUALIFY ROW_NUMBER,',
    '       GROUP BY, DISTINCT); OR an upstream filter on airtable_record_id scopes to a single corpus',
    '       (known heuristic: such a filter usually removes the cartesian risk -> lean OK, but use REVIEW',
    '       with a clear note if you are not certain). Quote the exact extract and pose the precise question.',
    '',
    'Track table aliases carefully (the kp table is usually aliased, e.g. AS kp; the source another alias).',
    'If BUG: set fix_find to the EXACT current ON-clause text copied verbatim from the file, and fix_replace',
    'to that same text with two equalities ADDED matching the kp language/zone to the source language/zone',
    '(use the real aliases you see). evidence = the exact "JOIN ... ON ..." extract. inflation_note = which',
    'displayed metric inflates (the SUM/aggregate) and a rough factor if inferable.',
    'Set card_id=' + t.card_id + ', antipattern="A".',
  ].join('\n')
}

function analyzePromptB(t) {
  return [
    'You are a meticulous SQL auditor. Analyze EXACTLY ONE Metabase card for SQL anti-pattern B.',
    '',
    'Read the file (comment metadata, then the full native SQL): ' + t.path,
    TEMPLATING_NOTE,
    '',
    'ANTI-PATTERN B — eaten regex escape in Snowflake.',
    'In Snowflake REGEXP_* / RLIKE the pattern is a SQL string literal. A SINGLE backslash before a regex',
    'metacharacter (dot, question-mark, plus, parentheses, brackets, braces, pipe, caret, dollar, star) is',
    'NOT honored as the author expects: the backslash is consumed and the metacharacter KEEPS its special',
    'meaning. The classic case: a backslash before a dot, intended to match a LITERAL dot, instead matches',
    'ANY single character. Confirmed impact: a Share-of-Voice query used backslash-dot to anchor a domain',
    'suffix and instead mis-stripped a character (e.g. domain handling for manucurist.com went wrong ->',
    'Share of Voice 118%). The correct robust form is a CHARACTER CLASS: wrap the metachar in [ ] (a literal',
    'dot becomes the two-character class open-bracket dot close-bracket).',
    '',
    'VERDICT RUBRIC (judge the CURRENT SQL):',
    '- BUG: a REGEXP pattern contains a single-backslash-escaped metacharacter CLEARLY meant as a LITERAL',
    '       (matching/stripping a real dot, parenthesis, etc. in a domain, URL, or number), so the eaten',
    '       escape changes matching and thus the card output.',
    '- OK:  the metachar is already inside a character class, OR its special meaning is actually intended,',
    '       OR the difference cannot affect this card result.',
    '- REVIEW: intent genuinely ambiguous — quote the pattern and pose the question.',
    '',
    'For each REGEXP call, extract the pattern string literal and reason about author intent. If BUG: fix_find',
    '= the exact pattern literal as written in the file; fix_replace = the corrected pattern (wrap each wrongly',
    'escaped metachar in a character class). evidence = the exact REGEXP_... call. Set card_id=' + t.card_id + ', antipattern="B".',
  ].join('\n')
}

const LENSES_A = [
  { key: 'aliases', title: 'alias & ON-clause re-read',
    body: 'Re-read the kp__ JOIN and ALL alias definitions. Verify the ON clause TRULY omits BOTH the kp ' +
          'language and the kp zone columns. Perhaps language/zone ARE matched under different aliases, via ' +
          'USING, or via an equivalent WHERE/QUALIFY predicate; or the prior auditor misread a non-kp join. ' +
          'If matching on language/zone is in fact present, refute.' },
  { key: 'upstream', title: 'upstream dedup / scoping',
    body: 'Determine the row grain feeding the kp JOIN. If an upstream CTE already reduces to exactly one ' +
          '(language,zone) per keyword (QUALIFY ROW_NUMBER, GROUP BY, DISTINCT), or the query is scoped to a ' +
          'single corpus via airtable_record_id, the cartesian fan-out does not occur on real data -> verdict ' +
          'should be OK/REVIEW. Refute if such a guard exists.' },
  { key: 'impact', title: 'does it actually inflate output',
    body: 'Check how the kp columns are consumed. If they are aggregated immune to row duplication (MAX of a ' +
          'per-keyword-constant column; or joined rows are de-duplicated by a later QUALIFY/DISTINCT/GROUP BY ' +
          'before any SUM/COUNT/AVG), the displayed metric is NOT inflated -> refute. Keep the bug only if a ' +
          'SUM/COUNT/AVG over the fanned-out rows is actually displayed.' },
]

const LENSES_B = [
  { key: 'intent', title: 'literal-intent check',
    body: 'Is the escaped metacharacter truly meant as a literal? If it is already inside a character class, ' +
          'or its regex special meaning is what the author wants, refute.' },
  { key: 'behavior', title: 'behavioral impact',
    body: 'Confirm Snowflake actually mis-handles this escape in a string-literal REGEXP pattern here AND that ' +
          'it changes the card output (not a harmless cosmetic match). If there is no observable output ' +
          'difference, refute.' },
]

function verifyPrompt(t, analysis, lens) {
  return [
    'You are an adversarial verifier. A prior auditor classified card #' + t.card_id + ' as a BUG for SQL',
    'anti-pattern ' + t.antipattern + '. Try HARD to REFUTE the claim through ONE specific lens. Conclude',
    'refuted=false only if the bug clearly survives your scrutiny.',
    '',
    'Read the SQL file: ' + t.path,
    TEMPLATING_NOTE,
    '',
    'Prior auditor evidence: ' + (analysis.evidence || '(none)'),
    'Prior auditor reasoning: ' + (analysis.reasoning || '(none)'),
    'Proposed fix find: ' + (analysis.fix_find || '(none)'),
    '',
    'LENS — ' + lens.title + ':',
    lens.body,
    '',
    'Decide: is the BUG claim wrong (refuted=true) or does it hold (refuted=false)? Give corrected_verdict',
    '(BUG if it holds; OK or REVIEW if you refute) and a concise reason citing the SQL.',
  ].join('\n')
}

log('Auditing ' + TASKS.length + ' candidate cards (' +
    TASKS.filter(t => t.antipattern === 'A').length + ' for A, ' +
    TASKS.filter(t => t.antipattern === 'B').length + ' for B)')

const results = await pipeline(
  TASKS,
  // STAGE 1 — analyze
  (t) => agent(t.antipattern === 'A' ? analyzePromptA(t) : analyzePromptB(t),
               { label: 'analyze:' + t.task_id, phase: 'Analyze', schema: ANALYSIS_SCHEMA }),
  // STAGE 2 — verify BUGs only (per item, no barrier)
  async (analysis, t) => {
    if (!analysis) {
      return { ...t, analysis: null, verifications: [], final_verdict: 'ERROR', confirmed: null }
    }
    if (analysis.verdict !== 'BUG') {
      return { ...t, analysis, verifications: [], final_verdict: analysis.verdict, confirmed: false }
    }
    const lenses = t.antipattern === 'A' ? LENSES_A : LENSES_B
    const votes = (await parallel(lenses.map(L => () =>
      agent(verifyPrompt(t, analysis, L),
            { label: 'verify:' + t.task_id + ':' + L.key, phase: 'Verify', schema: VERDICT_SCHEMA })
        .then(v => v ? { lens: L.key, ...v } : null)
    ))).filter(Boolean)
    const refutes = votes.filter(v => v.refuted).length
    const need = Math.ceil(votes.length / 2)        // majority must NOT refute
    const confirmed = votes.length > 0 && refutes < need
    const final_verdict = confirmed ? 'BUG' : 'REVIEW'  // downgrade refuted bugs to human REVIEW
    return { ...t, analysis, verifications: votes, refutes, votes_total: votes.length,
             final_verdict, confirmed }
  }
)

const clean = results.filter(Boolean)
const tally = (verd) => clean.filter(r => r.final_verdict === verd).length
log('Done. BUG=' + tally('BUG') + ' OK=' + tally('OK') + ' REVIEW=' + tally('REVIEW') + ' ERROR=' + tally('ERROR'))

return {
  summary: {
    analyzed: clean.length,
    bug: tally('BUG'), ok: tally('OK'), review: tally('REVIEW'), error: tally('ERROR'),
    a: clean.filter(r => r.antipattern === 'A').length,
    b: clean.filter(r => r.antipattern === 'B').length,
  },
  results: clean,
}
