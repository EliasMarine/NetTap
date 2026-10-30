// Force client-side rendering only — SSR produces just a loading spinner
// for this page since all data is fetched on mount. Skipping SSR avoids
// hydration mismatches between server HTML and client DOM.
export const ssr = false;
