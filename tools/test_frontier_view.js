// Battery for the M6 alternatives view (app.js renderFrontierHtml).
//   node tools/test_frontier_view.js [alternative app.js]
//
// Lifts the real function out of app.js and drives it with /build/frontier-
// shaped fixtures: every member is listed, "best at" names the unique leader,
// minimums HIDE without deleting (and say how many), sorting reorders,
// minimize objectives sort the other way, the starting build has no "use"
// button, labels are escaped, and a bad response never throws.
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
const escStart = src.indexOf("const escHtml");
const escSrc = src.slice(escStart, escStart + src.slice(escStart).search(/;\r?\n/) + 1);
const render = new Function(`${escSrc}\n${unitsSrc}\n${lift("function renderFrontierHtml")}\nreturn renderFrontierHtml;`)();

const cats = [{ key: "single_target_damage", label: "Single-target damage", unit: "damage_per_second" },
              { key: "defense", label: "Defense", unit: "percent" }];
const member = (fp, label, dmg, def, extra = {}) => Object.assign({
  fingerprint: fp, label, direction: label, is_starting_build: false,
  objectives: { single_target_damage: dmg, defense: def },
  measurements: { single_target_damage: dmg, defense: def },
  grades: { single_target_damage: "B", defense: "C" },
  change_from_start: { single_target_damage: dmg - 40, defense: def - 30 },
  offense_complete: true }, extra);
const res = (members, dirs = ["max", "max"]) => ({
  ok: true, kind: "discovered_frontier", members,
  frontier: { exact: true, objectives: [{ key: "single_target_damage", direction: dirs[0] },
                                        { key: "defense", direction: dirs[1] }] },
  search: { evaluations: 9, stop_reason: "exhausted" }, starting_build: { on_frontier: true } });
let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };
const order = html => [...html.matchAll(/<th scope="row">([^<]*)</g)].map(m => m[1]);

const members = [member("a", "start", 40, 30, { is_starting_build: true }),
                 member("b", "Damage", 80, 20), member("c", "Defense", 35, 45)];
let html = render(res(members), { sortKey: null, mins: {} }, cats);
ok(order(html).length === 3, "every member listed");
ok(html.includes("Best at Single-target damage") && html.includes("Best at Defense"), "unique leaders named");
ok(html.includes("A trade-off"), "a member that leads nothing is called a trade-off");
ok(!html.includes('data-frontier-use="a"') && html.includes('data-frontier-use="b"'), "no use button on the starting build");
ok(html.includes("+40.0 vs yours"), "change from the starting build shown");
ok(html.includes("NOT a proof") || html.includes("not a proof"), "the discovered-frontier claim is stated");

html = render(res(members), { sortKey: "defense", mins: {} }, cats);
ok(order(html).join() === "Defense,start,Damage", "sort reorders by the chosen objective");
html = render(res(members, ["max", "min"]), { sortKey: "defense", mins: {} }, cats);
ok(order(html).join() === "Damage,start,Defense", "a minimize objective sorts low first");
ok(html.includes("(lower is better)"), "minimize objectives say so");

html = render(res(members), { sortKey: null, mins: { defense: 31 } }, cats);
ok(order(html).join() === "Defense", "minimums hide members below them");
ok(html.includes("2 alternative(s) hidden by your minimums; they are still on the list."), "hidden count stated");
html = render(res(members), { sortKey: null, mins: { defense: 99 } }, cats);
ok(html.includes("No alternative meets your minimums."), "an empty view says why");

html = render(res([member("p", "P", 50, 40), member("q", "Q", 60, 40)]), null, cats);
ok(!html.includes("Best at Defense"), "a tie for the lead names no leader");

html = render(res([member("x", '<img src=x onerror="alert(1)">', 1, 1)]), null, cats);
ok(!html.includes("<img src=x"), "labels are escaped");
ok(render(null, null, []).includes("could not be read"), "a bad response never throws");
ok(render({ ok: false, error: "PvP <b>no</b>" }, null, []).includes("PvP &lt;b&gt;no&lt;/b&gt;"), "refusal shown, escaped");

console.log(`test_frontier_view: ${checks} checks passed`);
