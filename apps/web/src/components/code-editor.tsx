"use client";

import { autocompletion, type CompletionContext } from "@codemirror/autocomplete";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { setDiagnostics } from "@codemirror/lint";
import { Annotation, EditorState } from "@codemirror/state";
import { EditorView, hoverTooltip } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { basicSetup } from "codemirror";
import { useEffect, useRef, useState, type RefObject } from "react";
import type { Diagnostic, DraftCheck } from "@/lib/api";
import catalog from "@/lib/catalog.json";

const fields = ["open", "high", "low", "close", "volume"];
const units = ["price", "volume", "money", "count"];
const keywords = new Set(catalog.keywords);
const shortKeywords = ["short", "cover", "initial", "margin", "maintenance", "borrow", "day"];
const functions = new Map(catalog.functions.map((fn) => [fn.name, fn]));
const selectors = [...new Set(catalog.functions.flatMap((fn) => fn.fields))];
type DraftRecords = { source: string; records: DraftCheck["records"] };
const sourceFix = Annotation.define<boolean>();

export const usesDsl2 = (source: string) =>
  /^[\s\uFEFF]*tradelang\s+[2345678]\b/.test(source.replace(/#[^\r\n]*/g, ""));

const language = StreamLanguage.define({
  name: "TradeLang",
  token(stream) {
    if (stream.eatSpace()) return null;
    if (stream.match(/^#.*/)) return "comment";
    if (stream.match(/^"(?:[^"\\]|\\.)*"?/)) return "string";
    if (stream.match(/^\d{4}-\d{2}-\d{2}|^\d+[mhd]\b|^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?/)) return "number";
    if (stream.match(/^[a-z_][a-z_0-9]*/i)) {
      const word = stream.current();
      if (functions.has(word)) return "variableName.function";
      if (fields.includes(word) || selectors.includes(word)) return "property";
      if (keywords.has(word) || units.includes(word) || shortKeywords.includes(word)) return "keyword";
      return "variableName";
    }
    if (stream.match(/^[+*/^%<>=!-]+/)) return "operator";
    stream.next();
    return null;
  },
});

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--syntax-keyword)" },
  { tag: tags.function(tags.variableName), color: "var(--syntax-function)" },
  { tag: tags.propertyName, color: "var(--syntax-property)" },
  { tag: tags.number, color: "var(--syntax-number)" },
  { tag: tags.string, color: "var(--syntax-string)" },
  { tag: tags.comment, color: "var(--syntax-comment)", fontStyle: "italic" },
  { tag: tags.operator, color: "var(--syntax-keyword)" },
]);

const theme = EditorView.theme({
  "&": { color: "var(--ink)", backgroundColor: "var(--canvas)" },
  ".cm-content": { padding: "6px 0", fontFamily: "var(--mono)", lineHeight: "1.6" },
  ".cm-line": { padding: "0 13px" },
  ".cm-gutters": { background: "var(--inspector)", border: "0", color: "var(--muted)" },
  ".cm-lineNumbers .cm-gutterElement": { paddingInline: "11px" },
  ".cm-activeLine": { background: "var(--inspector)" },
  ".cm-activeLineGutter": { background: "var(--selected)" },
  ".cm-scroller": { overflow: "auto" },
});

function tokens(source: string) {
  return [...source.matchAll(/#[^\n]*|"(?:\\.|[^"\\])*"?|[a-z_][a-z_0-9]*|\d+(?:\.\d+)?|[^\s]/gi)]
    .map((match) => match[0]).filter((token) => !token.startsWith("#"));
}

function recordFields(prefix: string, draft?: DraftRecords): [string, string | null][] {
  const terms = tokens(prefix);
  if (terms.pop() !== ".") return [];
  let end = terms.length - 1;
  while (terms[end] === ")") {
    let depth = 1;
    let start = end - 1;
    for (; start >= 0; start--) {
      if (terms[start] === ")") depth++;
      if (terms[start] === "(" && --depth === 0) break;
    }
    if (start < 0) return [];
    const indicator = functions.get(terms[start - 1]);
    if (indicator) {
      const scales: Partial<Record<string, string>> = indicator.field_scales;
      return indicator.fields.map((name) => [name, scales[name] ?? null]);
    }
    terms.splice(start, 1);
    end--;
    end--;
  }
  const name = terms[end];
  const record = draft?.records.find((item) => item.name === name);
  if (!record || !draft) return [];
  const endOfDeclaration = position(draft.source, record.span.end_byte);
  const originalPrefix = draft.source.replace(/\r\n?|\n/g, "\n").slice(0, endOfDeclaration);
  return prefix.length > endOfDeclaration && prefix.startsWith(originalPrefix)
    ? Object.entries(record.fields) : [];
}

function activeCall(source: string) {
  const stack: { token: string; name?: string; argument: number }[] = [];
  let previous = "";
  for (const token of tokens(source)) {
    if (token === "(" || token === "[") {
      stack.push({ token, name: token === "(" ? previous : undefined, argument: 0 });
    } else if (token === ")" || token === "]") {
      const expected = token === ")" ? "(" : "[";
      if (stack.at(-1)?.token === expected) stack.pop();
    } else if (token === "," && stack.length) {
      stack[stack.length - 1].argument++;
    }
    previous = token;
  }
  return stack.findLast((frame) => frame.name && functions.has(frame.name));
}

function signatureHelp(prefix: string) {
  const call = activeCall(prefix);
  const functionName = call?.name;
  const fn = functionName && functions.get(functionName);
  if (!call || !fn) return [];
  return fn.signatures.filter((form) => form.arguments.length > call.argument).map((form) => {
    const selected = form.arguments[call.argument];
    return {
      label: `${fn.name}(${form.arguments.map((argument) => argument.name).join(", ")})`,
      detail: [
        `${selected.name} · ${selected.constraint}`, form.default, form.relationship, fn.scale,
      ].filter(Boolean).join(" · "),
    };
  });
}

function complete(context: CompletionContext, draft?: DraftRecords) {
  const word = context.matchBefore(/[\w]*/);
  if (!word || (!context.explicit && word.from === word.to && context.state.sliceDoc(word.from - 1, word.from) !== ".")) {
    return null;
  }
  const prefix = context.state.sliceDoc(0, word.from);
  const version2 = usesDsl2(prefix);
  const directive = prefix.replace(/#[^\r\n]*/g, "");
  const version3 = /^[\s\uFEFF]*tradelang\s+[345678]\b/.test(directive);
  const version4 = /^[\s\uFEFF]*tradelang\s+[45678]\b/.test(directive);
  const version5 = /^[\s\uFEFF]*tradelang\s+[5678]\b/.test(directive);
  const version6 = /^[\s\uFEFF]*tradelang\s+[678]\b/.test(directive);
  if (prefix.endsWith(".")) {
    const available = recordFields(prefix, draft);
    return available.length ? {
      from: word.from,
      options: available.map(([label, scale]) => ({ label, type: "property", detail: scale ?? undefined })),
    } : null;
  }
  const names = Array.from(prefix.matchAll(/^\s*(?:let|param)\s+([a-z_][a-z_0-9]*)\s*[:=]/gm), (match) => match[1]);
  return {
    from: word.from,
    options: [
      ...names.map((label) => ({ label, type: "variable" })),
      ...catalog.functions.map((fn) => ({
        label: fn.name, type: "function",
        detail: fn.signatures.map((form) => `(${form.arguments.map((argument) => argument.name).join(", ")})`).join(" | ") +
          (fn.scale ? ` · ${fn.scale}` : ""),
      })),
      ...(version2 ? Object.entries(catalog.choice_functions).map(([label, detail]) => ({
        label, detail, type: "function",
      })) : []),
      ...fields.map((label) => ({ label, type: "property" })),
      ...[...new Set([...catalog.keywords, ...units])].filter((label) => !fields.includes(label))
        .map((label) => ({ label, type: "keyword" })),
      ...(version2 ? [...catalog.version2_keywords, "ratio", "bool"].map((label) =>
        ({ label, type: "keyword" })) : []),
      ...(version3 ? [
        { label: "feed", type: "keyword" }, { label: "max_age", type: "keyword" },
        { label: "on", detail: "(feed, expression)", type: "function" },
        { label: "align", detail: "(secondary_series)", type: "function" },
      ] : []),
      ...(version4 ? [
        { label: "risking", detail: "fraction of equity at the modeled stop", type: "keyword" },
        { label: "allocation", detail: "max allocation fraction of equity", type: "keyword" },
      ] : []),
      ...(version5 ? [
        { label: "rule", detail: "named exit in source order", type: "keyword" },
        { label: "after", detail: "completed holding candles", type: "keyword" },
        { label: "bars", type: "keyword" },
        { label: "trailing", detail: "tighten at the next observed open", type: "keyword" },
        { label: "expire", detail: "maximum signal order age", type: "keyword" },
      ] : []),
      ...(/^[\s\uFEFF]*tradelang\s+[78]\b/.test(directive) ? [
        { label: "session", detail: "use the recorded exchange-session calendar", type: "keyword" },
      ] : []),
      ...(version6 ? [
        { label: "position", detail: "close a fraction of position", type: "keyword" },
        { label: "units", detail: "base-unit quantity", type: "keyword" },
        { label: "scale", detail: "add to a held position", type: "keyword" },
        { label: "add", detail: "using money or a fraction of cash", type: "keyword" },
        { label: "cash", type: "keyword" },
        { label: "quantity", detail: "quantity step in units", type: "keyword" },
      ] : []),
      ...(/^[\s\uFEFF]*tradelang\s+8\b/.test(directive) ?
        shortKeywords.map((label) => ({ label, type: "keyword" })) : []),
    ],
  };
}

function position(source: string, bytes: number) {
  const buffer = new TextEncoder().encode(source);
  return new TextDecoder("utf-8", { ignoreBOM: true }).decode(buffer.subarray(0, bytes))
    .replace(/\r\n?|\n/g, "\n").length;
}

export function focusDiagnostic(view: EditorView | null, source: string, diagnostic: Diagnostic) {
  if (!view || !diagnostic.span) return;
  const from = position(source, diagnostic.span.start_byte);
  const to = position(source, diagnostic.span.end_byte);
  view.dispatch({ selection: { anchor: from, head: to }, scrollIntoView: true });
  view.focus();
}

export function applyDiagnosticFix(view: EditorView | null, source: string, diagnostic: Diagnostic) {
  const { span, details } = diagnostic;
  if (!view || !span || typeof details.original !== "string" || typeof details.replacement !== "string") return;
  const bytes = new TextEncoder().encode(source);
  const decode = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
  const { start_byte: start, end_byte: end } = span;
  if (start < 0 || end > bytes.length || start >= end ||
      view.state.doc.toString() !== source.replace(/\r\n?|\n/g, "\n")) return;
  if (decode.decode(bytes.subarray(start, end)) !== details.original) return;
  const from = position(source, start);
  const to = position(source, end);
  view.dispatch({
    changes: { from, to, insert: details.replacement },
    selection: { anchor: from + details.replacement.length },
    annotations: sourceFix.of(true),
    scrollIntoView: true,
  });
  view.focus();
  return decode.decode(bytes.subarray(0, start)) + details.replacement + decode.decode(bytes.subarray(end));
}

export function CodeEditor({
  source, onEdit, diagnostics, editor, readOnly = false, draft,
}: {
  source: string; onEdit: (source: string) => void; diagnostics: Diagnostic[];
  editor: RefObject<EditorView | null>; readOnly?: boolean; draft?: DraftRecords;
}) {
  const parent = useRef<HTMLDivElement>(null);
  const initial = useRef(source);
  const onChange = useRef(onEdit);
  onChange.current = onEdit;
  const compiled = useRef<DraftRecords>(undefined);
  if (draft) compiled.current = draft;
  const [hints, setHints] = useState<ReturnType<typeof signatureHelp>>([]);
  useEffect(() => {
    const normalized = initial.current.replace(/\r\n?|\n/g, "\n");
    const view = new EditorView({
      parent: parent.current!,
      state: EditorState.create({
        doc: normalized,
        extensions: [
          basicSetup, language, syntaxHighlighting(highlight), theme, EditorView.lineWrapping,
          autocompletion({ override: [(context) => complete(context, compiled.current)] }),
          hoverTooltip((view, pos) => {
            const word = view.state.wordAt(pos);
            if (!word) return null;
            const label = view.state.sliceDoc(word.from, word.to);
            const scale = functions.get(label)?.scale ??
              recordFields(view.state.sliceDoc(0, word.from), compiled.current).find(([field]) => field === label)?.[1];
            if (!scale) return null;
            return {
              pos: word.from, end: word.to, above: true,
              create() {
                const dom = document.createElement("div");
                dom.className = "editor-hint";
                dom.textContent = scale === "points" ? "Measured in points. Use 30 for thirty points." :
                  scale === "fraction" ? "Measured as a fraction. 30% represents 0.3." : "Percentage literal scale.";
                return { dom };
              },
            };
          }),
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({
            "aria-label": "Strategy source",
            ...(readOnly ? { tabindex: "0", "aria-readonly": "true" } : {}),
          }),
          EditorView.theme({
            "& .cm-selectionBackground, &.cm-focused .cm-selectionBackground": { backgroundColor: "var(--selected)" },
            "& .cm-cursor": { borderLeftColor: "var(--ink)" },
          }),
          EditorView.updateListener.of((update) => {
            if (!readOnly && (update.docChanged || update.selectionSet || update.focusChanged)) {
              const prefix = update.state.sliceDoc(0, update.state.selection.main.head);
              setHints(update.view.hasFocus && prefix.length <= 65_536 ? signatureHelp(prefix) : []);
            }
            if (update.docChanged && !update.transactions.some((transaction) => transaction.annotation(sourceFix))) {
              const edited = update.state.doc.toString();
              onChange.current(edited === normalized ? initial.current : edited);
            }
          }),
        ],
      }),
    });
    editor.current = view;
    return () => {
      editor.current = null;
      view.destroy();
    };
  }, [editor, readOnly]);

  useEffect(() => {
    const view = editor.current;
    if (!view) return;
    view.dispatch(setDiagnostics(view.state, diagnostics.flatMap((item) => item.span ? [{
      from: position(source, item.span.start_byte),
      to: position(source, item.span.end_byte),
      severity: item.severity,
      message: item.message,
    }] : [])));
  }, [source, diagnostics, editor]);

  return <>
    <div ref={parent} />
    {hints.length > 0 && <div className="editor-hint" role="note" aria-label="Function signature">
      {hints.map((hint) => <div key={hint.label}><code>{hint.label}</code> {hint.detail}</div>)}
    </div>}
  </>;
}
