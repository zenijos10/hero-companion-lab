const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const js = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "static", "index.html"), "utf8");
const start = js.indexOf("function sidekickExportPayload(");
const end = js.indexOf("// The slots changed since import", start);
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
// Sidekick's slot history rides the export request, and its drop is reported.
const withOrder = fn({...original, sidekick_slot_order: {entries: [{powerName: "P", slotIndex: 1}],
                                                         shape: []}}, "A");
assert.equal(withOrder.build.sidekick_slot_order.entries[0].powerName, "P");
const nStart = js.indexOf("function sidekickSlotOrderNote(");
const nEnd = js.indexOf("async function exportSidekick()", nStart);
const note = vm.runInNewContext("(" + js.slice(nStart, nEnd).trim() + ")", {});
assert.match(note({dropped_slot_order: true}), /slot-by-level history was left out/);
assert.equal(note({dropped_slot_order: false}), "");
assert.match(note({dropped_proc_settings: ["a:b:0"]}), /1 Sidekick proc setting\(s\) were left out/);
assert(js.includes("build.sidekick_proc_settings = null;"), "a new character resets them");
assert(js.includes("build.sidekick_proc_settings = b.sidekick_proc_settings"), "resume restores them");
assert(js.includes("sp: build.sidekick_proc_settings,"), "autosave notices them");
assert(js.includes("+ sidekickSlotOrderNote(result);"));
// A new character never inherits the last one's history; resume restores it.
assert(/build\.sidekick_attack_chains = \[\];\r?\n  build\.sidekick_slot_order = null;/.test(js));
assert(js.includes("build.sidekick_slot_order = b.sidekick_slot_order"));
assert(js.includes("so: build.sidekick_slot_order"));
// Accolade ticks belong to the character: saves keep them, opening restores
// them, the export sends them, and a tick is a change autosave notices.
const aStart = js.indexOf("function buildWithAccolades(");
const withAcc = vm.runInNewContext("(" + js.slice(aStart, js.indexOf("\nfunction renderAccolades()", aStart))
  .replace(/^\/\/.*$/gm, "").trim() + ")", {build: {archetype: "X"}, ACCOLADES_CHECKED: new Set(["Portal_Jockey"])});
assert.deepEqual(JSON.parse(JSON.stringify(withAcc())), {archetype: "X", accolades: ["Portal_Jockey"]});
assert.equal((js.match(/build: buildWithAccolades\(\), plan/g) || []).length, 2, "both save writers");
assert(js.includes("sidekickExportPayload(buildWithAccolades(),"));
assert(js.includes("const known = new Set((await loadAccolades()).map(a => a.key));"));
assert(js.includes("if (!known.size || known.has(k)) ACCOLADES_CHECKED.add(k);"),
       "only accolades the panel knows are restored");
assert(js.includes("ac: [...ACCOLADES_CHECKED],"));
console.log("Sidekick export UI request: passed");
