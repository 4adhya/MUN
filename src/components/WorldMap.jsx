
import { useEffect, useRef, useState } from "react";
import { geoNaturalEarth1, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import world from "world-atlas/countries-110m.json";
import "./WorldMap.css";

const countryNames = {
  4: "Afghanistan", 8: "Albania", 12: "Algeria", 24: "Angola",
  32: "Argentina", 36: "Australia", 40: "Austria", 50: "Bangladesh",
  56: "Belgium", 76: "Brazil", 124: "Canada", 156: "China",
  250: "France", 276: "Germany", 356: "India", 360: "Indonesia",
  364: "Iran", 376: "Israel", 392: "Japan", 410: "South Korea",
  484: "Mexico", 566: "Nigeria", 408: "North Korea", 586: "Pakistan",
  643: "Russia", 682: "Saudi Arabia", 710: "South Africa",
  724: "Spain", 792: "Turkey", 804: "Ukraine",
  826: "United Kingdom", 840: "United States",
};

const countries = feature(
  world,
  world.objects.countries
).features;

export default function WorldMap({
  selectedCountry = "India",
  onCountrySelect = () => {},
  height = 520,
}) {
  const svgRef = useRef(null);
  const [hovered, setHovered] = useState(null);
  const [dimensions, setDimensions] = useState({ width: 900, height });

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const observer = new ResizeObserver(([entry]) => {
      setDimensions({
        width: Math.max(320, entry.contentRect.width),
        height,
      });
    });

    observer.observe(svg.parentElement);
    return () => observer.disconnect();
  }, [height]);

  const projection = geoNaturalEarth1()
    .fitExtent(
      [[8, 12], [dimensions.width - 8, dimensions.height - 12]],
      { type: "Sphere" }
    );

  const path = geoPath(projection);

  return (
    <div className="real-world-map">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
        role="img"
        aria-label="Interactive world map. Hover over a country to identify it and click to select it."
      >
        <defs>
          <pattern
            id="world-map-grid"
            width="32"
            height="32"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 32 0 L 0 0 0 32"
              fill="none"
              stroke="#17344d"
              strokeWidth=".7"
            />
          </pattern>
          <filter id="country-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <rect
          width={dimensions.width}
          height={dimensions.height}
          fill="#071829"
        />
        <rect
          width={dimensions.width}
          height={dimensions.height}
          fill="url(#world-map-grid)"
        />

        <g className="world-country-layer">
          {countries.map((country) => {
            const id = Number(country.id);
            const name = country.properties?.name || countryNames[id] || `Country ${id}`;
            const isSelected = name === selectedCountry;
            const isHovered = hovered?.name === name;

            return (
              <path
                key={country.id}
                d={path(country) || ""}
                className={[
                  "world-country",
                  isSelected ? "is-selected" : "",
                  isHovered ? "is-hovered" : "",
                ].join(" ")}
                tabIndex={0}
                role="button"
                aria-label={name}
                onMouseEnter={(event) =>
                  setHovered({
                    name,
                    x: event.clientX,
                    y: event.clientY,
                  })
                }
                onMouseMove={(event) =>
                  setHovered({
                    name,
                    x: event.clientX,
                    y: event.clientY,
                  })
                }
                onMouseLeave={() => setHovered(null)}
                onFocus={() =>
                  setHovered({ name, x: 0, y: 0 })
                }
                onBlur={() => setHovered(null)}
                onClick={() => onCountrySelect(name)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onCountrySelect(name);
                  }
                }}
              />
            );
          })}
        </g>

        {hovered && (
          <g className="map-hover-label">
            <rect
              x={12}
              y={12}
              width={Math.min(dimensions.width - 24, hovered.name.length * 9 + 35)}
              height={36}
              rx={6}
            />
            <circle cx={25} cy={30} r={4} />
            <text x={37} y={34}>{hovered.name}</text>
          </g>
        )}
      </svg>

      <div className="world-map-footer">
        <span><i className="map-dot selected-dot" /> Selected country</span>
        <span><i className="map-dot hover-dot" /> Hover to explore</span>
        <span>WORLD VIEW · {countries.length} GEOGRAPHIC FEATURES</span>
      </div>
    </div>
  );
}
