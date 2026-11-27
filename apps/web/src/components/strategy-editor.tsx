"use client";

import type { EditorView } from "@codemirror/view";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ApiError, api, read, type Diagnostic, type DraftCheck, type Explanation, type Health, type RunPreset, type RunSettings, type Strategy, type Validation } from "@/lib/api";
import { loadDraft, storeDraft, type Draft } from "@/lib/draft";
import { integer, memory } from "@/lib/format";
import { isActive, runStatus, useRunStatus, type Run } from "@/lib/run-status";
import { loadAttempts, pruneAttempts, storeAttempts, type Attempt } from "@/lib/submission";
import type { components } from "@/lib/schema";
import { useResource } from "@/lib/use-resource";
import { applyDiagnosticFix, CodeEditor, focusDiagnostic } from "./code-editor";
import { RunDetail } from "./run-detail";
import { Details, Notice, Pending } from "./ui";
import { Time, usePane } from "./shell";

const noDiagnostics: Diagnostic[] = [];
type RunRequest = components["schemas"]["BacktestRequest"];
type RunInputs = Omit<RunRequest, "strategy_id" | "strategy_revision">;
type CapturedRun = { revision: Strategy; inputs: RunInputs };
type AssetStrategy = Pick<Strategy, "id" | "name" | "current_revision">;
const assetStrategyValue = (strategy: AssetStrategy) => `${strategy.id}:${strategy.current_revision}`;
const profileRequired = (source: string) =>
  /\bVPROFILE\s*\(/.test(source.replace(/"(?:[^"\\]|\\.)*"|#[^\r\n]*/g, ""));
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;

export function StrategyEditor({ id }: { id: string }) {
  const record = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/strategies/{ident}", { params: { path: { ident: id } }, signal },
  )), [id]));
  if (record.error) return <>
    <h1>Strategy unavailable</h1><Notice error={record.error} />
    <div className="actions"><Link href="/strategies">Open Strategies</Link>
      <button className="button" onClick={record.reload}>Retry</button></div>
  </>;
  if (!record.data) return <Pending>Loading strategy…</Pending>;
  return <EditorWorkspace record={record.data} />;
}

