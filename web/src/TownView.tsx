import { useEffect, useState } from "react";
import { SORA_EXPRESSIONS, spriteSrcOnMissing, soraSpriteUrl } from "./soraExpressions";
import { resolveTown, type ScenarioCard } from "./townMap";

function guidePlate(mapUrl: string): string {
  if (!mapUrl) return "";
  const resting = mapUrl.replace(/\/bg\/[^/?#]+$/, `/sprites/sora/${SORA_EXPRESSIONS[0]}.webp`);
  return soraSpriteUrl(resting, SORA_EXPRESSIONS[0]);
}

export function TownView({
  scenarios,
  mapUrl,
  onOpen,
}: {
  scenarios: ScenarioCard[];
  mapUrl: string;
  onOpen: (scenarioId: string) => void;
}) {
  const { hotspots, locked } = resolveTown(scenarios);
  const mapSrc = mapUrl;
  const resting = SORA_EXPRESSIONS[0];
  const [guideSrc, setGuideSrc] = useState("");

  useEffect(() => {
    setGuideSrc(guidePlate(mapSrc));
  }, [mapSrc]);

  return (
    <section className="town" aria-label="Town">
      {guideSrc ? (
        <img
          className="town-guide"
          src={guideSrc}
          alt="Sora"
          width={44}
          height={44}
          data-expression={resting}
          onError={() =>
            setGuideSrc((current) => {
              const next = spriteSrcOnMissing(current);
              return next === current ? current : next;
            })
          }
        />
      ) : null}
      <div className="town-scroll">
      <div className="town-stage">
        {mapSrc ? <img className="town-map" src={mapSrc} alt="" /> : null}
        {hotspots.map((spot) => (
          <button
            key={spot.id}
            type="button"
            className={spot.locked ? "town-hotspot locked" : "town-hotspot"}
            style={{
              left: `${spot.left}%`,
              top: `${spot.top}%`,
              width: `${spot.width}%`,
              height: `${spot.height}%`,
            }}
            disabled={spot.locked}
            title={spot.locked ? "Locked" : `${spot.titleEn} · ${spot.titleJa}`}
            onClick={() => onOpen(spot.scenarioId)}
          >
            <span className="town-label">
              <span className="en">{spot.titleEn}</span>
              <span className="ja">{spot.titleJa}</span>
            </span>
          </button>
        ))}
      </div>
      </div>
      {locked.length > 0 ? (
        <ul className="town-locked">
          {locked.map((card) => (
            <li key={card.id} title={card.tooltip}>
              {card.titleEn} · {card.titleJa}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
