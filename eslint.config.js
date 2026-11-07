// TypeScript lint rules supplement compiler strict mode, which permits explicit any.
import tseslint from 'typescript-eslint';

export default tseslint.config(
  ...tseslint.configs.recommended,
  {rules: {'@typescript-eslint/no-explicit-any': 'error', '@typescript-eslint/no-non-null-assertion': 'error'}},
);
