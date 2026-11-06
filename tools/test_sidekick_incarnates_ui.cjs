/** Contract test for per-slot incarnate active-state calculation gates. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const js = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
const start = js.indexOf("function activeIncarnateEntries(");
const end = js.indexOf("\nfunction buildPayload()", start);
assert(start >= 0 && end > start, "The calculation gate must be shared by buildPayload");
const source = js.slice(start, end).trim();
const active = vm.runInNewContext("(" + source + ")", {});
const picks = {
  Alpha: {full_name: "Incarnate.Alpha.Agility_Core_Paragon", active: true},
  Destiny: {full_name: "Incarnate.Destiny.Ageless_Invocation", active: false},
  Hybrid: {full_name: "Incarnate.Hybrid.Assault_Core_Embodiment"}, // older save
};
assert.deepEqual(Array.from(active(picks), ([slot]) => slot), ["Alpha", "Hybrid"]);
assert.deepEqual(Array.from(active({})), []);
assert.equal(picks.Destiny.active, false, "Do not change the saved inactive selection");
assert(js.includes("onchange=\"onIncarnateActive(this)\""),
       "Editor must expose active toggling, not silently lock inactive selections");
// The checkbox lives inside the slot's <label>, whose control is the <select>:
// a click on its words must reach the checkbox (proven with a real mouse in
// Chromium during review; without the handler the dropdown takes the focus).
assert(js.includes('onclick="onIncarnateActiveText(event, this)"'),
       "Clicking 'Active in peak totals' must toggle the checkbox, not focus the select");
const handlerStart = js.indexOf("window.onIncarnateActiveText = function");
assert(handlerStart >= 0, "Text-click handler must exist");
const handler = vm.runInNewContext("(" + js.slice(handlerStart + "window.onIncarnateActiveText = ".length,
  js.indexOf("\n};", handlerStart) + 2) + ")", {});
let clicked = 0, prevented = 0;
const box = {click: () => { clicked++; }};
const span = {querySelector: () => box};
handler({target: {tagName: "SPAN"}, preventDefault: () => { prevented++; }}, span);
handler({target: {tagName: "INPUT"}, preventDefault: () => { prevented++; }}, span);
assert.deepEqual([clicked, prevented], [1, 1], "words toggle once; the box itself is left alone");
console.log("Sidekick incarnate calculator gate: passed");
