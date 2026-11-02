import { Link, Outlet } from "@tanstack/react-router";
import { useIsMutating, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, clearAuthToken, getActiveDatasetId, hasAuthToken, setActiveDatasetId } from "../lib/api";
import type { ReactNode } from "react";

export function RootLayout() {
  const queryClient = useQueryClient();
  const mutationCount = useIsMutating();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const activeId = getActiveDatasetId();
  const active = datasets.data?.items.find((item) => item.id === activeId);
  const legacy = datasets.data?.items.find((item) => item.id === "legacy");

  function changeDataset(id: string) {
    if (mutationCount > 0 || id === (activeId ?? "")) return;
    void queryClient.cancelQueries();
    setActiveDatasetId(id || null);
    queryClient.clear();
    window.location.reload();
  }

  return (
    <div className="min-h-screen flex flex-col">
      <div aria-hidden className="h-[2px] frame-strip" />
      <header className="px-8 py-5 border-b border-ink-200">
        <div className="flex flex-wrap items-end gap-4">
          <Link to="/" className="group flex items-baseline gap-3 select-none">
            <span className="display text-3xl text-gold-500 leading-none group-hover:text-gold-600 transition-colors">GoldenMatch</span>
            <span className="eyebrow text-ink-400 group-hover:text-ink-500 transition-colors">entity resolution&nbsp;·&nbsp;workbench</span>
          </Link>
          <nav className="ml-auto flex flex-wrap items-center gap-1 text-[12px]">
            <NavLink to="/">Project</NavLink><NavLink to="/workbench">Workbench</NavLink><NavLink to="/match">Match</NavLink>
            <NavLink to="/data">Data</NavLink><NavLink to="/connections">Connections</NavLink><NavLink to="/documents">Ingest</NavLink>
            <NavLink to="/compare">Compare</NavLink><NavLink to="/sensitivity">Sensitivity</NavLink><NavLink to="/identities">Identities</NavLink>
            <NavLink to="/memory">Memory</NavLink><NavLink to="/settings">Settings</NavLink>
            {hasAuthToken() && <button type="button" onClick={clearAuthToken} className="ml-2 border-l border-ink-200 px-3 py-2 uppercase tracking-eyebrow text-ink-500 hover:text-gold-600 transition-colors">Sign out</button>}
          </nav>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-ink-600">
            <span className="eyebrow">Active dataset</span>
            <select aria-label="Active dataset" className="min-w-56" value={activeId ?? ""} disabled={mutationCount > 0 || datasets.isLoading} onChange={(event) => changeDataset(event.target.value)}>
              {!legacy && !activeId && <option value="" disabled>Choose a dataset</option>}
              {legacy && <option value="">Legacy project (default)</option>}
              {activeId && !active && <option value={activeId}>Unavailable dataset ({activeId})</option>}
              {datasets.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.row_count ?? "?"} rows</option>)}
            </select>
          </label>
          <span className="text-xs text-ink-500">{active ? `Using ${active.name}` : activeId ? `Selected dataset ${activeId} is unavailable; choose a valid snapshot or legacy project.` : legacy ? "Using legacy project." : "Choose a dataset or import one from Data."}</span>
          {mutationCount > 0 && <span className="text-xs text-amber-800">Finish the current operation before switching datasets.</span>}
        </div>
      </header>
      <main className="flex-1 min-h-0"><Outlet /></main>
      <div aria-hidden className="h-[2px] frame-strip" />
    </div>
  );
}

function NavLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link to={to} className="px-3 py-2 uppercase tracking-eyebrow text-ink-500 hover:text-gold-600 transition-colors" activeProps={{ className: "text-gold-500" }}>{children}</Link>;
}
