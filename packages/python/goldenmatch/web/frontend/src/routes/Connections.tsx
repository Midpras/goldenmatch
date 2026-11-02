import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setActiveDatasetId } from "../lib/api";
import type { ConnectionDraft, ConnectionSummary, DataPreview, DatasetSummary } from "../lib/api";

const emptyDraft: ConnectionDraft = {
  name: "", host: "", port: 5432, database: "", username: "", password: "", sslmode: "verify-full",
};

export function Connections() {
  const queryClient = useQueryClient();
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.connections });
  const [selectedId, setSelectedId] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ConnectionDraft>(emptyDraft);
  const [tableKey, setTableKey] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [preview, setPreview] = useState<DataPreview | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState(false);

  const tables = useQuery({
    queryKey: ["connection-tables", selectedId],
    queryFn: () => api.connectionTables(selectedId),
    enabled: Boolean(selectedId) && connections.data?.items.some((item) => item.id === selectedId) === true,
  });
  const saveMutation = useMutation({
    mutationFn: () => editingId ? api.updateConnection(editingId, withoutBlankPassword(draft)) : api.createConnection(draft),
    onSuccess: async (saved) => {
      setTableKey("");
      setPreview(null);
      setSelectedId(saved.id);
      setEditingId(null);
      setDraft(emptyDraft);
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      report("Connection profile saved.");
    },
    onError: (error) => report(error.message, true),
  });
  const deleteMutation = useMutation({
    mutationFn: api.deleteConnection,
    onSuccess: async (_result, id) => {
      if (selectedId === id) { setSelectedId(""); setTableKey(""); setPreview(null); }
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      report("Connection deleted.");
    },
    onError: (error) => report(error.message, true),
  });
  const testMutation = useMutation({
    mutationFn: api.testConnection,
    onSuccess: () => report("Connection test succeeded."),
    onError: (error) => report(error.message, true),
  });
  const previewMutation = useMutation({
    mutationFn: () => api.previewConnectionTable(selectedId, selectedTable()),
    onSuccess: (result) => { setPreview(result); report("Preview loaded."); },
    onError: (error) => report(error.message, true),
  });
  const importMutation = useMutation({
    mutationFn: () => api.importConnectionTable(selectedId, { ...selectedTable(), name: datasetName.trim() }),
    onSuccess: activateDataset,
    onError: (error) => report(error.message, true),
  });

  function report(message: string, isError = false) {
    setFeedback(message);
    setFeedbackError(isError);
  }
  function selectedTable() {
    const [schema = "", ...rest] = tableKey.split("\u0000");
    return { schema, table: rest.join("\u0000") };
  }
  function activateDataset(dataset: DatasetSummary) {
    setActiveDatasetId(dataset.id);
    void queryClient.cancelQueries();
    queryClient.clear();
    window.location.reload();
  }
  function beginEdit(connection: ConnectionSummary) {
    setSelectedId(connection.id);
    setTableKey("");
    setPreview(null);
    setEditingId(connection.id);
    setDraft({
      name: connection.name, host: connection.host, port: connection.port,
      database: connection.database, username: connection.username,
      password: "", sslmode: connection.sslmode,
    });
    setFeedback(null);
  }
  function resetForm() { setEditingId(null); setDraft(emptyDraft); }
  function update<K extends keyof ConnectionDraft>(key: K, value: ConnectionDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  const selectedConnection = connections.data?.items.find((item) => item.id === selectedId);
  const currentTable = tableKey ? selectedTable() : null;
  const busyImportOrPreview = importMutation.isPending || previewMutation.isPending;
  const saving = saveMutation.isPending || deleteMutation.isPending || busyImportOrPreview;
  return <div className="px-8 py-10 max-w-6xl mx-auto space-y-8">
    <header>
      <p className="eyebrow mb-2">connections</p>
      <h1 className="display text-3xl text-ink-900">Postgres sources</h1>
      <p className="mt-2 max-w-3xl text-sm text-ink-500">Save remote PostgreSQL profiles, inspect read-only tables, preview records, and import a local dataset snapshot.</p>
    </header>

    {connections.data && !connections.data.configured && <section role="status" className="card border-gold-300 bg-gold-50 p-5 text-sm text-ink-800">
      <h2 className="font-semibold">Connection encryption is not configured</h2>
      <p className="mt-2">Set a stable <code>GOLDENMATCH_CONNECTION_KEY</code> environment variable in Coolify, then restart GoldenMatch. Profiles cannot be saved securely until this key is configured. Keep the key in server environment settings; it is never sent to or stored in this browser.</p>
    </section>}
    {feedback && <p role={feedbackError ? "alert" : "status"} className={`text-sm ${feedbackError ? "text-red-700" : "text-green-700"}`}>{feedback}</p>}

    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)] gap-6 items-start">
      <section className="card p-5 space-y-4">
        <div className="flex items-baseline justify-between gap-3"><h2 className="eyebrow">Saved profiles</h2><button className="text-xs text-gold-600" onClick={() => void connections.refetch()}>Refresh</button></div>
        {connections.isLoading && <p className="text-sm text-ink-500">Loading profiles…</p>}
        {connections.error && <p role="alert" className="text-sm text-red-700">{connections.error.message}</p>}
        {!connections.isLoading && connections.data?.items.length === 0 && <p className="text-sm text-ink-500">No connection profiles saved.</p>}
        <div className="divide-y divide-ink-100">
          {connections.data?.items.map((connection) => <div key={connection.id} className="py-3">
            <label className="flex items-start gap-3">
              <input type="radio" name="connection" value={connection.id} checked={selectedId === connection.id} disabled={previewMutation.isPending || importMutation.isPending || testMutation.isPending} onChange={() => { setSelectedId(connection.id); setTableKey(""); setPreview(null); }} />
              <span className="min-w-0 flex-1"><strong className="block text-sm text-ink-900">{connection.name}</strong><span className="block break-all text-xs text-ink-500">{connection.username}@{connection.host}:{connection.port}/{connection.database} · SSL {connection.sslmode} · {connection.has_password ? "password saved" : "no password"}</span></span>
            </label>
            <div className="mt-2 flex gap-3 pl-7 text-xs"><button className="text-gold-600" disabled={saving || testMutation.isPending} onClick={() => beginEdit(connection)}>Edit</button><button className="text-gold-600" disabled={saving || testMutation.isPending} onClick={() => { setSelectedId(connection.id); setTableKey(""); setPreview(null); testMutation.mutate(connection.id); }}>Test</button><button className="text-red-700" disabled={saving || testMutation.isPending} onClick={() => { if (window.confirm(`Delete connection ${connection.name}?`)) deleteMutation.mutate(connection.id); }}>Delete</button></div>
          </div>)}
        </div>
      </section>

      <section className="card p-5">
        <h2 className="eyebrow mb-4">{editingId ? "Edit connection" : "Add connection"}</h2>
        <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); setFeedback(null); saveMutation.mutate(); }}>
          <Field label="Profile name"><input required className="w-full" value={draft.name} disabled={busyImportOrPreview || testMutation.isPending} onChange={(e) => update("name", e.target.value)} /></Field>
          <Field label="Database host"><input required className="w-full" value={draft.host} disabled={busyImportOrPreview || testMutation.isPending} onChange={(e) => update("host", e.target.value)} placeholder="db.example.com" autoComplete="off" /></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Port"><input required type="number" min={1} max={65535} className="w-full" value={draft.port} disabled={busyImportOrPreview || testMutation.isPending} onChange={(e) => update("port", Number(e.target.value))} /></Field><Field label="Database"><input required className="w-full" value={draft.database} disabled={busyImportOrPreview || testMutation.isPending} onChange={(e) => update("database", e.target.value)} autoComplete="off" /></Field></div>
          <Field label="Username"><input required className="w-full" value={draft.username} disabled={busyImportOrPreview || testMutation.isPending} onChange={(e) => update("username", e.target.value)} autoComplete="username" /></Field>
          <Field label={editingId ? "New password (leave blank to keep current)" : "Password"}><input type="password" required={!editingId} className="w-full" value={draft.password ?? ""} disabled={busyImportOrPreview || testMutation.isPending} onChange={(e) => update("password", e.target.value)} autoComplete="new-password" /></Field>
          <Field label="TLS mode"><select className="w-full" value={draft.sslmode} disabled={busyImportOrPreview || testMutation.isPending} onChange={(e) => update("sslmode", e.target.value as ConnectionDraft["sslmode"])}><option value="verify-full">verify-full (recommended)</option><option value="require">require</option><option value="disable">disable</option></select></Field>
          {draft.sslmode === "disable" && <p className="text-xs text-amber-800">Warning: database traffic will not use TLS.</p>}
          <div className="flex gap-3 pt-1"><button className="btn btn-primary" type="submit" disabled={saveMutation.isPending || busyImportOrPreview || testMutation.isPending || !connections.data?.configured}>{saveMutation.isPending ? "Saving…" : editingId ? "Save changes" : "Save connection"}</button>{editingId && <button className="btn" type="button" disabled={busyImportOrPreview || testMutation.isPending} onClick={resetForm}>Cancel</button>}</div>
        </form>
      </section>
    </div>

    {selectedConnection && <section className="card p-5 space-y-4">
      <div><h2 className="eyebrow">Import a table</h2><p className="mt-1 text-xs text-ink-500">Use a read-only database account. The server needs outbound network access to your database. TLS verification is recommended. This interface only selects tables; it does not execute user SQL.</p></div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
        <label className="block"><span className="eyebrow block mb-1">Table</span><select className="w-full" value={tableKey} onChange={(e) => { setTableKey(e.target.value); setPreview(null); }} disabled={tables.isLoading || previewMutation.isPending || importMutation.isPending}><option value="">{tables.isLoading ? "Loading tables…" : "Choose a table"}</option>{tables.data?.items.map((table) => <option key={`${table.schema}.${table.name}`} value={`${table.schema}\u0000${table.name}`}>{table.schema}.{table.name}</option>)}</select></label>
        <label className="block"><span className="eyebrow block mb-1">Dataset name</span><input className="w-full" value={datasetName} disabled={importMutation.isPending} onChange={(e) => setDatasetName(e.target.value)} placeholder="Imported customers" /></label>
        <div className="flex gap-3"><button className="btn" disabled={!currentTable || previewMutation.isPending || importMutation.isPending} onClick={() => previewMutation.mutate()}>{previewMutation.isPending ? "Loading…" : "Preview 20 rows"}</button><button className="btn btn-primary" disabled={!preview || !currentTable || !datasetName.trim() || previewMutation.isPending || importMutation.isPending} onClick={() => importMutation.mutate()}>{importMutation.isPending ? "Importing…" : "Import dataset"}</button></div>
      </div>
      {tables.error && <p role="alert" className="text-sm text-red-700">{tables.error.message}</p>}
      {preview && <Preview preview={preview} />}
    </section>}
  </div>;
}

function withoutBlankPassword(draft: ConnectionDraft): ConnectionDraft {
  const copy = { ...draft };
  if (!copy.password) delete copy.password;
  return copy;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="eyebrow block mb-1">{label}</span>{children}</label>;
}

function Preview({ preview }: { preview: DataPreview }) {
  return <div className="overflow-auto max-h-[28rem] border border-ink-100 rounded"><table className="min-w-full text-xs text-left"><thead className="sticky top-0 bg-ink-50"><tr>{preview.columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}</tr></thead><tbody>{preview.rows.map((row, index) => <tr key={index} className="border-t border-ink-100">{row.map((value, col) => <td key={col} className="px-3 py-2 max-w-64 truncate">{value == null ? "" : String(value)}</td>)}</tr>)}</tbody></table></div>;
}
