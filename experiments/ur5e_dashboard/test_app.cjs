"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { createContext, runInContext } = require("node:vm");

const element = { addEventListener() {}, parentElement: {} };
const context = createContext({
  document: {
    getElementById: () => element,
    querySelectorAll: () => [],
  },
  ResizeObserver: class {
    observe() {}
  },
  // Keep initial data loading pending while testing the actual label functions.
  fetch: () => new Promise(() => {}),
});
runInContext(readFileSync(join(__dirname, "app.js"), "utf8"), context);

test("custom experiment names and statuses do not collide with object properties", () => {
  for (const value of ["constructor", "toString", "__proto__"]) {
    const argument = JSON.stringify(value);
    assert.equal(
      runInContext(`experimentName(${argument}, null)`, context),
      value.replaceAll("_", " "),
    );
    assert.equal(runInContext(`describeStatus(${argument})[0]`, context), value);
    assert.equal(
      runInContext(`describeStatus(${argument})[1]`, context),
      "other",
    );
  }
  assert.equal(
    runInContext('experimentName("stack", null)', context),
    "Three-brick stack",
  );
  assert.equal(
    runInContext('describeStatus("completed")[0]', context),
    "Completed",
  );
  assert.equal(
    runInContext('outcomeName("wrong_stud")', context),
    "Connected at the wrong stud (flagged)",
  );
  assert.equal(
    runInContext('predictionLabel(undefined)', context),
    "Not in the published suite",
  );
  assert.equal(
    runInContext('predictionLabel(false)', context),
    "Differs from prediction",
  );
  assert.equal(
    runInContext('runTitle({case_id: "C01", case_title: "Nominal"})', context),
    "C01 · Nominal",
  );
});