function EditorWorkspace({ record }: { record: Strategy }) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const explicitDataset = params.get("dataset") ?? "";
  const requestedRun = params.get("run");
  const runId = requestedRun && uuid.test(requestedRun) ? requestedRun.toLowerCase() : null;
  const viewingResult = params.has("run");
  const savedParams = new URLSearchParams(params.toString());
  savedParams.delete("run");
  const sourceUrl = savedParams.size ? `${path}?${savedParams}` : path;
  const runUrl = (id: string) => {
    const query = new URLSearchParams(savedParams);
    query.set("run", id);
    return `${path}?${query}`;
  };
  const [previousRun, setPreviousRun] = useState(runId);
  const openRun = viewingResult ? runId : previousRun;

  const workspace = useRef<HTMLDivElement>(null);
  const editor = useRef<EditorView | null>(null);
  const dockTabs = useRef<HTMLDivElement>(null);
  const previousSourceFocus = useRef(false);
  const requests = useRef<Partial<Record<"validate" | "explain", AbortController>>>({});
  const runAttempts = useRef(new Map<string, Attempt>());
  const submitLock = useRef(false);
  const saveLock = useRef(false);
  const configGeneration = useRef(0);
  const mounted = useRef(false);
  const [saved, setSaved] = useState(record);
  const savedRecord = useRef(record);
  const [source, setSource] = useState(record.current_source);
  const latestSource = useRef(record.current_source);
  const [recovered, setRecovered] = useState<Draft>();
  const draftPending = useRef(false);
  const [cacheError, setCacheError] = useState(false);
  const [submitted, setSubmitted] = useState<Run[]>([]);
  const latestRun = useRunStatus(submitted[0]?.id, submitted[0]);
  const [datasetOverride, setDatasetId] = useState<string | undefined>(explicitDataset || undefined);
  const [profileOverride, setProfileId] = useState<string>();
  const [feedIds, setFeedIds] = useState<Record<string, string>>({});
  const [portfolioBindings, setPortfolioBindings] = useState<Record<string, {
    strategy?: AssetStrategy; dataset_id?: string; profile_dataset_id?: string; feed_name?: string; feed_dataset_id?: string;
    settings?: RunSettings; parameters_text?: string;
  }>>({});
  const [preset, setPreset] = useState<RunPreset>();
  const [presetName, setPresetName] = useState("");
  const [presetBusy, setPresetBusy] = useState(false);
  const [settings, setSettings] = useState<RunSettings>({});
  const [inspectPanel, setInspectPanel] = useState<"Explain" | "Assumptions">("Explain");
  const [dockPanel, setDockPanel] = useState<"Problems" | "Runs">("Problems");
  const [inspectorOpen, setInspectorOpen] = usePane("editorInspector");
  const [dockOpen, setDockOpen] = usePane("dock");
  const [switchOpen, setSwitchOpen] = usePane("strategies", false);
  const [validation, setValidation] = useState<Validation>();
  const [syntax, setSyntax] = useState<{ source: string; result: DraftCheck }>();
  const [parameterOverrides, setParameterOverrides] = useState<Record<string, number | boolean>>({});
  const [explanation, setExplanation] = useState<Explanation>();
  const [validating, setValidating] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [combining, setCombining] = useState(false);
  const [retryCombined, setRetryCombined] = useState<CapturedRun>();
  const [health, setHealth] = useState<Health>();
  const [error, setError] = useState<unknown>();
  const [conflict, setConflict] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const datasets = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/datasets", { params: { query: { limit: 500 } }, signal },
  )), []));
  const presets = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/run-presets", { params: { query: { limit: 500 } }, signal },
  )), []));
  const strategies = useResource(useCallback(async (signal) => (switchOpen || /\btradelang\s+9\b/.test(source)) ? read(await api.GET(
    "/api/v1/strategies", { params: { query: { limit: 500 } }, signal },
  )) : undefined, [switchOpen, source]));
  const dirty = source !== saved.current_source;
  const datasetId = datasetOverride ?? preset?.dataset_id ?? "";
  const profileId = profileOverride ?? preset?.profile_dataset_id ?? "";
  const currentDataset = datasets.data?.items.find((row) => row.id === datasetId);
  const currentProfile = datasets.data?.items.find((row) => row.id === profileId);
  const syntaxResult = syntax?.source === source ? syntax.result : undefined;
  const candidateSpec = validation?.spec ?? syntaxResult?.spec;
  const portfolioSpec = candidateSpec?.dsl_version === 9 ? candidateSpec : undefined;
  const strategySpec = candidateSpec?.dsl_version === 9 ? undefined : candidateSpec;
  const validatedStrategy = validation?.spec?.dsl_version === 9 ? undefined : validation?.spec;
  const modernSpec = strategySpec && strategySpec.dsl_version !== 1 ? strategySpec : undefined;
  const definitions = modernSpec?.parameters ?? [];
  const needsProfile = modernSpec?.requires_profile ?? profileRequired(source);
  const requiredFeeds = modernSpec && "required_feeds" in modernSpec ? modernSpec.required_feeds : [];
  const missingFeed = requiredFeeds.find((name) => !Object.hasOwn(feedIds, name) || !feedIds[name]);
  const configured = Boolean(preset || Object.keys(settings).length);
  function assetParameters(text?: string): Record<string, number | boolean> | undefined {
    if (!text?.trim()) return {};
    try {
      const value: unknown = JSON.parse(text);
      if (!value || typeof value !== "object" || Array.isArray(value) ||
          Object.values(value).some((item) => typeof item !== "boolean" &&
            (typeof item !== "number" || !Number.isFinite(item)))) return undefined;
      return value as Record<string, number | boolean>;
    } catch {
      return undefined;
    }
  }
  const assetSelections = portfolioSpec && Object.fromEntries(portfolioSpec.assets.map((name) => {
    const binding = portfolioBindings[name];
    const strategy = binding?.strategy;
    const parameters = assetParameters(binding?.parameters_text);
    return [name, binding && strategy && binding.dataset_id && parameters && Boolean(binding.feed_name) === Boolean(binding.feed_dataset_id) ? {
      strategy_id: strategy.id, strategy_revision: strategy.current_revision, dataset_id: binding.dataset_id,
      profile_dataset_id: binding.profile_dataset_id || undefined,
      feed_ids: binding.feed_name && binding.feed_dataset_id ? { [binding.feed_name]: binding.feed_dataset_id } : undefined,
      settings: { ...binding.settings, parameters },
    } : null];
  }));
  const assetStrategies = strategies.data?.items.filter((item) => item.id !== saved.id) ?? [];
  const portfolioReady = Boolean(portfolioSpec && assetSelections &&
    Object.values(assetSelections).every(Boolean));
  const selection = portfolioSpec ? {
    portfolio_assets: portfolioReady ? assetSelections as Record<string, { strategy_id: string; strategy_revision: number; dataset_id: string }> : undefined,
  } : {
    dataset_id: preset ? datasetOverride === undefined ? undefined : datasetOverride || null : datasetId || undefined,
    profile_dataset_id: needsProfile
      ? preset ? profileOverride === undefined ? undefined : profileOverride || null : profileId || undefined
      : preset?.profile_dataset_id ? null : undefined,
    preset_id: preset?.id,
    preset_revision: preset?.revision,
    settings: configured ? settings : undefined,
    parameters: Object.keys(parameterOverrides).length ? parameterOverrides : undefined,
    feed_ids: requiredFeeds.length && !missingFeed
      ? Object.fromEntries(requiredFeeds.map((name) => [name, feedIds[name]]))
      : undefined,
  };
  const primaryInput = currentDataset?.filename ?? (datasetId ? `dataset ${datasetId}` : "source only");
  const primaryInputs = [
    primaryInput,
    ...(needsProfile && profileId ? [currentProfile?.filename ?? `dataset ${profileId}`] : []),
    ...requiredFeeds.filter((name) => Object.hasOwn(feedIds, name) && feedIds[name]).map((name) =>
      `${name} · ${datasets.data?.items.find((item) => item.id === feedIds[name])?.filename ?? feedIds[name]}`),
  ].join(" + ");
  const input = portfolioSpec
    ? portfolioReady ? `${portfolioSpec.assets.length} portfolio assets` : "source only"
    : primaryInputs;
  const compatible = validation?.valid && validation.data_compatible === true &&
    validation.source_hash === saved.source_hash && (portfolioSpec ? portfolioReady :
      currentDataset && (!needsProfile || currentProfile) && !missingFeed);
  const ready = !dirty && !recovered && !conflict && Boolean(compatible && health?.worker_available) &&
    !saving && !running && !validating && !combining;
  const canCombine = Boolean((portfolioSpec ? portfolioReady : currentDataset && (!needsProfile || currentProfile) && !missingFeed) &&
    health?.worker_available && !recovered && !conflict && !saving && !running && !combining);
  const canRetryCombined = Boolean(retryCombined && health?.worker_available &&
    !recovered && !conflict && !saving && !running && !combining);
  const checkedDiagnostics = validation?.diagnostics ?? explanation?.diagnostics;
  const useDraftErrors = !checkedDiagnostics ||
    (!validation?.valid && !explanation?.valid && Object.keys(parameterOverrides).length === 0);
  const diagnostics = useDraftErrors && syntaxResult ? [
    ...syntaxResult.diagnostics,
    ...(checkedDiagnostics ?? []).filter((item) => !syntaxResult.diagnostics.some((draft) =>
      draft.code === item.code && draft.span?.start_byte === item.span?.start_byte &&
      draft.span?.end_byte === item.span?.end_byte)),
  ] : checkedDiagnostics ?? noDiagnostics;
  const draftFixes = syntaxResult?.diagnostics ?? noDiagnostics;
  const currentWindow = validation?.resolved_window ?? explanation?.resolved_window;
  const effective = validation?.run_configuration ?? explanation?.run_configuration;
  const sourceConfig = strategySpec?.backtest;
  const resolvedCosts = effective ?? validatedStrategy?.backtest;
  const workload = validation?.workload ?? explanation?.workload;
  const errorCount = diagnostics.filter((item) => item.severity === "error").length;
  const warningCount = diagnostics.filter((item) => item.severity === "warning").length;
  const runHint = combining ? "Validating, saving, and submitting the captured source" :
    running ? "Submitting the saved revision" : saving ? "Saving the revision" :
    validating ? "Validating the selected inputs" : recovered ? "Resolve the recovered draft" : conflict ? "Load the latest saved revision" :
    dirty ? "Save revision to run" : portfolioSpec && !portfolioReady ? "Select a strategy and dataset for each asset" :
      !portfolioSpec && !currentDataset ? "Select a dataset to run" :
      needsProfile && !currentProfile ? "Select a Volume Profile dataset" :
        missingFeed ? `Select a dataset for feed ${missingFeed}` :
        !health?.worker_available ? "The run worker is unavailable" :
          !compatible ? "Validate the saved revision with the selected data" : "";
  const changedBase = recovered &&
    (recovered.revision !== saved.current_revision || recovered.hash !== saved.source_hash);

  const persist = useCallback(() => {
    if (draftPending.current) return true;
    try {
      storeDraft(savedRecord.current, latestSource.current);
      setCacheError(false);
      return true;
    } catch {
      const unsaved = latestSource.current !== savedRecord.current.current_source;
      setCacheError(unsaved);
      return !unsaved;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    runAttempts.current = loadAttempts(record.id);
    try {
      const draft = loadDraft(record.id);
      if (draft && draft.source !== record.current_source) {
        draftPending.current = true;
        setRecovered(draft);
      } else if (draft) storeDraft(record, record.current_source);
    } catch {}
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!persist()) {
        event.preventDefault();
        event.returnValue = true;
      }
    };
    const onHide = () => { if (document.visibilityState === "hidden") persist(); };
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("pagehide", persist);
    document.addEventListener("visibilitychange", onHide);
    return () => {
      persist();
      mounted.current = false;
      window.removeEventListener("beforeunload", beforeUnload);
      window.removeEventListener("pagehide", persist);
      document.removeEventListener("visibilitychange", onHide);
    };
  }, [record, persist]);

  useEffect(() => {
    if (draftPending.current) return;
    const timer = setTimeout(persist, 220);
    return () => clearTimeout(timer);
  }, [source, saved, persist]);

  useEffect(() => {
    const verifyLink = (event: MouseEvent) => {
      const link = (event.target as HTMLElement | null)?.closest("a[href]") as HTMLAnchorElement | null;
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey ||
        link.pathname === path || link.download || link.target === "_blank") return;
      if (!persist() && !window.confirm("Your draft could not be stored. Leave without saving?")) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    document.addEventListener("click", verifyLink, true);
    return () => document.removeEventListener("click", verifyLink, true);
  }, [path, persist]);

  const invalidate = useCallback(() => {
    configGeneration.current++;
    requests.current.validate?.abort();
    requests.current.explain?.abort();
    setValidation(undefined);
    setExplanation(undefined);
    setValidating(false);
    setExplaining(false);
    setAnnouncement("");
  }, []);

  useEffect(() => {
    if (!explicitDataset) return;
    setDatasetId(explicitDataset);
    setProfileId((current) => current === explicitDataset ? "" : current);
    invalidate();
  }, [explicitDataset, invalidate]);

  useEffect(() => {
    if (!source.trim()) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const result = read(await api.POST("/api/v1/strategies/draft-check", {
          body: { source }, signal: controller.signal,
        }));
        if (!controller.signal.aborted && latestSource.current === source) setSyntax({ source, result });
      } catch {
        // The manual validation action reports transport errors.
      }
    }, 500);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [source]);

  useEffect(() => {
    if (runId) setPreviousRun(runId);
    if (viewingResult) {
      previousSourceFocus.current = true;
    } else if (previousSourceFocus.current) {
      previousSourceFocus.current = false;
      editor.current?.requestMeasure();
      editor.current?.focus();
    }
  }, [runId, viewingResult]);

  useEffect(() => {
    const inspections = requests.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function check() {
      try {
        const response = await fetch("/api/health", { signal: controller.signal, cache: "no-store" });
        const value: Health = await response.json();
        if (!controller.signal.aborted) setHealth(response.ok && value.schema_version === 1 ? value : undefined);
      } catch {
        if (!controller.signal.aborted) setHealth(undefined);
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(check, 5000);
      }
    }
    void check();
    return () => {
      inspections.validate?.abort();
      inspections.explain?.abort();
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  function edit(value: string) {
    if (value === latestSource.current) return;
    latestSource.current = value;
    setSource(value);
    setSyntax(undefined);
    setParameterOverrides({});
    invalidate();
  }

  function changeParameter(name: string, value: number | boolean | undefined) {
    setParameterOverrides((previous) => value === undefined
      ? Object.fromEntries(Object.entries(previous).filter(([key]) => key !== name))
      : { ...previous, [name]: value });
    invalidate();
  }

  function choosePreset(option: RunPreset | undefined) {
    setPreset(option);
    setPresetName(option?.name ?? "");
    setSettings({});
    setDatasetId(option ? undefined : datasetId || undefined);
    setProfileId(option ? undefined : profileId || undefined);
    setParameterOverrides({});
    invalidate();
  }

  function changeSetting<K extends keyof RunSettings>(field: K, value: RunSettings[K]) {
    setSettings((previous) => {
      const next = { ...previous };
      if (value === undefined) delete next[field];
      else next[field] = value;
      return next;
    });
    invalidate();
  }

  async function savePreset(update: boolean) {
    const name = presetName.trim();
    if (!name || presetBusy) return;
    const generation = configGeneration.current;
    setPresetBusy(true);
    setError(undefined);
    const body = {
      name,
      dataset_id: datasetId || null,
      profile_dataset_id: needsProfile ? profileId || null : null,
      settings: {
        ...preset?.settings, ...settings,
        parameters: { ...preset?.settings.parameters, ...parameterOverrides },
      },
    };
    try {
      const stored = update && preset
        ? read(await api.PUT("/api/v1/run-presets/{ident}", {
          params: { path: { ident: preset.id } },
          body: { ...body, expected_revision: preset.revision },
        }))
        : read(await api.POST("/api/v1/run-presets", { body }));
      presets.reload();
      if (generation === configGeneration.current) choosePreset(stored);
      setAnnouncement(update ? "Run preset updated." : "Run preset saved.");
    } catch (cause) {
      setError(cause);
      if (cause instanceof ApiError && cause.code === "E_PRESET_CONFLICT") presets.reload();
    } finally {
      setPresetBusy(false);
    }
  }

  function fixDiagnostic(item: Diagnostic) {
    if (!syntax || syntax.source !== latestSource.current || !syntax.result.diagnostics.includes(item)) return;
    const fixed = applyDiagnosticFix(editor.current, latestSource.current, item);
    if (fixed !== undefined) edit(fixed);
  }

  function replaceSource(value: string) {
    const view = editor.current;
    if (view) view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value.replace(/\r\n?|\n/g, "\n") } });
    edit(value);
  }

  function resolveDraft(restore: boolean) {
    const draft = recovered;
    draftPending.current = false;
    setRecovered(undefined);
    if (restore && draft) replaceSource(draft.source);
    persist();
    setAnnouncement(restore ? "Draft restored." : "Draft discarded.");
    requestAnimationFrame(() => editor.current?.focus());
  }

  async function inspect(kind: "validate" | "explain") {
    requests.current[kind]?.abort();
    const controller = new AbortController();
    requests.current[kind] = controller;
    const pending = kind === "validate" ? setValidating : setExplaining;
    pending(true);
    setError(undefined);
    setAnnouncement("");
    const body = { ...selection, source: latestSource.current };
    try {
      if (kind === "validate") {
        const result = read(await api.POST("/api/v1/strategies/validate", { body, signal: controller.signal }));
        if (controller.signal.aborted) return;
        setValidation(result);
        const errors = result.diagnostics.filter((item) => item.severity === "error").length;
        setAnnouncement(errors ? `Validation found ${errors} ${errors === 1 ? "error" : "errors"}.` :
          result.data_compatible ? "Strategy and dataset validated." : "Strategy source validated.");
      } else {
        const result = read(await api.POST("/api/v1/strategies/explain", { body, signal: controller.signal }));
        if (controller.signal.aborted) return;
        setExplanation(result);
        setAnnouncement(result.valid ? "Explanation ready." : "Check strategy diagnostics.");
        if (!result.valid) setDockPanel("Problems");
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause);
        if (cause instanceof ApiError && cause.code === "E_PRESET_CONFLICT") presets.reload();
      }
    } finally {
      if (!controller.signal.aborted) pending(false);
    }
  }

  function validate() {
    if (validating || recovered) return;
    setDockPanel("Problems");
    void inspect("validate");
  }

  function acceptSaved(value: Strategy) {
    savedRecord.current = value;
    setSaved(value);
    persist();
  }

  async function reloadSaved(discard: boolean) {
    const value = read(await api.GET("/api/v1/strategies/{ident}", {
      params: { path: { ident: record.id } },
    }));
    if (!mounted.current) return;
    if (discard) replaceSource(value.current_source);
    else invalidate();
    acceptSaved(value);
    setConflict(false);
  }

  async function writeRevision(base: Strategy, draft: string) {
    return read(await api.PUT("/api/v1/strategies/{ident}", {
      params: { path: { ident: base.id }, header: { "If-Match": base.etag } },
      body: { source: draft, name: base.name, expected_revision: base.current_revision },
    }));
  }

  async function save() {
    const base = savedRecord.current;
    const draft = latestSource.current;
    if (draft === base.current_source || saveLock.current || recovered || conflict) return;
    saveLock.current = true;
    setSaving(true);
    setError(undefined);
    try {
      const updated = await writeRevision(base, draft);
      if (!mounted.current) return;
      acceptSaved(updated);
      setAnnouncement(latestSource.current === draft ? "Revision saved." : "Revision saved. New edits are unsaved.");
    } catch (cause) {
      if (cause instanceof ApiError && (cause.status === 409 || cause.status === 412)) setConflict(true);
      setError(cause);
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  }

  function captureInputs(): RunInputs {
    return {
      ...selection,
      policy: portfolioSpec || configured ? undefined : { gap_policy: currentDataset?.metadata.gap_policy ?? "reject" },
    } as const;
  }

  async function submitRevision(revision: Strategy, inputs: RunInputs) {
    const body: RunRequest = {
      strategy_id: revision.id,
      strategy_revision: revision.current_revision,
      ...inputs,
    };
    const version = JSON.stringify(body);
    const now = Date.now();
    const attempts = runAttempts.current;
    pruneAttempts(attempts, now);
    const attempt = attempts.get(version) ?? { key: crypto.randomUUID(), at: now };
    attempts.set(version, attempt);
    storeAttempts(revision.id, attempts);
    try {
      const result = read(await api.POST("/api/v1/backtests", {
        params: { header: { "Idempotency-Key": attempt.key } }, body,
      }));
      attempts.delete(version);
      storeAttempts(revision.id, attempts);
      if (!mounted.current) return;
      setRetryCombined(undefined);
      setSubmitted((items) => [result, ...items.filter((item) => item.id !== result.id)].slice(0, 4));
      if (dockOpen && !dockTabs.current?.contains(document.activeElement)) setDockPanel("Runs");
      setAnnouncement(`Backtest submitted for revision ${result.strategy_revision}. ${runStatus(result)}.`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status < 500 && cause.status !== 429) {
        attempts.delete(version);
        storeAttempts(revision.id, attempts);
      }
      throw cause;
    }
  }

  async function run() {
    if (!ready || (!portfolioSpec && !currentDataset) || submitLock.current || saveLock.current || latestSource.current !== saved.current_source) return;
    const inputs = captureInputs();
    submitLock.current = true;
    setRunning(true);
    setError(undefined);
    try {
      await submitRevision(saved, inputs);
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "E_REVISION_CONFLICT") {
        invalidate();
        try { await reloadSaved(false); } catch { setConflict(true); }
      }
      if (cause instanceof ApiError && cause.code === "E_PRESET_CONFLICT") {
        invalidate();
        presets.reload();
      }
      setError(cause);
    } finally {
      submitLock.current = false;
      setRunning(false);
    }
  }

  async function saveAndRun(retry?: CapturedRun) {
    if (!(retry ? canRetryCombined : canCombine) || submitLock.current || saveLock.current) return;
    const base = savedRecord.current;
    const draft = latestSource.current;
    const inputs = retry?.inputs ?? captureInputs();
    const { policy, ...validationInputs } = inputs;
    const generation = configGeneration.current;
    const origin = document.activeElement;
    let captured = retry;
    saveLock.current = true;
    submitLock.current = true;
    setCombining(true);
    setError(undefined);
    setAnnouncement("");
    try {
      if (!captured) {
        const checked = read(await api.POST("/api/v1/strategies/validate", {
          body: { source: draft, ...validationInputs },
        }));
        const current = generation === configGeneration.current && draft === latestSource.current;
        if (mounted.current && current) setValidation(checked);
        if (!checked.valid || checked.data_compatible !== true) {
          if (mounted.current && current) setDockPanel("Problems");
          if (mounted.current) setError(new ApiError(
            422, "The captured draft did not pass validation.", checked.diagnostics,
          ));
          return;
        }
        let acknowledged = base;
        if (draft !== base.current_source) {
          try {
            acknowledged = await writeRevision(base, draft);
          } catch (cause) {
            if (!(cause instanceof ApiError) || cause.status < 500) throw cause;
            const currentSaved = read(await api.GET("/api/v1/strategies/{ident}", {
              params: { path: { ident: base.id } },
            }));
            if (currentSaved.current_revision !== base.current_revision + 1 ||
                currentSaved.current_source !== draft || currentSaved.source_hash !== checked.source_hash) throw cause;
            acknowledged = currentSaved;
          }
          if (mounted.current) acceptSaved(acknowledged);
        }
        captured = { revision: acknowledged, inputs: { ...validationInputs, policy } };
      }
      await submitRevision(captured.revision, captured.inputs);
    } catch (cause) {
      if (!mounted.current) return;
      const error = cause instanceof ApiError ? cause : undefined;
      const staleStrategy = error && (error.code === "E_REVISION_CONFLICT" || error.status === 412);
      if (staleStrategy) {
        setConflict(true);
        invalidate();
      }
      if (error?.code === "E_PRESET_CONFLICT") {
        invalidate();
        presets.reload();
      }
      setRetryCombined(staleStrategy ? undefined : captured);
      if (captured && !staleStrategy) setAnnouncement(`Revision ${captured.revision.current_revision} saved. Retry the run when ready.`);
      setError(cause);
    } finally {
      saveLock.current = false;
      submitLock.current = false;
      if (mounted.current) {
        setCombining(false);
        if (document.activeElement === document.body || document.activeElement === origin) editor.current?.focus();
      }
    }
  }

  function shortcuts(event: KeyboardEvent<HTMLDivElement>) {
    if (viewingResult || event.nativeEvent.isComposing || event.keyCode === 229 || event.repeat ||
      event.defaultPrevented || document.querySelector("dialog[open], [aria-modal='true']")) return;
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, select, [contenteditable]:not(.cm-content)")) return;
    if (event.metaKey === event.ctrlKey) return;
    if (event.altKey && !event.shiftKey && event.code === "Period") {
      event.preventDefault();
      if (editor.current?.hasFocus) workspace.current?.querySelector<HTMLButtonElement>("#dock-toggle")?.focus();
      else editor.current?.focus();
    } else if (!event.altKey && !event.shiftKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      void save();
    } else if (event.altKey && !event.shiftKey && event.key === "Enter") {
      event.preventDefault();
      void saveAndRun();
    } else if (!event.altKey && event.key === "Enter") {
      event.preventDefault();
      if (event.shiftKey) validate();
      else void run();
    }
  }

  function changeStrategy(id: string) {
    if (id !== saved.id && (persist() || window.confirm("Your draft could not be stored. Leave without saving?"))) {
      router.push(`/strategies/${id}`);
    }
  }

  return <div className="strategy-terminal" ref={workspace} onKeyDownCapture={shortcuts}>
    <nav className="workspace-tabs" aria-label="Strategy views">
      <Link href={sourceUrl} scroll={false} aria-current={!viewingResult ? "page" : undefined}>Source</Link>
      {openRun && <Link href={runUrl(openRun)} scroll={false} aria-current={viewingResult ? "page" : undefined}>Backtest</Link>}
    </nav>
    <div hidden={viewingResult}>
      <div className="editor-chrome editor-top">
        <div className="heading-copy">
          <h1>{saved.name}</h1>
          <p className="muted">Revision {saved.current_revision} · {dirty ? "Unsaved changes" : "Saved"}</p>
          {runHint && <p id="run-hint" className="muted run-blocker">{runHint}</p>}
        </div>
        <div className="actions">
          <button className="text-button" aria-expanded={switchOpen} aria-controls="strategy-switch"
            onClick={() => setSwitchOpen(!switchOpen)}>Switch strategy</button>
          <button className="text-button" aria-expanded={inspectorOpen} aria-controls="editor-inspector"
            onClick={() => setInspectorOpen(!inspectorOpen)}>{inspectorOpen ? "Hide inspector" : "Show inspector"}</button>
          <details className="disclosure shortcut-help">
            <summary>Shortcuts</summary>
            <Details rows={[
              ["Save", "Cmd/Ctrl+S"], ["Validate", "Cmd/Ctrl+Shift+Enter"],
              ["Save and run", "Cmd/Ctrl+Alt+Enter"],
              ["Run backtest", "Cmd/Ctrl+Enter"], ["Source / dock focus", "Cmd/Ctrl+Alt+."],
            ]} />
          </details>
        </div>
      </div>
      <div id="strategy-switch" hidden={!switchOpen} className="actions strategy-switch">
        <label className="inline-field">Strategy
          <select value={saved.id} onChange={(event) => changeStrategy(event.target.value)}>
            {!strategies.data?.items.some((item) => item.id === saved.id) && <option value={saved.id}>{saved.name}</option>}
            {strategies.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <Link href="/strategies">Open Strategies</Link>
        <Notice error={strategies.error} />
        {Boolean(strategies.error) && <button className="button compact" onClick={strategies.reload}>Retry strategies</button>}
      </div>
      <div className="editor-toolbar bar">
        <div className="actions">
          {!portfolioSpec && <label className="inline-field">Dataset
            <select value={datasetId} title={input} onChange={(event) => {
              setDatasetId(event.target.value);
              if (event.target.value === profileId) setProfileId("");
              invalidate();
            }}>
              <option value="">Select a dataset</option>
              {datasetId && !currentDataset && <option value={datasetId}>{datasets.data ? "Dataset unavailable" : "Loading dataset…"}</option>}
              {datasets.data?.items.map((item) => <option key={item.id} value={item.id}>
                {item.filename} · {item.metadata.symbol} · {item.metadata.timeframe}
              </option>)}
            </select>
          </label>}
          {portfolioSpec?.assets.map((name) => {
            const strategy = portfolioBindings[name]?.strategy;
            const value = strategy ? assetStrategyValue(strategy) : "";
            const choices = strategy && !assetStrategies.some((item) => assetStrategyValue(item) === value)
              ? [strategy, ...assetStrategies] : assetStrategies;
            return <fieldset key={name}>
              <legend>{name}</legend>
              <label className="inline-field">Strategy for {name}
                <select value={value} onChange={(event) => {
                  const strategy = choices.find((item) => assetStrategyValue(item) === event.currentTarget.value);
                  setPortfolioBindings({ ...portfolioBindings, [name]: { ...portfolioBindings[name], strategy } });
                  invalidate();
                }}>
                  <option value="">Select a strategy</option>
                  {choices.map((item) => <option key={assetStrategyValue(item)} value={assetStrategyValue(item)}>
                    {item.name} · revision {item.current_revision}
                  </option>)}
                </select>
              </label>
              <label className="inline-field">Dataset for {name}
                <select aria-label={`Dataset for ${name}`} value={portfolioBindings[name]?.dataset_id ?? ""} onChange={(event) => {
                  setPortfolioBindings({ ...portfolioBindings, [name]: { ...portfolioBindings[name], dataset_id: event.currentTarget.value } });
                  invalidate();
                }}>
                  <option value="">Select a dataset</option>
                  {datasets.data?.items.map((item) => <option key={item.id} value={item.id}>
                    {item.filename} · {item.metadata.symbol} · {item.metadata.timeframe}
                  </option>)}
                </select>
              </label>
              <details className="disclosure"><summary>Additional candles for {name}</summary>
                <label className="inline-field">Volume Profile for {name}
                  <select value={portfolioBindings[name]?.profile_dataset_id ?? ""} onChange={(event) => {
                    setPortfolioBindings({ ...portfolioBindings, [name]: { ...portfolioBindings[name], profile_dataset_id: event.currentTarget.value } });
                    invalidate();
                  }}>
                    <option value="">None</option>
                    {datasets.data?.items.map((item) => <option key={item.id} value={item.id}>{item.filename} · {item.metadata.symbol} · {item.metadata.timeframe}</option>)}
                  </select>
                </label>
                <label className="inline-field">Feed name for {name}
                  <input value={portfolioBindings[name]?.feed_name ?? ""} onChange={(event) => {
                    setPortfolioBindings({ ...portfolioBindings, [name]: { ...portfolioBindings[name], feed_name: event.currentTarget.value } });
                    invalidate();
                  }} />
                </label>
                <label className="inline-field">Feed dataset for {name}
                  <select value={portfolioBindings[name]?.feed_dataset_id ?? ""} onChange={(event) => {
                    setPortfolioBindings({ ...portfolioBindings, [name]: { ...portfolioBindings[name], feed_dataset_id: event.currentTarget.value } });
                    invalidate();
                  }}>
                    <option value="">None</option>
                    {datasets.data?.items.map((item) => <option key={item.id} value={item.id}>{item.filename} · {item.metadata.symbol} · {item.metadata.timeframe}</option>)}
                  </select>
                </label>
              </details>
              <details className="disclosure"><summary>Run settings for {name}</summary>
                {(["from_date", "to_date", "fee_bps", "slippage_bps"] as const).map((field) =>
                  <label className="inline-field" key={field}>
                    {({ from_date: "From date", to_date: "To date", fee_bps: "Fee bps", slippage_bps: "Slippage bps" })[field]} for {name}
                    <input type={field.endsWith("date") ? "date" : "number"} step={field.endsWith("date") ? undefined : "any"}
                      value={portfolioBindings[name]?.settings?.[field] ?? ""}
                      onChange={(event) => {
                        const raw = event.currentTarget.value;
                        const next = field.endsWith("date") ? raw || undefined : raw ? Number(raw) : undefined;
                        setPortfolioBindings({ ...portfolioBindings, [name]: {
                          ...portfolioBindings[name],
                          settings: { ...portfolioBindings[name]?.settings, [field]: next },
                        } });
                        invalidate();
                      }} />
                  </label>)}
                <label className="inline-field">Parameter overrides for {name}
                  <input value={portfolioBindings[name]?.parameters_text ?? ""} placeholder={'{"period": 14}'}
                    aria-invalid={assetParameters(portfolioBindings[name]?.parameters_text) === undefined}
                    onChange={(event) => {
                      setPortfolioBindings({ ...portfolioBindings, [name]: {
                        ...portfolioBindings[name], parameters_text: event.currentTarget.value,
                      } });
                      invalidate();
                    }} />
                </label>
                {assetParameters(portfolioBindings[name]?.parameters_text) === undefined &&
                  <p role="alert">Use a JSON object with numeric or Boolean parameter values.</p>}
              </details>
            </fieldset>;
          })}
          {needsProfile && <label className="inline-field">Volume Profile dataset
            <select value={profileId} onChange={(event) => { setProfileId(event.target.value); invalidate(); }}>
              <option value="">Select lower-timeframe candles</option>
              {datasets.data?.items.filter((item) => item.id !== datasetId).map((item) =>
                <option key={item.id} value={item.id}>{item.filename} · {item.metadata.timeframe}</option>)}
            </select>
          </label>}
          {requiredFeeds.map((name) => <label className="inline-field" key={name}>Feed {name}
            <select value={Object.hasOwn(feedIds, name) ? feedIds[name] : ""} onChange={(event) => {
              setFeedIds({ ...feedIds, [name]: event.currentTarget.value });
              invalidate();
            }}>
              <option value="">Select higher-timeframe candles</option>
              {datasets.data?.items.filter((item) => item.id !== datasetId).map((item) =>
                <option key={item.id} value={item.id}>{item.filename} · {item.metadata.timeframe}</option>)}
            </select>
          </label>)}
          <details className="disclosure input-menu">
            <summary>Data</summary>
            <div className="input-popover">
              {currentDataset && <p className="dataset-context">{currentDataset.filename} · {currentDataset.metadata.symbol} · {currentDataset.metadata.timeframe}</p>}
              {currentProfile && needsProfile && <p>Volume Profile · {currentProfile.filename}</p>}
              <Link href={`/datasets?strategy=${saved.id}`}>Browse datasets</Link>
            </div>
          </details>
        </div>
        <div className="actions">
          <button className="button" onClick={save} disabled={!dirty || saving || Boolean(recovered) || conflict}
            aria-keyshortcuts="Meta+S Control+S">{saving ? "Saving…" : "Save"}</button>
          <button className="button" onClick={validate} disabled={validating || Boolean(recovered)}
            aria-keyshortcuts="Meta+Shift+Enter Control+Shift+Enter">Validate</button>
          <button className="button"
            onClick={() => { setInspectPanel("Assumptions"); setInspectorOpen(true); }}>
            Run settings
          </button>
          <button className="button primary" disabled={!ready && !running} aria-disabled={!ready} onClick={run}
            aria-keyshortcuts="Meta+Enter Control+Enter" aria-describedby={runHint ? "run-hint" : undefined}>
            {running ? "Submitting…" : "Run backtest"}
          </button>
          {(dirty || (combining && !retryCombined)) && <button className="button primary"
            disabled={!canCombine && !combining} aria-disabled={!canCombine}
            aria-keyshortcuts="Meta+Alt+Enter Control+Alt+Enter" onClick={() => void saveAndRun()}>
            {combining ? "Saving and running…" : "Save and run"}
          </button>}
          {retryCombined && <button className="button"
            disabled={!canRetryCombined && !combining} aria-disabled={!canRetryCombined}
            onClick={() => void saveAndRun(retryCombined)}>
            Retry captured run
          </button>}
        </div>
      </div>
      <div className={inspectorOpen ? "editor-grid" : "editor-grid inspector-hidden"}>
        <section className="source-pane" aria-label="Strategy source">
          <div inert={Boolean(recovered)}>
            <CodeEditor source={source} diagnostics={diagnostics} editor={editor} onEdit={edit}
              draft={syntaxResult ? { source, records: syntaxResult.records } : undefined} />
          </div>
        </section>
        <section className="dock" aria-label="Editor dock" ref={dockTabs}>
          <div className="dock-strip">
            {dockOpen ? <PaneTabs id="dock" label="Editor dock" names={["Problems", "Runs"] as const}
              selected={dockPanel} select={setDockPanel}
              text={(name) => name === "Problems" && (errorCount > 0 || warningCount > 0) ? `Problems · ${errorCount + warningCount}` : name} /> :
              <button className="text-button" onClick={() => { setDockPanel("Problems"); setDockOpen(true); }}>
                Problems · {errorCount} errors, {warningCount} warnings
              </button>}
            {submitted[0] && (!dockOpen || dockPanel !== "Runs") &&
              <DockRun status={latestRun} seed={submitted[0]} href={runUrl(submitted[0].id)} compact />}
            <div className="sr-only" role="status">
              {submitted[0] && latestRun.run && runStatus(latestRun.run) !== runStatus(submitted[0]) &&
                `Revision ${latestRun.run.strategy_revision} backtest. ${runStatus(latestRun.run)}.`}
            </div>
            <button className="text-button" id="dock-toggle" aria-expanded={dockOpen} aria-controls="dock-panel"
              aria-keyshortcuts="Meta+Alt+. Control+Alt+." onClick={() => setDockOpen(!dockOpen)}>
              {dockOpen ? "Hide dock" : "Show dock"}
            </button>
          </div>
          <div className="dock-content" id="dock-panel" role="tabpanel" aria-labelledby={dockOpen ? `dock-${dockPanel}` : undefined} tabIndex={0} hidden={!dockOpen}>
            {dockPanel === "Problems" ? <>
              <div className="bar">
                <p className="muted">{errorCount} {errorCount === 1 ? "error" : "errors"} · {warningCount} {warningCount === 1 ? "warning" : "warnings"}</p>
                {(validation || explanation) && <p className="muted dataset-context">{validation ? "Validated" : "Explained"} with {input}</p>}
              </div>
              {!validation && !explanation && <p className="muted">Validate to check the strategy and selected data.</p>}
              {diagnostics.length > 0 && <ul className="diagnostics">{diagnostics.map((item, index) => {
                const fix = draftFixes.find((candidate) => candidate.code === item.code &&
                  candidate.span?.start_byte === item.span?.start_byte &&
                  candidate.span?.end_byte === item.span?.end_byte &&
                  typeof candidate.details.replacement === "string");
                return <li key={index}>
                {item.span ? <button className="text-button" onClick={() => focusDiagnostic(editor.current, source, item)}>
                  Line {item.span.start_line} · {item.message}
                </button> : <p>{item.data_row != null && `Row ${item.data_row} · `}{item.message}</p>}
                <small>{item.severity} · {item.code}</small>
                {item.suggestion && <p>{item.suggestion}</p>}
                {fix && <button className="button compact" onClick={() => fixDiagnostic(fix)}>
                  Apply fix to line {fix.span?.start_line}
                </button>}
              </li>;
              })}</ul>}
            </> : dockOpen && submitted.length ? <div>
              <DockRun status={latestRun} seed={submitted[0]} href={runUrl(submitted[0].id)} />
              {submitted.slice(1).map((item) => <TrackedDockRun key={item.id} seed={item} href={runUrl(item.id)} />)}
            </div> :
              <p className="muted">Backtests submitted from this editor appear here.</p>}
          </div>
        </section>
        <aside className="inspector editor-inspector" id="editor-inspector" aria-label="Strategy inspection" hidden={!inspectorOpen}>
          <PaneTabs id="inspection" label="Strategy inspection" names={["Explain", "Assumptions"] as const}
            selected={inspectPanel} select={setInspectPanel} />
          <div className="tab-content" role="tabpanel" id="inspection-panel" aria-labelledby={`inspection-${inspectPanel}`} tabIndex={0}>
            {inspectPanel === "Explain" ? <>
              <button className="button compact" disabled={explaining || Boolean(recovered)}
                onClick={() => void inspect("explain")}>Explain strategy</button>
              {explanation?.text ? <ExplainSections text={explanation.text} dataset={input} /> :
                <p className="muted">{explanation ? "Open Problems to review errors." : "Explain the entry, exit, and execution rules."}</p>}
            </> : <>
              <fieldset className="strategy-parameters">
                <legend>Run settings</legend>
                <label>Run preset
                  <select value={preset?.id ?? ""} onChange={(event) =>
                    choosePreset(presets.data?.items.find((item) => item.id === event.currentTarget.value))}>
                    <option value="">Source defaults</option>
                    {preset && !presets.data?.items.some((item) => item.id === preset.id) &&
                      <option value={preset.id}>{preset.name}</option>}
                    {presets.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
                {presets.error != null && <Notice error={presets.error} />}
                {preset && presets.data?.items.some((item) => item.id === preset.id && item.revision !== preset.revision) &&
                  <button className="button compact" onClick={() =>
                    choosePreset(presets.data?.items.find((item) => item.id === preset.id))}>Load latest preset revision</button>}
                {(["from_date", "to_date"] as const).map((field) => <label key={field}>
                  {field === "from_date" ? "From date (UTC)" : "To date (UTC)"}
                  <input type="date" value={settings[field] ?? ""} onChange={(event) =>
                    changeSetting(field, event.currentTarget.value || undefined)} />
                  <small className="muted">Default {preset?.settings[field] ?? sourceConfig?.[field] ?? "from strategy"}</small>
                </label>)}
                {([["capital", "Starting capital"], ["fee_bps", "Fee (bps per side)"],
                  ["slippage_bps", "Slippage (bps per side)"]] as const).map(([field, label]) => <label key={field}>
                    {label}
                    <input type="number" step="any" value={settings[field] ?? ""} placeholder={String(preset?.settings[field] ??
                      (field === "capital" ? sourceConfig?.capital : sourceConfig &&
                        (field === "fee_bps" ? sourceConfig.fee_rate : sourceConfig.slippage_rate) * 10000) ?? "")}
                      onChange={(event) => {
                        const value = event.currentTarget.valueAsNumber;
                        changeSetting(field, Number.isFinite(value) ? value : undefined);
                      }} />
                  </label>)}
                <label>Run gap policy
                  <select value={settings.gap_policy ?? ""} onChange={(event) => {
                    const policy = event.currentTarget.value;
                    changeSetting("gap_policy", policy === "allow" || policy === "reject" ? policy : undefined);
                  }}>
                    <option value="">Default ({preset?.settings.gap_policy ?? currentDataset?.metadata.gap_policy ?? "from dataset"})</option>
                    <option value="reject">Reject gaps</option>
                    <option value="allow">Allow gaps</option>
                  </select>
                </label>
                <label>Preset name
                  <input maxLength={120} value={presetName} onChange={(event) => {
                    configGeneration.current++;
                    setPresetName(event.currentTarget.value);
                  }} />
                </label>
                <div className="actions">
                  <button className="button compact" disabled={!presetName.trim() || presetBusy}
                    onClick={() => void savePreset(false)}>Save as preset</button>
                  {preset && <button className="button compact" disabled={!presetName.trim() || presetBusy}
                    onClick={() => void savePreset(true)}>Update preset</button>}
                </div>
              </fieldset>
              {definitions.length > 0 && <fieldset className="strategy-parameters">
                <legend>Run parameter overrides</legend>
                {definitions.map((parameter) => {
                  const override = Object.hasOwn(parameterOverrides, parameter.name)
                    ? parameterOverrides[parameter.name] : undefined;
                  const fallback = preset?.settings.parameters && Object.hasOwn(preset.settings.parameters, parameter.name)
                    ? preset.settings.parameters[parameter.name] : parameter.default;
                  return <label key={parameter.name}>
                    <span>{parameter.name}</span>
                    {parameter.kind === "bool" ? <select value={override === undefined ? "" : String(override)} onChange={(event) =>
                      changeParameter(parameter.name, event.currentTarget.value === "" ? undefined : event.currentTarget.value === "true")
                    }>
                      <option value="">Default ({String(fallback)})</option>
                      <option value="true">True</option>
                      <option value="false">False</option>
                    </select> : <input type="number" step={parameter.kind === "count" ? 1 : "any"}
                      value={typeof override === "number" ? override : ""}
                      placeholder={String(fallback)} onChange={(event) => {
                        const value = event.currentTarget.valueAsNumber;
                        changeParameter(parameter.name, Number.isFinite(value) ? value : undefined);
                      }} />}
                    {parameter.kind !== "bool" && <small className="muted">
                      {parameter.kind} · default {String(fallback)}
                      {parameter.minimum != null && parameter.maximum != null &&
                        ` · ${parameter.minimum} to ${parameter.maximum}`}
                    </small>}
                  </label>;
                })}
              </fieldset>}
              <Details rows={[
              ["Revision", saved.current_revision],
              ["Resolved with", currentWindow && input],
              ["Dataset fingerprint", currentDataset?.dataset_hash],
              ["Gap policy", currentDataset?.metadata.gap_policy],
              ["Starting capital", effective?.capital ?? validatedStrategy?.backtest.capital ?? portfolioSpec?.capital],
              ["Asset priority", portfolioSpec?.assets.join(", ")],
              ["Fee per side (bps)", resolvedCosts && resolvedCosts.fee_rate * 10000],
              ["Slippage per side (bps)", resolvedCosts && resolvedCosts.slippage_rate * 10000],
              ...(effective ? [
                ["Resolved dates (UTC)", `${effective.from_date} to ${effective.to_date}`],
                ...Object.entries(effective.parameters).map(([name, value]): [string, string] =>
                  [`Parameter ${name}`, String(value)]),
              ] as [string, string][] : []),
              ["First open", <Time key="first" value={currentWindow?.first_open} />],
              ["Last close", <Time key="last" value={currentWindow?.last_close_at} />],
              ["First executable open", <Time key="execute" value={currentWindow?.first_execution_at} />],
              ["Structural warmup index", validation?.warmup_index ?? explanation?.warmup_index],
              ...(workload ? [
                ["Evaluated candles", integer.format(workload.evaluated_rows)],
                ["Retained series estimate", integer.format(workload.retained_series)],
                ["Minimum resident storage", memory(workload.minimum_resident_bytes)],
                ["Worker memory budget", memory(workload.memory_limit_bytes)],
                ["Largest estimated allocation", workload.dominant_component],
                ["Largest expression by series", workload.dominant_expression ?? "None"],
              ] as [string, string][] : []),
              ["Final holdings", "Marked at final close"],
            ]} />
            </>}
          </div>
        </aside>
      </div>
      <div className="editor-notices">
        <p role="status" className={validating || explaining || announcement ? "muted" : "sr-only"}>
          {validating ? `Validating with ${input}…` : explaining ? `Explaining with ${input}…` : announcement}
        </p>
        <Notice error={datasets.error} />
        {Boolean(datasets.error) && <button className="button compact" onClick={datasets.reload}>Retry datasets</button>}
        <Notice error={error} />
        {cacheError && <p role="alert">This tab could not store your draft. Save or copy the source before leaving.</p>}
        {recovered && <div className="notice" role="region" aria-label="Recovered draft">
          <h2>Recovered draft</h2>
          <p>{changedBase ? `The saved revision changed since this draft was cached from revision ${recovered.revision}.` :
            `This tab has unsaved source based on revision ${recovered.revision}.`}</p>
          {changedBase && <details className="disclosure"><summary>Review recovered source</summary>
            <pre className="conflict-source">{recovered.source}</pre>
          </details>}
          <div className="actions">
            <button className="button" onClick={() => resolveDraft(true)}>{changedBase ? "Use recovered draft" : "Restore draft"}</button>
            <button className="button" onClick={() => resolveDraft(false)}>Discard draft</button>
            {changedBase && <CopySource source={recovered.source} label="Copy recovered source" onCopied={setAnnouncement} onError={setError} />}
          </div>
        </div>}
        {conflict && <div className="actions section-heading">
          <button className="button" onClick={() => {
            setError(undefined);
            void reloadSaved(false).catch(setError);
          }}>Keep local source and load latest revision</button>
          <button className="button" onClick={() => {
            if (window.confirm("Reload the server version and discard local source?")) {
              setError(undefined);
              void reloadSaved(true).catch(setError);
            }
          }}>Reload server version</button>
          <CopySource source={source} label="Copy local source" onCopied={setAnnouncement} onError={setError} />
        </div>}
      </div>
    </div>
    {viewingResult && !runId && <div className="route-fallback"><h1>Run link is invalid</h1>
      <Link href={sourceUrl} scroll={false}>Return to source</Link></div>}
    {openRun && <div hidden={!viewingResult}>
      <RunDetail key={openRun} id={openRun} strategyId={saved.id} active={viewingResult} sourceUrl={sourceUrl} />
    </div>}
  </div>;
}

function CopySource({ source, label, onCopied, onError }: {
  source: string; label: string; onCopied: (text: string) => void; onError: (error: unknown) => void;
}) {
  return <button className="button" onClick={async () => {
    try { await navigator.clipboard.writeText(source); onCopied("Source copied."); }
    catch (error) { onError(error); }
  }}>{label}</button>;
}

function PaneTabs<T extends string>({ id, label, names, selected, select, text }: {
  id: string; label: string; names: readonly T[]; selected: T; select: (name: T) => void; text?: (name: T) => ReactNode;
}) {
  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    const index = names.indexOf(selected);
    const next = event.key === "ArrowRight" ? (index + 1) % names.length :
      event.key === "ArrowLeft" ? (index + names.length - 1) % names.length :
        event.key === "Home" ? 0 : event.key === "End" ? names.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    select(names[next]);
    event.currentTarget.querySelectorAll("button")[next].focus();
  }
  return <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKey}>
    {names.map((name) => <button key={name} id={`${id}-${name}`} role="tab" aria-selected={selected === name}
      aria-controls={`${id}-panel`} tabIndex={selected === name ? 0 : -1} onClick={() => select(name)}>
      {text ? text(name) : name}
    </button>)}
  </div>;
}

