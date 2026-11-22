import { resolveTown, type ScenarioCard } from "./townMap";

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

  return (
    <section className="town" aria-label="Town">
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
