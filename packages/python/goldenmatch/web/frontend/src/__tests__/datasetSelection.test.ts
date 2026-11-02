// Dynamic imports intentionally simulate page reloads: static imports would
// capture localStorage before the test establishes each document's selection.
import { afterEach, expect, it, vi } from "vitest";

const storageKey = "goldenmatch.datasetId";
const originalSelection = localStorage.getItem(storageKey);

afterEach(() => {
  if (originalSelection === null) localStorage.removeItem(storageKey);
  else localStorage.setItem(storageKey, originalSelection);
  vi.resetModules();
});

it("keeps the rendered dataset selected until reload when another tab switches", async () => {
  localStorage.setItem(storageKey, "snapshot-a");
  vi.resetModules();
  const selection = await import("../lib/api");
  localStorage.setItem(storageKey, "snapshot-b");
  expect(selection.getActiveDatasetId()).toBe("snapshot-a");

  selection.setActiveDatasetId("snapshot-c");
  expect(selection.getActiveDatasetId()).toBe("snapshot-a");
  vi.resetModules();
  const reloadedSelection = await import("../lib/api");
  expect(reloadedSelection.getActiveDatasetId()).toBe("snapshot-c");
});
