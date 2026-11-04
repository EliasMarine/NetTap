// Disable SSR — first for Leaflet (browser globals); kept now that the map is DotMap, since the
// page is all live client data and has nothing to render on the server
export const ssr = false;
