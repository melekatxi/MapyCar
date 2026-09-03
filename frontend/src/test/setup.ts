import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Leaflet necesita un DOM con tamaño real; en jsdom sustituimos el mapa por
// botones/divs consultables para que el flujo importar → mapa sea testeable.
vi.mock("react-leaflet", async () => {
  const { createElement } = await import("react");
  return {
    MapContainer: ({ children }: { children?: unknown }) =>
      createElement("div", { "data-testid": "leaflet-map" }, children as never),
    TileLayer: () => null,
    CircleMarker: ({
      children,
      eventHandlers,
      center,
    }: {
      children?: unknown;
      eventHandlers?: { click?: () => void };
      center: [number, number];
    }) =>
      createElement(
        "button",
        {
          type: "button",
          "data-testid": "map-marker",
          "data-lat": String(center[0]),
          "data-lng": String(center[1]),
          onClick: () => eventHandlers?.click?.(),
        },
        children as never,
      ),
    Marker: ({ children }: { children?: unknown }) =>
      createElement("div", { "data-testid": "map-pin" }, children as never),
    Popup: ({ children }: { children?: unknown }) =>
      createElement("div", null, children as never),
    useMapEvents: () => ({}),
  };
});
