// ESLint 9 flat config for the frontend.
// TypeScript is the source language (plan D7), so the TypeScript and React
// rules apply to .ts and .tsx files only.
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  {
    ignores: ['dist/', 'node_modules/', 'coverage/'],
  },
  ...tseslint.config({
    files: ['**/*.{ts,tsx}'],
    extends: [tseslint.configs.recommended],
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  }),
];
