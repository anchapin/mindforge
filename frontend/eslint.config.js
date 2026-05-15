// ESLint v9 flat config — Wave 6 PR B
// Stack: Vite + React 19 + TypeScript (strict)
// Goal: enforce real bug-class rules; downgrade noisy stylistic rules to warn/off
//       so an existing 45-file codebase passes immediately. Stricter rules can
//       be ratcheted up in follow-ups.

import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default tseslint.config(
  // 1. Ignore build output / vendored / generated
  {
    ignores: [
      "dist/**",
      "build/**",
      "coverage/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
      "*.config.js",
      "*.config.ts",
    ],
  },

  // 2. Base recommended rules from eslint + typescript-eslint
  js.configs.recommended,
  ...tseslint.configs.recommended,

  // 3. App source — React + hooks + Vite refresh boundary
  {
    files: ["src/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      // Bug-class — keep at error
      "react-hooks/rules-of-hooks": "error",
      "no-undef": "off", // TypeScript handles this; flat-config /globals false-positives are common

      // Pragmatic for this codebase (45 files, 108 tests already green)
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "no-unused-vars": "off", // delegated to @typescript-eslint/no-unused-vars
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },

  // 4. Test files — relax type assertions & require for fixtures/mocks
  {
    files: ["**/*.test.{ts,tsx}", "tests/**/*.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/ban-ts-comment": "off",
      "@typescript-eslint/no-empty-function": "off",
    },
  },
);
