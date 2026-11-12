// ESLint 9 flat config for the Nirvaah frontend.
//
// Scope: catch real mistakes (undefined variables, broken hooks, unused imports)
// without demanding a refactor of the existing JSX. Rules that the current code
// violates in bulk are set to "warn" so CI can report them without turning red
// on day one — see docs/engineering/CODING_STANDARDS.md for the ratchet plan.

import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default [
    {
        ignores: ['dist/**', 'node_modules/**', '.src-backup-*/**', 'public/sw.js'],
    },
    js.configs.recommended,
    {
        files: ['**/*.{js,jsx}'],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: 'module',
            globals: {
                ...globals.browser,
                // injected by vite.config.js `define`
                __APP_VERSION__: 'readonly',
            },
            parserOptions: {
                ecmaFeatures: { jsx: true },
            },
        },
        settings: {
            react: { version: 'detect' },
        },
        plugins: {
            react,
            'react-hooks': reactHooks,
            'react-refresh': reactRefresh,
        },
        rules: {
            ...react.configs.flat.recommended.rules,
            // The app targets React 18 with the new JSX transform.
            'react/react-in-jsx-scope': 'off',
            // No PropTypes anywhere; the codebase is plain JS with no runtime checks.
            'react/prop-types': 'off',
            'react/no-unescaped-entities': 'warn',
            // Unused imports/variables exist in bulk today: report, do not block.
            'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
            'no-empty': ['warn', { allowEmptyCatch: true }],
            'no-cond-assign': ['error', 'except-parens'],
            // Hooks are a correctness rule, not a style one — keep them errors.
            'react-hooks/rules-of-hooks': 'error',
            'react-hooks/exhaustive-deps': 'warn',
            'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
        },
    },
    {
        // Config and build files run in Node, not the browser.
        files: ['vite.config.js', 'eslint.config.js'],
        languageOptions: { globals: { ...globals.node } },
    },
];
