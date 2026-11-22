import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
  {
    files: [
      "src/audio/**/*.{ts,tsx}",
      "src/hintLevel.ts",
      "src/hintLevel.test.ts",
      "src/hintLadder.ts",
      "src/hintLadder.test.ts",
      "src/mouth.ts",
      "src/mouth.test.ts",
      "src/coach.ts",
      "src/coach.test.ts",
      "src/flow.ts",
      "src/flow.test.ts",
    ],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
);