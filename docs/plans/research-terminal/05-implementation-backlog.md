# Implementation backlog

Use this table to sequence changes in the existing TradeLang repository. Sizes are relative to frontend work. Build in small slices and ship all redesigned screens behind one release gate. Keep the working tree's in-progress browser features intact and recheck the baseline before editing shared files. [Confirmed decisions](README.md#confirmed-decisions) · [Frontend architecture](03-frontend-architecture.md)

| ID | Deliverable | Depends on | Size | Ready to merge when |
| --- | --- | --- | --- | --- |
| T00 | Record the current layout for each existing screen. Capture the editor, run, and compare at target viewports using the same fixtures that will be used for review. | Current browser build and fixtures | S | Baseline records layout positions and route behavior for the edit-to-run loop and includes reference captures for all major screens. |
| T01 | Compact shell, navigation rail, theme tokens, and responsive pane primitives. Apply shared tokens to native controls, CodeMirror, and chart styling as each slice adopts the shell. | T00 | M | All current routes open. `/` lands on Strategies. Controls fit at laptop width, reflow at narrow width, and pass keyboard and contrast checks. Graphite is the fresh-profile default, and light mode and pane preferences survive reload. |
| T02 | Strategy workspace toolbar, Problems dock, and Explain and Assumptions inspector. Add scoped editor commands and draft recovery according to the decision register. | T01 | L | Invalid source can still be saved. Clicking a diagnostic focuses the exact span, and stale inspection cannot make Run available. Draft recovery and conflict behavior pass the acceptance cases. |
| T03 | Run dock, shared submission and status, and the in-workspace result tab. Preserve direct run and executed-revision links. | T02 | L | An acknowledged run appears in the dock while the editor stays active. Opening and closing results preserves editor selection and undo. Refresh, direct links, retries, cancellation, and interruption work. |
| T04 | Dense run overview, synchronized charts and ledger, and selected-trade inspector. Keep the standalone and workspace result views on the same components. | T03 | M | Desktop fit and narrow layout pass. Chart values, source snapshot, fills, events, selected row, and exports match the known fixture and existing contract. |
| T05 | Bring Strategies, saved revisions, Datasets, and Runs into the terminal layout. Compact tables, filters, import, and selection details. | T01 | M | Strategy create, duplicate, archive, read-only revision, dataset import and selection, and run history filtering work from their normal entries. Keyboard navigation and wide table overflow remain usable. |
| T06 | Bring Compare into the terminal layout. Add the baseline selector, signed deltas, and data and window differences before plots. | T01, T04, T05 | L | Two-to-four-run comparison handles exact match, intersection, and unavailable overlay. Pin links and fallback work. Metric deltas follow the unit, eligibility, and missing-value rules in the interaction spec. |
| T07 | Full release verification and browser guide update. | T02–T06 | M | The build and test checks pass. A fresh library completes the full workflow through Compare with a pinned baseline. An existing library opens historical runs. Screenshots and state checks cover all redesigned screens, both themes, and target viewports. |
| T08 | Plan the Price & Signals follow-up against the existing approved design. | Bounded run-scoped candle and indicator contract | Separate estimate | The contract covers exact run inputs, indicator readiness, timestamp and fill precision, gap behavior, and bounded ranges. Scope implementation and acceptance from that contract. |

## Merge boundaries

- **Shell and editor.** Keep current run and browse routes usable while migrating the shell. Keep presentation work independent from revision, validation, and submission semantics.
- **Run workflow.** Change post-submit navigation, tracking, and result layout together so the dock and standalone route agree. Keep the stable canonical links available throughout.
- **Secondary screens.** Reuse the shell and interaction rules. Move existing forms, table controls, and typed requests before changing the visual density around them.

For each slice, record what changed, what fixture was exercised, and any gap against [verification and release](04-verification-and-release.md). Keep plan updates in this folder and update user-facing help alongside shipped behavior.
