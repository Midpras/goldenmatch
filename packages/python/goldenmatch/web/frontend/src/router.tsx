import {
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { RootLayout } from "./components/RootLayout";
import { Compare } from "./routes/Compare";
import { Connections } from "./routes/Connections";
import { Data } from "./routes/Data";
import { Documents } from "./routes/Documents";
import { Home } from "./routes/Home";
import { Inspector } from "./routes/Inspector";
import { Match } from "./routes/Match";
import { Identities } from "./routes/Identities";
import { Memory } from "./routes/Memory";
import { Sensitivity } from "./routes/Sensitivity";
import { Settings } from "./routes/Settings";
import { Workbench } from "./routes/Workbench";

const rootRoute = createRootRoute({ component: RootLayout });
const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Home,
});

const inspectorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$name",
  component: Inspector,
});

const workbenchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/workbench",
  component: Workbench,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: Settings,
});

const compareRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/compare",
  component: Compare,
});

const sensitivityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sensitivity",
  component: Sensitivity,
});

const matchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/match",
  component: Match,
});

const memoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/memory",
  component: Memory,
});

const documentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/documents",
  component: Documents,
});

const identitiesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/identities",
  component: Identities,
});
const dataRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/data",
  component: Data,
});

const connectionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/connections",
  component: Connections,
});


const routeTree = rootRoute.addChildren([
  homeRoute,
  inspectorRoute,
  workbenchRoute,
  compareRoute,
  sensitivityRoute,
  matchRoute,
  dataRoute,
  connectionsRoute,
  memoryRoute,
  identitiesRoute,
  documentsRoute,
  settingsRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
