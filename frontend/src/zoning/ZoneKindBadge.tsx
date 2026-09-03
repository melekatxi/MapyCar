const KIND_ORDER = ["urban", "rural", "mixed"] as const;

export type ZoneKind = (typeof KIND_ORDER)[number];

const KIND_LABELS: Record<ZoneKind, string> = {
  urban: "Urbana",
  rural: "Rural",
  mixed: "Mixta",
};

const KIND_ARIA: Record<ZoneKind, string> = {
  urban: "Zona urbana",
  rural: "Zona rural",
  mixed: "Zona mixta",
};

function isZoneKind(kind: string): kind is ZoneKind {
  return kind === "urban" || kind === "rural" || kind === "mixed";
}

function KindIcon({ kind }: { kind: ZoneKind }) {
  if (kind === "rural") {
    return (
      <svg
        className="zone-kind__icon"
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        <path
          fill="currentColor"
          d="M12 3 7 11h3l-4 6h5v4h2v-4h5l-4-6h3L12 3z"
        />
      </svg>
    );
  }
  if (kind === "mixed") {
    return (
      <svg
        className="zone-kind__icon"
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        <path
          fill="currentColor"
          d="M2 20V9l4-2v2l3-3v14H2zm16.5-16L15 11h2l-3 6h3.5v3h2v-3H23l-3-6h2l-3.5-7z"
        />
      </svg>
    );
  }
  return (
    <svg
      className="zone-kind__icon"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="currentColor"
        d="M3 21V10l4-2v2l4-4v4h2V5l8 4v12H3zm3-3h2v2H6v-2zm0-3h2v2H6v-2zm5 3h2v2h-2v-2zm0-3h2v2h-2v-2zm5-1h2v2h-2v-2zm0 3h2v2h-2v-2z"
      />
    </svg>
  );
}

interface BadgeProps {
  kind: string;
}

export function ZoneKindBadge({ kind }: BadgeProps) {
  const resolved: ZoneKind = isZoneKind(kind) ? kind : "mixed";
  const label = isZoneKind(kind) ? KIND_LABELS[kind] : kind;
  return (
    <span
      className={`zone-kind zone-kind--${resolved}`}
      aria-label={KIND_ARIA[resolved]}
    >
      <KindIcon kind={resolved} />
      <span className="zone-kind__label">{label}</span>
    </span>
  );
}

export function ZoneKindLegend() {
  return (
    <div className="map-legends">
      <p className="map-legend__title">Tipo de zona</p>
      <ul className="map-legend" aria-label="Tipo de zona">
        {KIND_ORDER.map((kind) => (
          <li key={kind}>
            <ZoneKindBadge kind={kind} />
          </li>
        ))}
      </ul>
    </div>
  );
}