function TrackedDockRun({ seed, href }: { seed: Run; href: string }) {
  const status = useRunStatus(seed.id, seed);
  return <DockRun seed={seed} href={href} status={status} />;
}

function DockRun({ status, seed, href, compact = false }: {
  status: ReturnType<typeof useRunStatus>; seed: Run; href: string; compact?: boolean;
}) {
  const run = status.run ?? seed;
  return <div className={compact ? "actions" : "run-item bar"}>
    <div>
      <strong>{status.cancelling ? "Requesting cancellation…" : runStatus(run)}</strong>
      {!compact && <p className="muted">Revision {run.strategy_revision} · {run.dataset_name} · <Time value={run.created_at} /></p>}
      {!compact && run.status === "running" && run.progress.total_bars > 0 &&
        <p>{run.progress.completed_bars} of {run.progress.total_bars} candles processed</p>}
      {!compact && run.error && <p>{run.error.message}</p>}
    </div>
    <div className="actions">
      <Link href={href} scroll={false} aria-label={compact ? "Open run" : `Open run · revision ${run.strategy_revision} · ${run.id.slice(0, 8)}`}>Open run</Link>
      {!compact && isActive(run) && <button className="button compact" onClick={status.cancel}
        disabled={status.cancelling || run.cancel_requested}>Cancel run</button>}
      {Boolean(status.error) && <><span className="muted">Status may be stale</span>
        <button className="text-button" onClick={status.retry}>Retry status</button></>}
    </div>
    {!compact && <Notice error={status.error} />}
  </div>;
}

