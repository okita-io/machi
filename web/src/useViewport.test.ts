import assert from "node:assert/strict";
import { test } from "node:test";
import { PHONE_MAX_WIDTH_PX, isPhoneViewport } from "./useViewport.ts";

test("phone layout starts at 480px and below", () => {
  assert.equal(PHONE_MAX_WIDTH_PX, 480);
  assert.equal(isPhoneViewport(0), true);
  assert.equal(isPhoneViewport(480), true);
  assert.equal(isPhoneViewport(481), false);
  assert.equal(isPhoneViewport(1280), false);
});
