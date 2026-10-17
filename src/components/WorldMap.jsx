
import { useMemo, useState } from "react";
import { feature } from "topojson-client";
import { geoNaturalEarth1, geoPath } from "d3-geo";
import countriesTopology from "world-atlas/countries-110m.json";
import { MAP_LAYOUT, routePairs, formatGdp } from "../lib/worldView.js";

const MAP_WIDTH = 850;
const MAP_HEIGHT = 440;

const LAND_COLORS = [
  "#a9bbb0",
  "#c9b9a3",
  "#8fa9b7",
  "#c6c9a9",
  "#b4a6bc",
  "#d0b4a7",
  "#9db8ad",
];

export default function WorldMap({
  world,
  selectedId,
  onSelect,
  search = "",
}) {
  const [hoveredCountry, setHoveredCountry] = useState(null);
  const [hoveredMarker, setHoveredMarker] = useState(null);

  const term = search.trim().toLowerCase();

  const geography = useMemo(() => {
    const countries = feature(
      countriesTopology,
      countriesTopology.objects.countries
    );

    const projection = geoNaturalEarth1().fitSize(
      [MAP_WIDTH, MAP_HEIGHT],
      countries
    );

    const pathGenerator = geoPath(projection);

    return {
      countries: countries.features,
      pathGenerator,
    };
  }, []);

  const pairs = routePairs(world).filter(
    (pair) => MAP_LAYOUT[pair.a] && MAP_LAYOUT[pair.b]
  );

  return (
    <div className="world-map">
      <div className="map-graticule" />

      <svg
        className="map-art"
        viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label="Interactive political world map"
      >
        <g className="real-world-countries">
          {geography.countries.map((country, index) => {
            const countryName = country.properties?.name || "Country";

            return (
              <path
                key={country.id ?? index}
                d={geography.pathGenerator(country) || ""}
                fill={LAND_COLORS[index % LAND_COLORS.length]}
                stroke="#f7f3ed"
                strokeWidth={0.65}
                vectorEffect="non-scaling-stroke"
                className="real-country-shape"
                onMouseEnter={() => setHoveredCountry(countryName)}
                onMouseLeave={() => setHoveredCountry(null)}
              >
                <title>{countryName}</title>
              </path>
            );
          })}
        </g>
      </svg>

      {hoveredCountry && (
        <div className="geography-tooltip" role="status">
          {hoveredCountry}
        </div>
      )}

      <svg
        className="live-routes"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {pairs.map((pair) => (
          <line
            key={`${pair.a}-${pair.b}`}
            className={
              pair.anyActive
                ? "live-route"
                : "live-route live-route-cut"
            }
            x1={MAP_LAYOUT[pair.a].x}
            y1={MAP_LAYOUT[pair.a].y}
            x2={MAP_LAYOUT[pair.b].x}
            y2={MAP_LAYOUT[pair.b].y}
          />
        ))}
      </svg>

      {world.countries.map((country) => {
        const spot = MAP_LAYOUT[country.id];

        if (!spot) return null;

        const dimmed =
          term && !country.name.toLowerCase().includes(term);

        return (
          <button
            key={country.id}
            type="button"
            className={[
              "country-marker",
              "marker-live",
              selectedId === country.id ? "marker-selected" : "",
              dimmed ? "marker-dim" : "",
              hoveredMarker === country.id ? "marker-hovered" : "",
            ].filter(Boolean).join(" ")}
            style={{
              left: `${spot.x}%`,
              top: `${spot.y}%`,
            }}
            onMouseEnter={() => setHoveredMarker(country.id)}
            onMouseLeave={() => setHoveredMarker(null)}
            onFocus={() => setHoveredMarker(country.id)}
            onBlur={() => setHoveredMarker(null)}
            onClick={() => onSelect(country.id)}
            aria-label={`Open ${country.name}`}
          >
            <span className="marker-badge">
              {country.name[0]}
            </span>

            <span className="country-marker-info">
              <strong>{country.name}</strong>
              <small>
                Stability {country.stability} · GDP {formatGdp(country.gdp)}
              </small>
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
