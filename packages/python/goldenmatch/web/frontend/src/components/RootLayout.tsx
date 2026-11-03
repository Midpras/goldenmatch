import { useState } from "react";
import { Link, Outlet } from "@tanstack/react-router";
import { useIsMutating, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, clearAuthToken, getActiveDatasetId, hasAuthToken, setActiveDatasetId } from "../lib/api";
import type { ReactNode } from "react";

export function RootLayout() {
  const queryClient = useQueryClient();
  const mutationCount = useIsMutating();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
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
      <header className="px-4 py-4 sm:px-8 sm:py-5 border-b border-ink-200">
        <div className="flex flex-wrap items-center gap-3">
          <Link to="/" className="group flex items-baseline gap-3 select-none">
            <span className="display text-3xl text-gold-500 leading-none group-hover:text-gold-600 transition-colors">GoldenMatch</span>
            <span className="eyebrow hidden sm:inline text-ink-500 group-hover:text-ink-600 transition-colors">entity resolution&nbsp;·&nbsp;workbench</span>
          </Link>
          <button
            type="button"
            className="btn ml-auto min-h-11 xl:hidden"
            aria-controls="primary-navigation"
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen((open) => !open)}
          >
            {mobileNavOpen ? "Close menu" : "Menu"}
          </button>
          <nav
            id="primary-navigation"
            aria-label="Primary navigation"
            onClick={() => setMobileNavOpen(false)}
            className={`${mobileNavOpen ? "grid" : "hidden"} w-full min-w-0 grid-cols-2 gap-1 text-xs sm:grid-cols-3 xl:ml-auto xl:flex xl:w-auto xl:grid-cols-none xl:flex-row xl:flex-wrap xl:items-center xl:justify-end`}
          >
            <NavLink to="/">Project</NavLink><NavLink to="/workbench">Workbench</NavLink><NavLink to="/match">Match</NavLink>
            <NavLink to="/data">Data</NavLink><NavLink to="/connections">Connections</NavLink><NavLink to="/documents">Ingest</NavLink>
            <NavLink to="/compare">Compare</NavLink><NavLink to="/sensitivity">Sensitivity</NavLink><NavLink to="/identities">Identities</NavLink>
            <NavLink to="/memory">Memory</NavLink><NavLink to="/settings">Settings</NavLink>
            {hasAuthToken() && <button type="button" onClick={clearAuthToken} className="col-span-2 min-h-11 border-l border-ink-200 px-3 py-2 uppercase tracking-eyebrow text-ink-500 hover:text-gold-600 transition-colors xl:col-span-1">Sign out</button>}
          </nav>
        </div>
        <div className="mt-4 flex flex-wrap items-start gap-3">
          <label className="flex w-full min-w-0 flex-col items-start gap-2 text-xs text-ink-600 sm:w-auto sm:flex-row sm:items-center">
            <span className="eyebrow text-xs">Active dataset</span>
            <select aria-label="Active dataset" className="w-full min-w-0 sm:w-auto sm:min-w-56 sm:max-w-[28rem]" value={activeId ?? ""} disabled={mutationCount > 0 || datasets.isLoading} onChange={(event) => changeDataset(event.target.value)}>
              {!legacy && !activeId && <option value="" disabled>Choose a dataset</option>}
              {legacy && <option value="">Legacy project (default)</option>}
              {activeId && !active && <option value={activeId}>Unavailable dataset ({activeId})</option>}
              {datasets.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.row_count ?? "?"} rows</option>)}
            </select>
          </label>
          <span className="min-w-0 max-w-full break-words text-xs text-ink-500">{active ? `Using ${active.name}` : activeId ? `Selected dataset ${activeId} is unavailable; choose a valid snapshot or legacy project.` : legacy ? "Using legacy project." : "Choose a dataset or import one from Data."}</span>
          {mutationCount > 0 && <span className="text-xs text-amber-800">Finish the current operation before switching datasets.</span>}
        </div>
      </header>
      <main className="flex-1 min-h-0"><Outlet /></main>
      <div aria-hidden className="h-[2px] frame-strip" />
    </div>
  );
}

function NavLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link to={to} className="flex min-h-11 items-center px-3 py-2 uppercase tracking-eyebrow text-ink-500 hover:text-gold-600 transition-colors" activeProps={{ className: "text-gold-500" }}>{children}</Link>;
}
