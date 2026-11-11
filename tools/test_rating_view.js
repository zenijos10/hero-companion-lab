// Battery for the M5 rating view (app.js renderRatingHtml).
//   node tools/test_rating_view.js [alternative app.js]
//
// Lifts the real function out of app.js (brace matching) and drives it with
// /build/compare-shaped fixtures. Checks escaping (labels are user-typed save
// names), the refused-column reason, the comparison-only Gap column, the
// best-cell marker, the low-sample marker and the notes.
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = path.resolve(__dirname, "..");
const src = fs.readFileSync(process.argv[2] || path.join(root, "static/app.js"), "utf8");

function lift(name) {
  const start = src.indexOf(name);
  assert.ok(start > 0, `${name} not found in app.js`);
  const open = src.indexOf("{", start);
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(start, j + 1);
  }
  throw new Error(`could not brace-match ${name}`);
}
const unitsSrc = src.slice(src.indexOf("const _RATING_UNITS"), src.indexOf("};", src.indexOf("const _RATING_UNITS")) + 2);
// escHtml spans several chained .replace lines and its strings contain ";"
// ("&amp;"), so it ends at the first ";" that closes a LINE.
const escStart = src.indexOf("const escHtml");
const escEnd = src.slice(escStart).search(/;\r?\n/);
const escSrc = src.slice(escStart, escStart + escEnd + 1);
assert.ok(unitsSrc.length > 20 && escSrc.length > 20, "helpers not found");
const make = new Function(`${escSrc}\n${unitsSrc}\n${lift("function renderRatingHtml")}\nreturn renderRatingHtml;`);
const render = make();

const col = (label, extra = {}) => Object.assign({
  label, ok: true, primary: "Brute_Melee.Super_Strength", secondary: "Brute_Defense.Invulnerability",
  rated: true, offense_complete: true, unsupported: [], scenario: "rating_plus4" }, extra);
const row = (cells, extra = {}) => Object.assign({
  category: "defense", label: "Defense", unit: "percent", cells, best: null,
  meaningful: false, difference: null }, extra);
let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };

// 1. scorecard: why text shown inline, no Gap column, grade class
let html = render({ ok: true, mode: "scorecard", columns: [col("Mine")],
  rows: [row([{ grade: "B", value: 31.25, why: null, low_sample: false }]),
         row([{ grade: "None", value: 0, why: "the build has none of this" }], { category: "control", label: "Control", unit: "weighted_mez_seconds_proxy" })],
  notes: ["Read-only: nothing was solved or saved."] });
ok(html.includes('class="rt-g rt-g-B"'), "letter grades carry their class");
ok(html.includes("31.3 %"), "value shown beside the grade with its unit");
ok(html.includes("the build has none of this"), "scorecard shows why inline");
ok(!html.includes("<th>Gap</th>"), "no Gap column on a scorecard");
ok(html.includes("Read-only: nothing was solved or saved."), "notes rendered");

// 2. comparison: Gap column, best marker, meaningful row, low-sample marker
html = render({ ok: true, mode: "comparison",
  columns: [col("A"), col("B")],
  rows: [row([{ grade: "B", value: 30 }, { grade: "S", value: 45, low_sample: true }],
             { best: [1], meaningful: true, difference: 15 })], notes: [] });
ok(html.includes("<th>Gap</th>"), "comparison has a Gap column");
ok(html.includes('class="rt-best"'), "best cell marked");
ok(html.includes('class="rt-diff"'), "meaningful row marked");
ok(html.includes("Δ 15.0 %"), "gap size shown");
ok(html.includes("rt-low"), "low-sample cut flagged");

// 3. escaping: a save name is user-typed text
html = render({ ok: true, mode: "comparison",
  columns: [col('<img src=x onerror="alert(1)">'), { label: "PvP 'one'", ok: false, error: "PvP <b>not</b> supported" }],
  rows: [row([{ grade: "A", value: 40, why: '"><script>' }, { grade: null, value: null }])], notes: [] });
ok(!html.includes("<img src=x"), "label is escaped");
ok(!html.includes("<script>"), "why text is escaped, including in the title attribute");
ok(html.includes("PvP &lt;b&gt;not&lt;/b&gt; supported"), "a refused column states its reason, escaped");

// 4. flags and unsupported list
html = render({ ok: true, mode: "scorecard",
  columns: [col("X", { rated: false, not_rated_reason: "recalibrate", offense_complete: false,
                       unsupported: [{ power: "Blaster_Ranged.Archery.Ranged_Shot", reason: "unread_redirect" }] })],
  rows: [], notes: [] });
ok(html.includes("Not rated: recalibrate"), "not-rated reason shown");
ok(html.includes("Offense incomplete"), "incomplete offense flagged");
ok(html.includes("unread redirect"), "unsupported powers listed in plain words");

// 5. the comparison states its scope; cross-archetype is flagged
html = render({ ok: true, mode: "comparison", scope: "cross_archetype",
  scope_note: "different archetypes: every grade uses the same all-archetype cut points",
  columns: [col("A"), col("B")], rows: [], notes: [] });
ok(html.includes("Comparing different archetypes") && html.includes('class="rt-flag keep-whole"'),
   "a cross-archetype comparison says so, flagged");
html = render({ ok: true, mode: "comparison", scope: "same_powersets", scope_note: "same archetype and powersets",
  columns: [col("A"), col("B")], rows: [], notes: [] });
ok(html.includes("Comparing same archetype and powersets") && !html.includes("rt-flag keep-whole"),
   "a same-powerset comparison is stated plainly");

// 6. a row without cells never throws
html = render({ ok: true, mode: "scorecard", columns: [col("Y")], rows: [{ label: "Defense", unit: "percent" }], notes: [] });
ok(html.includes("Defense"), "a row missing cells still renders");

// 7. garbage in: never throws
ok(render(null).includes("could not be read"), "a bad response reads as an error, not a crash");

console.log(`test_rating_view: ${checks} checks passed`);
