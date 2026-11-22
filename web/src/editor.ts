export type ScenarioIssue = {
  path: string;
  message: string;
  line: number | null;
};

export type EditorState = {
  yaml: string;
  status: "editing" | "valid" | "invalid";
  errors: ScenarioIssue[];
  filename: string;
};

export type EditorAction =
  | { type: "edit"; yaml: string }
  | { type: "load"; yaml: string; filename: string }
  | { type: "validated"; ok: true; id: string }
  | { type: "validated"; ok: false; errors: ScenarioIssue[] };

export function initialEditorState(): EditorState {
  return { yaml: "", status: "editing", errors: [], filename: "scenario.yaml" };
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "edit":
      return { ...state, yaml: action.yaml, status: "editing", errors: [] };
    case "load":
      return { yaml: action.yaml, status: "editing", errors: [], filename: action.filename };
    case "validated":
      if (action.ok) {
        return { ...state, status: "valid", errors: [], filename: `${action.id}.yaml` };
      }
      return { ...state, status: "invalid", errors: action.errors };
    default:
      return state;
  }
}

/** Export stays off until the current text has passed validation. */
export function exportEnabled(state: EditorState): boolean {
  return state.status === "valid" && state.yaml.trim().length > 0;
}

export function downloadYaml(filename: string, yaml: string): void {
  const blob = new Blob([yaml], { type: "application/yaml" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.endsWith(".yaml") ? filename : `${filename}.yaml`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
