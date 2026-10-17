import { MAP_LAYOUT, routePairs, formatGdp } from "../lib/worldView.js";

// The illustrative base map is artwork. Markers, trade lines and numbers come from the backend world.
export default function WorldMap({ world, selectedId, onSelect, search = "" }) {
  const term = search.trim().toLowerCase();
  const pairs = routePairs(world).filter((p) => MAP_LAYOUT[p.a] && MAP_LAYOUT[p.b]);

  return (
    <div className="world-map">
      <div className="map-ocean-label atlantic-label">Atlantic Ocean</div>
      <div className="map-ocean-label arctic-label">Arctic Ocean</div>
      <div className="map-ocean-label indian-label">Indian Ocean</div>
      <div className="map-graticule" />

      <svg
        className="map-art"
        viewBox="0 0 850 440"
        preserveAspectRatio="xMidYMid slice"
        role="img"
        aria-label="Illustrative geopolitical world map with trade routes"
      >
        <defs>
          <pattern id="mapDots" width="7" height="7" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r=".8" fill="#ffffff" opacity=".35" />
          </pattern>
          <linearGradient id="mapLand" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#d7d0c1" />
            <stop offset="100%" stopColor="#b4c4b7" />
          </linearGradient>
          <filter id="mapShadow">
            <feDropShadow dx="0" dy="2" stdDeviation="2" floodOpacity=".1" />
          </filter>
        </defs>

        <g className="landmass" filter="url(#mapShadow)">
          <path fill="#637f96" d="M30 80 L66 55 110 58 135 38 175 50 192 80 228 87 244 115 222 138 197 141 183 165 156 174 145 208 119 219 103 192 80 177 75 151 49 133 25 113Z" />
          <path fill="#71899a" d="M155 207 L181 221 193 244 182 266 165 291 150 319 132 333 121 310 124 279 111 255 124 233Z" />
          <path fill="#829a9a" d="M237 295 L273 284 300 299 321 323 309 355 295 382 280 414 263 391 252 358 232 337Z" />
          <path fill="#b6a58e" d="M350 81 L374 62 404 66 427 83 447 78 470 89 482 111 464 129 442 124 432 143 410 143 399 159 374 150 359 125 340 115Z" />
          <path fill="#a4b4a5" d="M365 157 L399 150 430 167 443 197 431 229 414 254 393 271 377 247 362 219 348 192Z" />
          <path fill="#819c9c" d="M421 65 L461 49 507 56 540 48 577 61 615 55 654 77 689 72 730 96 759 115 745 137 706 141 685 161 658 163 638 184 611 174 591 155 563 155 548 137 515 137 493 117 464 120 449 96Z" />
          <path fill="#bc9c8c" d="M638 183 L667 174 696 187 709 212 697 236 674 245 655 231 639 208Z" />
          <path fill="#9bafa0" d="M531 170 L560 166 585 186 595 211 583 235 566 248 547 229 535 207Z" />
          <path fill="#b7c1aa" d="M708 271 L743 260 775 274 794 300 775 322 750 313 735 292Z" />
          <path fill="#b8a78e" d="M775 340 L800 331 821 344 813 363 790 371Z" />
          <path fill="#c6b9a7" d="M297 65 L321 54 336 68 325 85 308 87Z" />
        </g>

        <g className="country-lines">
          <path d="M60 90 L99 121 91 156 136 168 176 140 212 116" />
          <path d="M138 68 L145 113 176 140 164 175" />
          <path d="M151 229 L180 251 150 278 164 310" />
          <path d="M261 307 L289 329 279 362 297 386" />
          <path d="M374 83 L389 108 424 104 451 92" />
          <path d="M376 168 L402 194 394 222 416 240" />
          <path d="M453 80 L475 101 501 92 524 124 551 106" />
          <path d="M530 169 L551 192 575 188 589 216" />
          <path d="M588 76 L605 107 644 103 670 126 703 113" />
          <path d="M644 187 L668 208 690 200" />
        </g>
      </svg>

      <svg className="live-routes" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {pairs.map((p) => (
          <line
            key={`${p.a}-${p.b}`}
            className={p.anyActive ? "live-route" : "live-route live-route-cut"}
            x1={MAP_LAYOUT[p.a].x} y1={MAP_LAYOUT[p.a].y}
            x2={MAP_LAYOUT[p.b].x} y2={MAP_LAYOUT[p.b].y}
          />
        ))}
      </svg>

      {world.countries.map((country) => {
        const spot = MAP_LAYOUT[country.id];
        if (!spot) return null;
        const dimmed = term && !country.name.toLowerCase().includes(term);
        return (
          <button
            key={country.id}
            className={`country-marker marker-live ${selectedId === country.id ? "marker-selected" : ""} ${dimmed ? "marker-dim" : ""}`}
            style={{ left: `${spot.x}%`, top: `${spot.y}%` }}
            onClick={() => onSelect(country.id)}
            aria-label={`Open ${country.name}`}
          >
            <span className="marker-badge">{country.name[0]}</span>
            <span>
              <strong>{country.name}</strong>
              <small>Stability {country.stability} · GDP {formatGdp(country.gdp)}</small>
            </span>
          </button>
        );
      })}

      <div className="map-legend">
        <span><i className="legend-dashed" /> Active trade route</span>
        <span><i className="legend-red" /> Route cut off</span>
      </div>
    </div>
  );
}