const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const js = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "static", "index.html"), "utf8");
const start = js.indexOf("function sidekickExportPayload(");
const end = js.indexOf("\nasync function exportSidekick()", start);
assert(start >= 0 && end > start, "Export payload helper must exist");
const fn = vm.runInNewContext("(" + js.slice(start, end).trim() + ")", {});
const original = {
  archetype: "Class_Blaster",
  incarnates: {Alpha: {full_name: "Incarnate.Alpha.Agility_Core_Paragon", active: false}},
  sidekick_attack_chains: [{id: "chain", name: "Original", powers: [], source_powers: []}],
  powers: [{full_name: "Test.Power", slots: [{piece_uid: "Crafted_Damage", boost: 2}]}]
};
const payload = fn(original, "A Character");
assert.equal(payload.name, "A Character");
assert.equal(payload.build.incarnates.Alpha.active, false);
assert.equal(payload.build.sidekick_attack_chains[0].name, "Original");
assert.equal(payload.build.powers[0].slots[0].boost, 2);
assert.equal(payload.allow_dropped_chains, false);
payload.build.incarnates.Alpha.active = true;
assert.equal(original.incarnates.Alpha.active, false, "The export request must be detached");
assert(js.includes('postJson({ ...snapshot, allow_dropped_chains: allowDropped })'));
assert(js.includes('"sidekick_export_dropped_chains"'));
assert(js.includes('offerSidekickDownload(result.download_bytes, status, "export")'));
assert(js.includes('saveTextFile('));
assert(html.includes('id="export-skif-btn"'));
assert(js.includes('$("export-skif-btn").addEventListener("click", exportSidekick)'));
console.log("Sidekick export UI request: passed");
