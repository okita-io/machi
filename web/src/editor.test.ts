import assert from "node:assert/strict";
import { test } from "node:test";
import { editorReducer, exportEnabled, initialEditorState } from "./editor.ts";

test("export enables only after the current yaml validates", () => {
  let state = initialEditorState();
  assert.equal(exportEnabled(state), false);

  state = editorReducer(state, { type: "edit", yaml: "id: draft\n" });
  assert.equal(state.status, "editing");
  assert.equal(exportEnabled(state), false);

  state = editorReducer(state, {
    type: "validated",
    ok: false,
    errors: [{ path: "id", message: "missing flow", line: 1 }],
  });
  assert.equal(state.status, "invalid");
  assert.equal(exportEnabled(state), false);

  state = editorReducer(state, { type: "validated", ok: true, id: "draft" });
  assert.equal(state.status, "valid");
  assert.equal(state.filename, "draft.yaml");
  assert.equal(exportEnabled(state), true);

  state = editorReducer(state, { type: "edit", yaml: "id: draft\nbonus: 1\n" });
  assert.equal(state.status, "editing");
  assert.equal(exportEnabled(state), false);

  state = editorReducer(state, {
    type: "load",
    yaml: "id: restaurant_ramen_01\n",
    filename: "restaurant_ramen_01.yaml",
  });
  assert.equal(exportEnabled(state), false);
  state = editorReducer(state, { type: "validated", ok: true, id: "restaurant_ramen_01" });
  assert.equal(exportEnabled(state), true);
});
