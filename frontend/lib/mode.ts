// The data source, fixed at build time by NEXT_PUBLIC_DATA_SOURCE (validated
// in next.config.mjs; this module never throws). Both constants are computed
// here, in one module, so the compiler folds them: in the public snapshot
// build API_URL is "" and no backend URL reaches the bundle. A constant
// imported from another module does not fold.
export const isSnapshot = process.env.NEXT_PUBLIC_DATA_SOURCE === "snapshot";

export const API_URL = isSnapshot
  ? ""
  : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
