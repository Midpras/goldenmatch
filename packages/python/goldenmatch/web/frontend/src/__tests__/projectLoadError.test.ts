import { expect, it } from "vitest";
import { ApiError } from "../lib/api";
import { isNoDatasetSelected } from "../lib/projectErrors";

it("recognizes the missing-dataset API response for the friendly project message", () => {
  expect(
    isNoDatasetSelected(
      new ApiError(409, '409 {"detail":"No dataset selected; import a dataset first"}'),
    ),
  ).toBe(true);
});

it("does not classify unrelated project errors as a missing dataset", () => {
  expect(isNoDatasetSelected(new ApiError(409, "409 Conflict"))).toBe(false);
  expect(isNoDatasetSelected(new ApiError(500, "500 Internal Server Error"))).toBe(false);
  expect(isNoDatasetSelected(new Error("No dataset selected"))).toBe(false);
});
