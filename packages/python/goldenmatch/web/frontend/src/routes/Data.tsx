import { useState, type ChangeEvent } from "react";
import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setActiveDatasetId } from "../lib/api";
import type { DataPreview, DatasetSummary, UploadStaged } from "../lib/api";

const DELIMITERS = [
  { label: "Comma ,", value: "," },
  { label: "Tab", value: "\t" },
  { label: "Semicolon ;", value: ";" },
  { label: "Pipe |", value: "|" },
];

export function Data() {
  const queryClient = useQueryClient();
  const pendingMutations = useIsMutating();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const [upload, setUpload] = useState<UploadStaged | null>(null);
  const [name, setName] = useState("");
  const [sheet, setSheet] = useState("");
  const [delimiter, setDelimiter] = useState(",");
  const [preview, setPreview] = useState<DataPreview | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const uploadMutation = useMutation({
    mutationFn: api.uploadDataset,
    onSuccess: (result, file) => {
      setUpload(result);
      setSheet(result.sheets[0] ?? "");
      setName(file.name.replace(/\.(csv|xlsx)$/i, ""));
      setPreview(null);
      setMessage(null);
    },
    onError: (error) => setMessage(error.message),
  });
  const previewMutation = useMutation({
    mutationFn: () => api.previewDatasetUpload(upload!.upload_id, {
      ...(sheet ? { sheet } : {}), delimiter,
    }),
    onSuccess: (result) => { setPreview(result); setMessage(null); },
    onError: (error) => setMessage(error.message),
  });
  const importMutation = useMutation({
    mutationFn: () => api.importDatasetUpload(upload!.upload_id, {
      name: name.trim(), ...(sheet ? { sheet } : {}), delimiter,
    }),
    onSuccess: activateDataset,
    onError: (error) => setMessage(error.message),
  });

  function activateDataset(dataset: DatasetSummary) {
    setActiveDatasetId(dataset.id);
    void queryClient.cancelQueries();
    queryClient.clear();
    window.location.reload();
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUpload(null);
    setPreview(null);
    if (/\.xls$/i.test(file.name)) {
      setMessage("Legacy .xls files are not supported. Save the workbook as .xlsx and upload it again.");
      return;
    }
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      setMessage("Choose a CSV or .xlsx workbook. Legacy .xls is not supported.");
      return;
    }
    setMessage(null);
    setPreview(null);
    uploadMutation.mutate(file);
  }

  return (
    <div className="px-8 py-10 max-w-6xl mx-auto space-y-8">
      <header>
        <p className="eyebrow mb-2">data</p>
        <h1 className="display text-3xl text-ink-900">Datasets</h1>
        <p className="mt-2 max-w-3xl text-sm text-ink-500">Import CSV or Excel .xlsx snapshots. Imports do not replace existing datasets; activate a snapshot to work with it.</p>
      </header>

      <section className="card p-5 space-y-4">
        <h2 className="eyebrow">Upload data</h2>
        <label className="block">
          <span className="eyebrow block mb-2">CSV or .xlsx file</span>
          <input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={handleFile} disabled={uploadMutation.isPending || previewMutation.isPending || importMutation.isPending} />
        </label>
        <p className="text-xs text-ink-500">Maximum upload: 25 MiB; maximum dataset: 100,000 rows. Excel workbooks are read without running formulas. Legacy .xls files are not accepted.</p>
        {uploadMutation.isPending && <p role="status" className="text-sm text-ink-500">Staging upload…</p>}
        {upload && <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
          {upload.sheets.length > 0 && <label className="block">
            <span className="eyebrow block mb-1">Worksheet</span>
            <select className="w-full" value={sheet} disabled={previewMutation.isPending || importMutation.isPending} onChange={(e) => { setSheet(e.target.value); setPreview(null); }}>
              {upload.sheets.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>}
          <label className="block">
            <span className="eyebrow block mb-1">CSV delimiter</span>
            <select className="w-full" value={delimiter} disabled={previewMutation.isPending || importMutation.isPending} onChange={(e) => { setDelimiter(e.target.value); setPreview(null); }}>
              {DELIMITERS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="eyebrow block mb-1">Dataset name</span>
            <input className="w-full" value={name} disabled={importMutation.isPending} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="Customer records" />
          </label>
        </div>}
        {upload && <div className="flex flex-wrap gap-3">
          <button className="btn" onClick={() => previewMutation.mutate()} disabled={previewMutation.isPending || importMutation.isPending}>{previewMutation.isPending ? "Loading preview…" : "Preview first 20 rows"}</button>
          <button className="btn btn-primary" onClick={() => importMutation.mutate()} disabled={!preview || !name.trim() || previewMutation.isPending || importMutation.isPending}>{importMutation.isPending ? "Importing…" : "Import as dataset"}</button>
        </div>}
        {message && <p role="alert" className="text-sm text-red-700 break-words">{message}</p>}
        {preview && <Preview preview={preview} />}
      </section>

      <section className="card p-5">
        <div className="flex items-baseline justify-between gap-4 mb-4">
          <h2 className="eyebrow">Available snapshots</h2>
          <button className="text-xs text-gold-600 hover:text-gold-700" onClick={() => void datasets.refetch()}>Refresh</button>
        </div>
        {datasets.isLoading && <p className="text-sm text-ink-500">Loading datasets…</p>}
        {datasets.error && <p role="alert" className="text-sm text-red-700">{datasets.error.message}</p>}
        {!datasets.isLoading && datasets.data?.items.length === 0 && <p className="text-sm text-ink-500">No data yet. Upload a CSV or workbook above.</p>}
        <div className="divide-y divide-ink-100">
          {datasets.data?.items.map((dataset) => <div key={dataset.id} className="py-4 flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
            <div>
              <p className="font-medium text-ink-900">{dataset.name}</p>
              <p className="text-xs text-ink-500">{dataset.id} · {dataset.source} · {dataset.row_count ?? "unknown"} rows · {dataset.columns.join(", ")}</p>
            </div>
            <button className="btn btn-primary shrink-0" disabled={pendingMutations > 0} onClick={() => activateDataset(dataset)}>Use dataset</button>
          </div>)}
        </div>
      </section>
    </div>
  );
}

function Preview({ preview }: { preview: DataPreview }) {
  return <div className="overflow-auto max-h-[28rem] border border-ink-100 rounded">
    <table className="min-w-full text-xs text-left">
      <thead className="sticky top-0 bg-ink-50"><tr>{preview.columns.map((column) => <th className="px-3 py-2 font-semibold" key={column}>{column}</th>)}</tr></thead>
      <tbody>{preview.rows.map((row, index) => <tr className="border-t border-ink-100" key={index}>{row.map((cell, col) => <td className="px-3 py-2 max-w-64 truncate" key={col}>{cell == null ? "" : String(cell)}</td>)}</tr>)}</tbody>
    </table>
  </div>;
}
