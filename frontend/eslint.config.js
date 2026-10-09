import ts from "typescript-eslint";
import hooks from "eslint-plugin-react-hooks";
export default ts.config(...ts.configs.recommended, {
  files: ["src/**/*.{ts,tsx}"],
  plugins: { "react-hooks": hooks },
  rules: {
    "react-hooks/rules-of-hooks": "error",
    "@typescript-eslint/no-explicit-any": "error",
  },
});
