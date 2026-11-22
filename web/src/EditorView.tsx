import { useEffect, useReducer, useState } from "react";
import { fetchScenarioYaml, listScenarios, validateScenario, type ScenarioSummary } from "./api";
import { downloadYaml, editorReducer, exportEnabled, initialEditorState } from "./editor";

export function EditorView() {
  const [state, dispatch] = useReducer(editorReducer, undefined, initialEditorState);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      try {
        const rows = await listScenarios();
        if (!cancel) setScenarios(rows);
      } catch {
        if (!cancel) setListError("Couldn't list scenarios.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  async function onLoad(id: string) {
    if (!id) return;
    setBusy(true);
    setListError(null);
    try {
      const yaml = await fetchScenarioYaml(id);
      dispatch({ type: "load", yaml, filename: `${id}.yaml` });
    } catch {
      setListError("Couldn't load that scenario.");
    } finally {
      setBusy(false);
    }
  }

  async function onValidate() {
    setBusy(true);
    try {
      const result = await validateScenario(state.yaml);
      if (result.ok && result.id) {
        dispatch({ type: "validated", ok: true, id: result.id });
      } else {
        dispatch({ type: "validated", ok: false, errors: result.errors });
      }
    } catch (err) {
      dispatch({
        type: "validated",
        ok: false,
        errors: [{ path: "request", message: err instanceof Error ? err.message : "validate failed", line: null }],
      });
    } finally {
      setBusy(false);
    }
  }

  const canExport = exportEnabled(state);
  let statusLabel = "Not validated";
  if (state.status === "valid") statusLabel = "Valid";
  if (state.status === "invalid") statusLabel = "Invalid";

  return (
    <section className="editor-layout">
      <div className="editor-actions">
        <label>
          Load
          <select
            aria-label="Load scenario"
            defaultValue=""
            disabled={busy}
            onChange={(event) => void onLoad(event.target.value)}
          >
            <option value="">Choose a scenario…</option>
            {scenarios.map((row) => (
              <option key={row.id} value={row.id}>
                {row.title_en}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={busy} onClick={() => void onValidate()}>
          {busy ? "…" : "Validate"}
        </button>
        <button type="button" disabled={!canExport} onClick={() => downloadYaml(state.filename, state.yaml)}>
          Export .yaml
        </button>
        <span className="editor-status" data-status={state.status}>
          {statusLabel}
        </span>
      </div>
      {listError ? <p className="hint-error">{listError}</p> : null}
      <textarea
        aria-label="Scenario YAML"
        spellCheck={false}
        value={state.yaml}
        onChange={(event) => dispatch({ type: "edit", yaml: event.target.value })}
      />
      {state.errors.length ? (
        <ul className="editor-errors">
          {state.errors.map((err, index) => (
            <li key={`${err.path}-${index}`}>
              {err.line ? `line ${err.line}: ` : ""}
              {err.path}: {err.message}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
