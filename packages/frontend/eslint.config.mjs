import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'

const eslintConfig = [
  { ignores: ['coverage/**'] },
  ...nextCoreWebVitals,
  {
    rules: {
      '@next/next/no-img-element': 'off',
      // Polling completion and hydration readiness are external-system effects.
      'react-hooks/set-state-in-effect': 'off',
      // TanStack Virtual intentionally exposes non-memoizable imperative methods.
      'react-hooks/incompatible-library': 'off',
    },
  },
]

export default eslintConfig
