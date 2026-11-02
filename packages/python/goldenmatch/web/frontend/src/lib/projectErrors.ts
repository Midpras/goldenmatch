import { ApiError } from "./api";

export function isNoDatasetSelected(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.message.includes("No dataset selected")
  );
}
