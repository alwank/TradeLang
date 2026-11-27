"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const Timezone = createContext({ local: false, toggle: () => {} });
export const displayKey = "tradelang.display.v1";
type Pane = "navigation" | "strategies" | "editorInspector" | "dock" | "tradeInspector";
type Display = { theme?: "dark" | "light" } & Partial<Record<Pane, boolean>>;
const DisplayContext = createContext({
  display: {} as Display,
  update: (_change: Display) => {},
});
const navigation = [
  ["/strategies", "Strategies", "M4 5h12M4 10h9M4 15h12"],
  ["/datasets", "Datasets", "M3 4h14v12H3zM3 8h14M8 8v8M3 12h14"],
  ["/runs", "Runs", "M6 4l10 6-10 6z"],
  ["/compare", "Compare", "M4 15V9m6 6V4m6 11V7"],
] as const;

export function usePane(name: Pane, fallback = true) {
  const { display, update } = useContext(DisplayContext);
  return [typeof display[name] === "boolean" ? display[name] : fallback,
    (open: boolean) => update({ [name]: open })] as const;
}

export function useDisplayTime() {
  return useContext(Timezone).local;
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [local, setLocal] = useState(false);
  const [display, setDisplay] = useState<Display>({});
  const [loaded, setLoaded] = useState(false);
  const expanded = display.navigation !== false;
  const active = navigation.find(([url]) => path === url || path.startsWith(url + "/"));
  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(displayKey) ?? "null");
      if (stored && typeof stored === "object" && !Array.isArray(stored)) {
        const clean: Display = {};
        if (stored.theme === "light" || stored.theme === "dark") clean.theme = stored.theme;
        for (const pane of ["navigation", "strategies", "editorInspector", "dock", "tradeInspector"] as const) {
          if (typeof stored[pane] === "boolean") clean[pane] = stored[pane];
        }
        setDisplay(clean);
      }
    } catch {}
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (!loaded) return;
    document.documentElement.dataset.theme = display.theme ?? "dark";
    try { localStorage.setItem(displayKey, JSON.stringify(display)); } catch {}
  }, [display, loaded]);
  const update = (change: Display) => setDisplay((current) => ({ ...current, ...change }));
  return (
    <DisplayContext.Provider value={{ display, update }}>
    <Timezone.Provider value={{ local, toggle: () => setLocal((value) => !value) }}>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="shell-context">
          <Link href="/strategies" className="brand"><span aria-hidden="true" className="brand-mark">TL</span>TradeLang</Link>
          {active && <span className="shell-section">{active[1]}</span>}
        </div>
        <label className="inline-field theme-select">Theme
          <select value={display.theme ?? "dark"} onChange={(event) => update({ theme: event.target.value === "light" ? "light" : "dark" })}>
            <option value="dark">Graphite</option><option value="light">Light</option>
          </select>
        </label>
      </header>
      <div className={expanded ? "terminal" : "terminal nav-collapsed"}>
        <div className="navigation-rail">
          <nav id="workspace-navigation" aria-label="Main navigation">
            {navigation.map(([url, label, icon]) => (
              <Link key={url} href={url} aria-label={label} title={label}
                aria-current={active?.[0] === url ? "page" : undefined}>
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor"
                  strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d={icon} /></svg>
                <span>{label}</span>
              </Link>
            ))}
          </nav>
          <button className="button compact rail-toggle" onClick={() => update({ navigation: !expanded })}
            aria-expanded={expanded} aria-controls="workspace-navigation"
            aria-label={expanded ? "Collapse navigation labels" : "Expand navigation labels"}
            title={expanded ? "Collapse navigation labels" : "Expand navigation labels"}>
            <span aria-hidden="true">{expanded ? "‹" : "›"}</span>{expanded && <span>Collapse</span>}
          </button>
        </div>
        <main id="main" tabIndex={-1} className="main">{children}</main>
      </div>
    </Timezone.Provider>
    </DisplayContext.Provider>
  );
}

export function TimeToggle() {
  const { local, toggle } = useContext(Timezone);
  return <button className="button compact" type="button" onClick={toggle} aria-pressed={local}>
    Display time: {local ? "Local" : "UTC"}
  </button>;
}

export function Time({ value, dateOnly = false }: { value: string | null | undefined; dateOnly?: boolean }) {
  const { local } = useContext(Timezone);
  if (!value) return "—";
  const rendered = new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: dateOnly ? undefined : "short",
    hourCycle: "h23",
    timeZone: local ? undefined : "UTC",
  }).format(new Date(value));
  return <time dateTime={value}>{rendered}{local || dateOnly ? "" : " UTC"}</time>;
}
