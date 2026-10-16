
import { useMemo, useState } from 'react'
import Globe from 'react-globe.gl'
import { feature } from 'topojson-client'
import worldData from 'world-atlas/countries-110m.json'

export default function InteractiveGlobe() {
  const [hoveredCountry, setHoveredCountry] = useState(null)

  const countries = useMemo(
    () =>
      feature(worldData, worldData.objects.countries).features,
    [],
  )

  return (
    <div className="globe-wrap">
      <Globe
        width={680}
        height={620}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl="https://unpkg.com/three-globe/example/img/earth-night.jpg"
        bumpImageUrl="https://unpkg.com/three-globe/example/img/earth-topology.png"
        polygonsData={countries}
        polygonCapColor={(country) =>
          country === hoveredCountry
            ? 'rgba(57, 151, 255, 0.55)'
            : 'rgba(20, 90, 160, 0.08)'
        }
        polygonSideColor={() => 'rgba(60, 130, 220, 0.12)'}
        polygonStrokeColor={() => 'rgba(125, 190, 255, 0.55)'}
        polygonAltitude={(country) =>
          country === hoveredCountry ? 0.012 : 0.002
        }
        onPolygonHover={setHoveredCountry}
        polygonLabel={(country) =>
          `<div style="padding:9px 13px;background:#080d14;color:#fff;border:1px solid #3997ff;border-radius:6px;font:12px Inter,sans-serif;letter-spacing:.04em">${country.properties.name}</div>`
        }
        showAtmosphere
        atmosphereColor="#278bff"
        atmosphereAltitude={0.16}
        enablePointerInteraction
      />

      <div className="globe-hint">
        <span className="globe-hint-dot" />
        {hoveredCountry
          ? hoveredCountry.properties.name
          : 'DRAG TO EXPLORE · HOVER OVER COUNTRIES'}
      </div>

      <div className="globe-orbit-label">
        <span>↗</span>
        <small>REAL EVENTS</small>
        <small>REAL CONSEQUENCES</small>
      </div>
    </div>
  )
}
