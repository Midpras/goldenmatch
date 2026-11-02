import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Data } from "../routes/Data";

vi.mock("../lib/api", () => ({
  api: {
    datasets: vi.fn(),
    uploadDataset: vi.fn(),
    previewDatasetUpload: vi.fn(),
    importDatasetUpload: vi.fn(),
  },
  setActiveDatasetId: vi.fn(),
}));


beforeEach(() => {
  vi.mocked(api.datasets).mockResolvedValue({ items: [] });
  vi.mocked(api.uploadDataset).mockResolvedValue({ upload_id: "upload-1", sheets: [] });
  vi.mocked(api.previewDatasetUpload).mockResolvedValue({ columns: ["id"], rows: [["1"]] });
  vi.mocked(api.importDatasetUpload).mockReset();
});
it("offers a Browse files button and explains why import is disabled", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Data />
    </QueryClientProvider>,
  );
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  const clickInput = vi.spyOn(input, "click");

  fireEvent.click(screen.getByRole("button", { name: "Browse files" }));
  expect(clickInput).toHaveBeenCalledOnce();

  fireEvent.change(input, {
    target: { files: [new File(["id\n1"], "customers.csv", { type: "text/csv" })] },
  });
  await waitFor(() => expect(api.uploadDataset).toHaveBeenCalledOnce());
  expect(await screen.findByText("customers.csv")).toBeInTheDocument();
  expect(screen.getByText("Preview the file to enable import.")).toBeInTheDocument();

  const importButton = screen.getByRole("button", { name: "Import as dataset" });
  expect(importButton).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Preview first 20 rows" }));
  await waitFor(() => expect(importButton).toBeEnabled());

  fireEvent.change(screen.getByLabelText("Dataset name"), { target: { value: "" } });
  expect(importButton).toBeDisabled();
  expect(screen.getByText("Enter a dataset name to enable import.")).toBeInTheDocument();
});