function ExplainSections({ text, dataset }: { text: string; dataset?: string }) {
  const sections = [
    { title: "Entry", lines: [] as string[] },
    { title: "Exit", lines: [] as string[] },
    { title: "Execution", lines: [] as string[] },
  ];
  const other: string[] = [];
  for (const line of text.split("\n")) {
    if (line.startsWith("At close, enter") || line.startsWith("At next open, allocate")) {
      sections[0].lines.push(line);
    } else if (line.startsWith("Exit all")) {
      sections[1].lines.push(line);
    } else if (line.startsWith("Warmup index") || line.startsWith("Fee ")) {
      sections[2].lines.push(line);
    } else {
      other.push(line);
    }
  }
  if (sections.every((section) => section.lines.length === 0)) return <div className="explanation">
    {other.map((line, index) => <p key={index}>{line}</p>)}
  </div>;
  return <div className="explanation">
    {dataset && <p className="muted section-heading">Explained with {dataset}</p>}
    {sections.map((section) => section.lines.length > 0 && <section className="explain-section" key={section.title}>
      <h3>{section.title}</h3>
      {section.lines.map((line, index) => <p key={index}>{line}</p>)}
    </section>)}
    {other.length > 0 && <details className="disclosure">
      <summary>Source and dataset details</summary>
      {other.map((line, index) => <p key={index}>{line}</p>)}
    </details>}
  </div>;
}
