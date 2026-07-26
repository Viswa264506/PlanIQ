import { useState, useRef, useEffect } from "react";

const API_BASE = "http://localhost:5000";
const SESSION_ID = "session_" + Math.random().toString(36).slice(2);

const REGIONS = ["default", "coimbatore", "chennai", "bangalore", "hyderabad", "mumbai", "pune", "delhi", "kochi", "madurai"];

// Mirrors backend/lifestyle_agent.py's LIFESTYLE_DEFAULTS — these are only
// used to pre-fill the wizard's later steps; the backend Lifestyle Agent is
// the source of truth for how rooms actually get distributed across floors.
const LIFESTYLES = [
  { id: "bachelor", label: "Bachelor", blurb: "Compact, efficient, low-maintenance" },
  { id: "couple", label: "Couple", blurb: "Open living, no clutter" },
  { id: "couple_with_kids", label: "Couple with Kids", blurb: "Kids' rooms, study area" },
  { id: "family_with_adults", label: "Family with Adults", blurb: "Guest room, more privacy" },
  { id: "joint_family", label: "Joint Family", blurb: "Multi-generational, larger living" },
  { id: "senior_citizens", label: "Senior Citizens", blurb: "Ground floor bedroom, minimal stairs" },
  { id: "wfh", label: "Work From Home", blurb: "Quiet office, natural light" },
  { id: "other", label: "Other", blurb: "I'll customize everything myself" },
];

const LIFESTYLE_DEFAULTS = {
  bachelor: { bedrooms: 1, bathrooms: 1, kitchen_type: "Small Kitchen", parking: true, pooja_room: false, balcony: false },
  couple: { bedrooms: 1, bathrooms: 1, kitchen_type: "Open Kitchen", parking: false, pooja_room: false, balcony: true },
  couple_with_kids: { bedrooms: 2, bathrooms: 2, kitchen_type: "Kitchen", parking: true, pooja_room: true, balcony: true },
  family_with_adults: { bedrooms: 3, bathrooms: 3, kitchen_type: "Kitchen", parking: true, pooja_room: true, balcony: true },
  joint_family: { bedrooms: 4, bathrooms: 4, kitchen_type: "Kitchen", parking: true, pooja_room: true, balcony: true },
  senior_citizens: { bedrooms: 2, bathrooms: 2, kitchen_type: "Kitchen", parking: true, pooja_room: true, balcony: false },
  wfh: { bedrooms: 2, bathrooms: 2, kitchen_type: "Kitchen", parking: true, pooja_room: false, balcony: true },
  other: { bedrooms: 2, bathrooms: 2, kitchen_type: "Kitchen", parking: true, pooja_room: false, balcony: false },
};

const KITCHEN_TYPES = ["Small Kitchen", "Open Kitchen", "Kitchen"];

const EXTRA_ROOM_OPTIONS = [
  "Kitchen",
  "Pooja room",
  "Parking",
  "Study room",
  "Guest room",
  "Store room",
  "Balcony",
  "Servant room",
  "Home office",
];

// Mirrors backend/blueprint_agent.py's room_color() palette, so the 3D
// preview's room floor tints match the 2D SVG blueprint.
const ROOM_COLORS = {
  "Living Room": "#FDEBD0",
  Kitchen: "#D6EAF8",
  "Master Bedroom": "#E8DAEF",
  Bathroom: "#D5F5E3",
  "Attached Bathroom": "#D5F5E3",
  "Common Bathroom": "#D5F5E3",
  "Pooja Room": "#FCF3CF",
  Parking: "#EAECEE",
  Dining: "#FADBD8",
  "Family Hall": "#D0ECE7",
  "Open Terrace": "#F5EEF8",
  Staircase: "#D7DBDD",
};

function roomColor(name) {
  if (ROOM_COLORS[name]) return ROOM_COLORS[name];
  if (name && name.startsWith("Bedroom")) return "#E8DAEF";
  return "#F2F3F4";
}

// 3D Floor Plan Preview — Three.js scene built directly from the Layout
// Agent's room geometry (x/y/width/height in feet, same numbers the SVG
// blueprint uses). Each room is a colored floor slab plus four extruded
// perimeter walls; camera starts in an elevated top-down position and can
// be orbited/tilted by the user for the "wow factor" 3D view.
function FloorPlan3D({ layout, floorNum }) {
  const mountRef = useRef(null);

  useEffect(() => {
    let renderer, scene, camera, controls, frameId, resizeObserver;
    let disposed = false;

    (async () => {
      const THREE = await import("three");
      const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
      const { CSS2DRenderer, CSS2DObject } = await import("three/examples/jsm/renderers/CSS2DRenderer.js");
      if (disposed) return;

      const mount = mountRef.current;
      if (!mount) return;
      mount.innerHTML = "";

      const rooms = (layout.floors && layout.floors[floorNum]) || [];
      const plotW = layout.plot_width;
      const plotH = layout.plot_height;
      const maxDim = Math.max(plotW, plotH);
      const wallHeight = 9; // feet — same unit scale as the plot dimensions
      const wallThickness = 0.5;

      const width = mount.clientWidth || 320;
      const height = 380;

      scene = new THREE.Scene();
      scene.background = new THREE.Color(0xf6f5f2);
      scene.fog = new THREE.Fog(0xf6f5f2, maxDim * 1.6, maxDim * 4.2);

      camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 2000);
      camera.position.set(plotW / 2, maxDim * 1.15, plotH / 2 + maxDim * 0.95);
      camera.lookAt(plotW / 2, 0, plotH / 2);

      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      mount.appendChild(renderer.domElement);

      const labelRenderer = new CSS2DRenderer();
      labelRenderer.setSize(width, height);
      labelRenderer.domElement.style.position = "absolute";
      labelRenderer.domElement.style.top = "0";
      labelRenderer.domElement.style.left = "0";
      labelRenderer.domElement.style.pointerEvents = "none";
      mount.appendChild(labelRenderer.domElement);

      controls = new OrbitControls(camera, renderer.domElement);
      controls.target.set(plotW / 2, 0, plotH / 2);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.maxPolarAngle = Math.PI / 2.05; // don't let it dip below the ground
      controls.minDistance = maxDim * 0.4;
      controls.maxDistance = maxDim * 3;
      controls.update();

      scene.add(new THREE.HemisphereLight(0xfff6e6, 0x8d8264, 0.85));
      const sun = new THREE.DirectionalLight(0xfff2df, 1.0);
      sun.position.set(plotW * 1.4, maxDim * 2.1, plotH * 0.35);
      sun.castShadow = true;
      sun.shadow.mapSize.set(1024, 1024);
      sun.shadow.camera.left = -maxDim * 1.3;
      sun.shadow.camera.right = maxDim * 1.3;
      sun.shadow.camera.top = maxDim * 1.3;
      sun.shadow.camera.bottom = -maxDim * 1.3;
      sun.shadow.bias = -0.0015;
      scene.add(sun);
      const fill = new THREE.DirectionalLight(0xdfe8ff, 0.25);
      fill.position.set(-plotW * 0.6, maxDim * 1.2, -plotH * 0.6);
      scene.add(fill);

      // Site slab beneath the whole plot, plus a fine grid so the ground
      // reads as landscaped terrain rather than a flat color card.
      const siteGeo = new THREE.BoxGeometry(plotW + 8, 0.3, plotH + 8);
      const siteMat = new THREE.MeshStandardMaterial({ color: 0xede9f2, roughness: 0.95 });
      const site = new THREE.Mesh(siteGeo, siteMat);
      site.position.set(plotW / 2, -0.16, plotH / 2);
      site.receiveShadow = true;
      scene.add(site);
      const grid = new THREE.GridHelper(Math.max(plotW, plotH) + 8, 12, 0xc9c4d6, 0xe2deec);
      grid.position.set(plotW / 2, 0.005, plotH / 2);
      scene.add(grid);

      const GAP = 0.22; // grout gap so adjacent room floors read as separate tiles
      const WINDOW_W = 0.55; // window band height on exterior facade walls

      rooms.forEach((room) => {
        const { x, y, width: rw, height: rh, name } = room;
        if (rw <= 0 || rh <= 0) return;

        const floorMat = new THREE.MeshStandardMaterial({
          color: new THREE.Color(roomColor(name)),
          roughness: 0.72,
          metalness: 0.03,
        });
        const floorMesh = new THREE.Mesh(
          new THREE.BoxGeometry(Math.max(rw - GAP, 0.1), 0.16, Math.max(rh - GAP, 0.1)),
          floorMat
        );
        floorMesh.position.set(x + rw / 2, 0.08, y + rh / 2);
        floorMesh.receiveShadow = true;
        scene.add(floorMesh);

        // Room name label — floats just above the walls, always facing
        // the camera, and stays legible while the user orbits/zooms.
        const labelDiv = document.createElement("div");
        labelDiv.className = "room-label-3d";
        labelDiv.textContent = name;
        const label = new CSS2DObject(labelDiv);
        label.position.set(x + rw / 2, wallHeight + 1.2, y + rh / 2);
        scene.add(label);

        // Four perimeter walls, extruded up from the floor slab. Walls on
        // the plot boundary are treated as exterior facade (darker, gets
        // a window band); shared interior walls are lighter and plain.
        const touchesN = y <= 0.01, touchesS = y + rh >= plotH - 0.01;
        const touchesW = x <= 0.01, touchesE = x + rw >= plotW - 0.01;
        const segments = [
          [rw + wallThickness, wallThickness, x + rw / 2, y, touchesN],
          [rw + wallThickness, wallThickness, x + rw / 2, y + rh, touchesS],
          [wallThickness, rh + wallThickness, x, y + rh / 2, touchesW],
          [wallThickness, rh + wallThickness, x + rw, y + rh / 2, touchesE],
        ];
        segments.forEach(([w, d, cx, cz, exterior]) => {
          const wallMat = new THREE.MeshStandardMaterial({
            color: exterior ? 0xafa8c2 : 0xe3deef,
            roughness: exterior ? 0.88 : 0.8,
          });
          const wall = new THREE.Mesh(new THREE.BoxGeometry(w, wallHeight, d), wallMat);
          wall.position.set(cx, wallHeight / 2, cz);
          wall.castShadow = true;
          wall.receiveShadow = true;
          scene.add(wall);

          // Facade window: a thin glassy band inset into the exterior
          // wall face, floating mid-height — breaks up the solid block.
          if (exterior && name !== "Staircase" && Math.max(w, d) > 3) {
            const glassMat = new THREE.MeshStandardMaterial({
              color: 0xaed6f1, roughness: 0.15, metalness: 0.4, transparent: true, opacity: 0.75,
            });
            const glassW = w > d ? w * 0.5 : wallThickness + 0.06;
            const glassD = w > d ? wallThickness + 0.06 : d * 0.5;
            const glass = new THREE.Mesh(new THREE.BoxGeometry(glassW, WINDOW_W, glassD), glassMat);
            glass.position.set(cx, wallHeight * 0.58, cz);
            scene.add(glass);
          }
        });
      });

      const animate = () => {
        frameId = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
        labelRenderer.render(scene, camera);
      };
      animate();

      resizeObserver = new ResizeObserver(() => {
        if (!mount) return;
        const w = mount.clientWidth || 320;
        camera.aspect = w / height;
        camera.updateProjectionMatrix();
        renderer.setSize(w, height);
        labelRenderer.setSize(w, height);
      });
      resizeObserver.observe(mount);
    })();

    return () => {
      disposed = true;
      if (frameId) cancelAnimationFrame(frameId);
      if (resizeObserver) resizeObserver.disconnect();
      if (renderer) {
        renderer.dispose();
        renderer.domElement && renderer.domElement.remove();
      }
    };
  }, [layout, floorNum]);

  return <div className="three-d-canvas" ref={mountRef} />;
}

// Construction Timeline Estimator — renders Agent 6's phase breakdown
// (Foundation -> Structure -> Roofing -> Finishing) as a simple Gantt bar
// chart, pairing naturally with the Budget Ledger below it.
const GANTT_PHASE_COLORS = {
  Foundation: "#8D6E63",
  Structure: "#5D6D7E",
  Roofing: "#6C4CF0",
  Finishing: "#2E7D4F",
};

function TimelineGantt({ timeline }) {
  if (!timeline) return null;
  const total = timeline.total_days || 1;
  return (
    <div className="gantt-card">
      <div className="gantt-summary">
        <span>
          Total: <b>{timeline.total_days} days</b>
        </span>
        <span>
          ≈ <b>{timeline.total_weeks} weeks</b>
        </span>
        <span>
          ≈ <b>{timeline.total_months} months</b>
        </span>
      </div>
      <div className="gantt-chart">
        {timeline.phases.map((p) => (
          <div className="gantt-row" key={p.phase}>
            <div className="gantt-label">{p.phase}</div>
            <div className="gantt-track">
              <div
                className="gantt-bar"
                style={{
                  left: `${((p.start_day - 1) / total) * 100}%`,
                  width: `${(p.duration_days / total) * 100}%`,
                  background: GANTT_PHASE_COLORS[p.phase] || "var(--orange)",
                }}
                title={`${p.description} — Day ${p.start_day}\u2013${p.end_day} (${p.duration_days}d)`}
              >
                <span>{p.duration_days}d</span>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="disclaimer">{timeline.estimated_completion_note}</div>
    </div>
  );
}

function BlueprintArt() {
  return (
    <div className="blueprint-art">
      <div className="ledger-stamp mono">
        PLAN NO.
        <br />
        001
      </div>
      <svg viewBox="0 0 420 300" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M20 0H0V20" fill="none" stroke="rgba(255,255,255,0.10)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="420" height="300" fill="url(#grid)" />

        {/* House elevation, drawn as a blueprint line-sketch */}
        <g stroke="#B9A9FF" strokeWidth="2.6" fill="none" strokeLinejoin="round" strokeLinecap="round">
          {/* roof */}
          <path className="draw-path" pathLength="100" d="M65 130 L210 55 L355 130" style={{ animationDelay: "0s" }} />
          {/* walls */}
          <path
            className="draw-path"
            pathLength="100"
            d="M85 130 V235 H335 V130"
            style={{ animationDelay: "0.35s" }}
          />
          {/* chimney */}
          <path className="draw-path" pathLength="100" d="M270 58 V88" style={{ animationDelay: "0.15s" }} />
          {/* door */}
          <path
            className="draw-path"
            pathLength="100"
            d="M188 235 V172 H232 V235"
            style={{ animationDelay: "0.7s" }}
          />
          {/* left window */}
          <rect className="draw-path" pathLength="100" x="112" y="160" width="42" height="38" rx="2" style={{ animationDelay: "0.9s" }} />
          <path className="draw-path" pathLength="100" d="M133 160 V198 M112 179 H154" style={{ animationDelay: "1.05s" }} />
          {/* right window */}
          <rect className="draw-path" pathLength="100" x="266" y="160" width="42" height="38" rx="2" style={{ animationDelay: "0.9s" }} />
          <path className="draw-path" pathLength="100" d="M287 160 V198 M266 179 H308" style={{ animationDelay: "1.05s" }} />
        </g>

        {/* ground / dimension line */}
        <g stroke="#57536A" strokeWidth="1" opacity="0.6">
          <line x1="60" y1="252" x2="360" y2="252" />
          <line x1="60" y1="246" x2="60" y2="258" />
          <line x1="360" y1="246" x2="360" y2="258" />
        </g>
        <text x="210" y="270" textAnchor="middle" fill="#8B87A0" fontSize="11" fontFamily="JetBrains Mono, monospace">
          30 FT
        </text>
        <circle className="pulse-dot" cx="130" cy="105" r="3" fill="#8F76FF" style={{ animationDelay: "1.4s" }} />
        <circle className="pulse-dot" cx="300" cy="200" r="3" fill="#8F76FF" style={{ animationDelay: "1.7s" }} />
      </svg>
    </div>
  );
}

function FitCallout({ fit }) {
  if (!fit) return null;
  return (
    <div className="fit-callout">
      <div className="fit-status">{fit.fit_status} fit</div>
      <p>{fit.fit_message}</p>
      <p style={{ opacity: 0.75 }}>
        Implied rate: ≈ ₹{fit.implied_rate_per_sqft_inr}/sqft
      </p>
    </div>
  );
}

// Save & Compare Plans — side-by-side comparison of 2-3 saved plans
// pulled from the SQLite-backed /api/plans/compare endpoint.
function ComparePanel({ plans, onClose }) {
  if (!plans || !plans.length) return null;
  const minCost = Math.min(...plans.map((p) => p.budget.estimated_total_cost_inr));
  const minDays = Math.min(...plans.map((p) => (p.timeline ? p.timeline.total_days : Infinity)));
  const firstFloorSvg = (p) => p.svg_by_floor["1"] || Object.values(p.svg_by_floor)[0];

  const roomCount = (p) =>
    Object.values(p.layout.floors || {}).reduce((sum, rooms) => sum + rooms.length, 0);
  const effectiveRate = (p) =>
    p.budget.built_up_area_sqft ? Math.round(p.budget.estimated_total_cost_inr / p.budget.built_up_area_sqft) : null;
  const minEffRate = Math.min(...plans.map((p) => effectiveRate(p) ?? Infinity));
  const minRooms = Math.min(...plans.map((p) => roomCount(p)));

  // Cost breakdown categories and timeline phases are the same fixed set
  // across every plan (from budget_agent/timeline_agent), so use the
  // first plan's keys/order as the canonical row list, then find the
  // cheapest/fastest plan per row for highlighting.
  const costCategories = Object.keys(plans[0].budget.cost_breakdown_inr || {});
  const minPerCategory = Object.fromEntries(
    costCategories.map((cat) => [cat, Math.min(...plans.map((p) => p.budget.cost_breakdown_inr?.[cat] ?? Infinity))])
  );
  const phaseNames = (plans[0].timeline?.phases || []).map((ph) => ph.phase);
  const minPerPhase = Object.fromEntries(
    phaseNames.map((name) => [
      name,
      Math.min(...plans.map((p) => p.timeline?.phases?.find((ph) => ph.phase === name)?.duration_days ?? Infinity)),
    ])
  );

  return (
    <div className="compare-card">
      <div className="compare-head">
        <h4>Comparing {plans.length} saved plans</h4>
        <button className="btn btn-ghost-dark" onClick={onClose}>
          Close comparison
        </button>
      </div>
      <div className="compare-grid" style={{ gridTemplateColumns: `repeat(${plans.length}, 1fr)` }}>
        {plans.map((p) => (
          <div className="compare-col" key={p.id}>
            <div className="compare-name">{p.name}</div>
            <div className="compare-thumb" dangerouslySetInnerHTML={{ __html: firstFloorSvg(p) }} />

            <table className="ledger-table compare-table">
              <tbody>
                <tr>
                  <td>Plot area</td>
                  <td>{p.plan.plot_area_sqft} sqft</td>
                </tr>
                <tr>
                  <td>Floors</td>
                  <td>{p.plan.floors}</td>
                </tr>
                <tr>
                  <td>Bedrooms requested</td>
                  <td>{p.plan.bedrooms_requested ?? "-"}</td>
                </tr>
                <tr className={roomCount(p) === minRooms ? "compare-best" : ""}>
                  <td>Total rooms</td>
                  <td>{roomCount(p)}</td>
                </tr>
                <tr>
                  <td>Facing</td>
                  <td>{p.plan.facing}</td>
                </tr>
                <tr>
                  <td>Region</td>
                  <td style={{ textTransform: "capitalize" }}>{p.region}</td>
                </tr>
                <tr>
                  <td>Built-up area</td>
                  <td>{p.budget.built_up_area_sqft ?? "-"} sqft</td>
                </tr>
                <tr className={effectiveRate(p) === minEffRate ? "compare-best" : ""}>
                  <td>Effective rate/sqft</td>
                  <td>{effectiveRate(p) != null ? `₹ ${effectiveRate(p).toLocaleString("en-IN")}` : "-"}</td>
                </tr>
                <tr className={p.budget.estimated_total_cost_inr === minCost ? "compare-best" : ""}>
                  <td>Est. cost</td>
                  <td>₹ {p.budget.estimated_total_cost_inr.toLocaleString("en-IN")}</td>
                </tr>
                {p.timeline && (
                  <tr className={p.timeline.total_days === minDays ? "compare-best" : ""}>
                    <td>Est. timeline</td>
                    <td>{p.timeline.total_days} days (~{p.timeline.total_weeks}w)</td>
                  </tr>
                )}
              </tbody>
            </table>

            {costCategories.length > 0 && (
              <>
                <div className="compare-subhead">Cost breakdown</div>
                <table className="ledger-table compare-table compare-table-sub">
                  <tbody>
                    {costCategories.map((cat) => (
                      <tr
                        key={cat}
                        className={p.budget.cost_breakdown_inr?.[cat] === minPerCategory[cat] ? "compare-best" : ""}
                      >
                        <td>{cat}</td>
                        <td>₹ {(p.budget.cost_breakdown_inr?.[cat] ?? 0).toLocaleString("en-IN")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            {phaseNames.length > 0 && (
              <>
                <div className="compare-subhead">Construction timeline</div>
                <table className="ledger-table compare-table compare-table-sub">
                  <tbody>
                    {phaseNames.map((name) => {
                      const ph = p.timeline?.phases?.find((x) => x.phase === name);
                      return (
                        <tr key={name} className={ph?.duration_days === minPerPhase[name] ? "compare-best" : ""}>
                          <td>{name}</td>
                          <td>{ph ? `${ph.duration_days} days` : "-"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>
            )}
          </div>
        ))}
      </div>
      <div className="disclaimer">Highlighted rows mark the lowest cost / fastest timeline among the compared plans.</div>
    </div>
  );
}

function SavedPlansPanel({ savedPlans, selectedIds, onToggleSelect, onDelete, onCompare, compareBusy }) {
  return (
    <div className="saved-plans-card">
      {savedPlans.length === 0 ? (
        <div className="empty-note">No saved plans yet — generate a plan above, then hit "Save this plan".</div>
      ) : (
        <>
          <div className="saved-plans-list">
            {savedPlans.map((p) => (
              <label className={"saved-plan-row" + (selectedIds.includes(p.id) ? " selected" : "")} key={p.id}>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(p.id)}
                  onChange={() => onToggleSelect(p.id)}
                  disabled={!selectedIds.includes(p.id) && selectedIds.length >= 3}
                />
                <div className="saved-plan-info">
                  <div className="saved-plan-name">{p.name}</div>
                  <div className="saved-plan-meta mono">
                    {p.plot_area_sqft} sqft · {p.floors}F · ₹{p.estimated_total_cost_inr?.toLocaleString("en-IN")} · {p.created_at}
                  </div>
                </div>
                <button
                  type="button"
                  className="saved-plan-delete"
                  onClick={(e) => {
                    e.preventDefault();
                    onDelete(p.id);
                  }}
                  title="Delete this saved plan"
                >
                  ✕
                </button>
              </label>
            ))}
          </div>
          <button className="btn btn-dark" onClick={onCompare} disabled={selectedIds.length < 2 || compareBusy}>
            {compareBusy ? "Loading comparison…" : `Compare selected (${selectedIds.length}/3)`}
          </button>
          {selectedIds.length === 1 && <div className="hint-text">Pick at least 2 plans to compare.</div>}
        </>
      )}
    </div>
  );
}

function AnalysisCard({ analysis }) {
  if (!analysis) return null;
  const b = analysis.buildability;
  const cramped = analysis.room_analysis.filter((r) => r.flag === "cramped");

  return (
    <div className="analysis-card">
      <div className="analysis-grid">
        <div className="analysis-stat">
          <div className="analysis-stat-label">Project type</div>
          <div className="analysis-stat-value">{analysis.project_type}</div>
        </div>
        <div className="analysis-stat">
          <div className="analysis-stat-label">Plot utilization</div>
          <div className="analysis-stat-value">{analysis.plot_utilization_percent}%</div>
        </div>
        <div className="analysis-stat">
          <div className="analysis-stat-label">Built-up area</div>
          <div className="analysis-stat-value">{analysis.built_up_area_sqft.toLocaleString("en-IN")} sqft</div>
        </div>
        <div className="analysis-stat">
          <div className="analysis-stat-label">Buildability</div>
          <div className={`analysis-stat-value ${b.buildable ? "ok-text" : "bad-text"}`}>
            {b.buildable ? "Buildable" : "Needs revision"}
          </div>
        </div>
      </div>

      <div className="banner" style={{ marginTop: 14 }}>{b.reason}</div>

      <div className="analysis-row">
        <div className="analysis-col">
          <h4>Cost summary</h4>
          <p>{analysis.cost_summary.message}</p>
        </div>
        <div className="analysis-col">
          <h4>Budget compatibility</h4>
          <p>{analysis.budget_compatibility.message}</p>
        </div>
      </div>

      <h4 style={{ marginTop: 16 }}>Room-by-room analysis</h4>
      <div className="room-analysis-list">
        {analysis.room_analysis.map((r, i) => (
          <div className={`room-analysis-item ${r.flag === "cramped" ? "flagged" : ""}`} key={i}>
            <div className="room-analysis-head">
              <span className="mono">Floor {r.floor} · {r.name}</span>
              {r.flag === "cramped" && <span className="flag-pill">check size</span>}
            </div>
            <p>{r.notes}</p>
          </div>
        ))}
      </div>

      <h4 style={{ marginTop: 16 }}>Future expansion</h4>
      <p>{analysis.future_expansion.notes}</p>

      <h4 style={{ marginTop: 16 }}>Overall assessment</h4>
      <p className="architect-note">{analysis.overall_assessment}</p>
    </div>
  );
}

export default function App() {
  // --- Feature 2: Lifestyle-first step wizard state ---
  const [wizStep, setWizStep] = useState(0);
  const [lifestyle, setLifestyle] = useState("");
  const [wizFloors, setWizFloors] = useState("");
  const [wizLand, setWizLand] = useState("1000");
  const [wizFacing, setWizFacing] = useState("East");
  const [wizBedrooms, setWizBedrooms] = useState(null);
  const [wizBathrooms, setWizBathrooms] = useState(null);
  const [wizKitchen, setWizKitchen] = useState(null);
  const [wizParking, setWizParking] = useState(null);
  const [wizPooja, setWizPooja] = useState(null);
  const [wizBalcony, setWizBalcony] = useState(null);
  const [wizSpecial, setWizSpecial] = useState("");

  function selectLifestyle(id) {
    setLifestyle(id);
    const d = LIFESTYLE_DEFAULTS[id];
    setWizBedrooms(d.bedrooms);
    setWizBathrooms(d.bathrooms);
    setWizKitchen(d.kitchen_type);
    setWizParking(d.parking);
    setWizPooja(d.pooja_room);
    setWizBalcony(d.balcony);
    setWizStep(1);
  }

  const WIZARD_STEPS = ["lifestyle", "floors", "land", "facing", "bedrooms", "bathrooms", "kitchen", "parking", "pooja", "balcony", "special"];
  function wizNext() { setWizStep((s) => Math.min(s + 1, WIZARD_STEPS.length - 1)); }
  function wizBack() { setWizStep((s) => Math.max(s - 1, 0)); }


  const [plotArea, setPlotArea] = useState("1000");
  const [floors, setFloors] = useState("1");
  const [facing, setFacing] = useState("East");
  const [bedrooms, setBedrooms] = useState(3);
  const [bathrooms, setBathrooms] = useState(2);
  const [extraRooms, setExtraRooms] = useState(["Kitchen", "Pooja room", "Parking"]);
  const [notes, setNotes] = useState("");
  const [budgetInput, setBudgetInput] = useState("");
  const [region, setRegion] = useState("default");
  const [revisionInput, setRevisionInput] = useState("");

  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const resultsRef = useRef(null);
  const formRef = useRef(null);

  // Save & Compare Plans
  const [saveName, setSaveName] = useState("");
  const [savedPlans, setSavedPlans] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [compareData, setCompareData] = useState(null);
  const [compareBusy, setCompareBusy] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");
  const [reviseMsg, setReviseMsg] = useState("");

  // 3D Floor Plan Preview — tracks which floor numbers currently show
  // the Three.js view instead of the flat SVG (lazy-mounted per floor).
  const [floors3D, setFloors3D] = useState({});

  async function refreshSavedPlans() {
    try {
      const res = await fetch(API_BASE + "/api/plans");
      const json = await res.json();
      setSavedPlans(json.plans || []);
    } catch (e) {
      // Non-fatal — saved plans list just stays empty/stale.
    }
  }

  useEffect(() => {
    refreshSavedPlans();
  }, []);

  function toggleSelectPlan(id) {
    setSelectedIds((prev) => {
      if (prev.includes(id)) return prev.filter((i) => i !== id);
      if (prev.length >= 3) return prev;
      return [...prev, id];
    });
  }

  function toggleFloor3D(floorNum) {
    setFloors3D((prev) => ({ ...prev, [floorNum]: !prev[floorNum] }));
  }

  async function callApi(path, body) {
    const res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Unknown error" }));
      throw new Error(err.error || "Request failed");
    }
    return res.json();
  }

  function toggleExtraRoom(room) {
    setExtraRooms((prev) => (prev.includes(room) ? prev.filter((r) => r !== room) : [...prev, room]));
  }

  function buildRequirementsText() {
    const roomList = extraRooms.length ? extraRooms.join(", ").toLowerCase() : "no extra rooms";
    let text = `I need a ${plotArea} sqft ${facing.toLowerCase()}-facing house, ${
      floors === "2" ? "ground plus first floor" : "single floor"
    }, with ${bedrooms} bedroom${bedrooms == 1 ? "" : "s"}, ${bathrooms} bathroom${
      bathrooms == 1 ? "" : "s"
    }, and ${roomList}.`;
    if (notes.trim()) text += ` ${notes.trim()}`;
    return text;
  }

  async function handleGenerate() {
    setError("");
    setLoading(true);
    const target_budget_inr = budgetInput.trim() ? Number(budgetInput.replace(/,/g, "")) : null;
    try {
      const res = await callApi("/api/plan", {
        requirements: buildRequirementsText(),
        session_id: SESSION_ID,
        seed: 0,
        target_budget_inr,
        region,
      });
      setData(res);
      setTimeout(() => resultsRef.current && resultsRef.current.scrollIntoView({ behavior: "smooth" }), 100);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerateWizard() {
    setError("");
    setLoading(true);
    const target_budget_inr = budgetInput.trim() ? Number(budgetInput.replace(/,/g, "")) : null;
    try {
      const res = await callApi("/api/plan/wizard", {
        session_id: SESSION_ID,
        seed: 0,
        lifestyle,
        floors: Number(wizFloors),
        plot_area_sqft: Number(wizLand),
        facing: wizFacing,
        bedrooms: Number(wizBedrooms),
        bathrooms: Number(wizBathrooms),
        kitchen_type: wizKitchen,
        parking: wizParking,
        pooja_room: wizPooja,
        balcony: wizBalcony,
        dining: true,
        special_requirements: wizSpecial,
        target_budget_inr,
        region,
      });
      setData(res);
      setTimeout(() => resultsRef.current && resultsRef.current.scrollIntoView({ behavior: "smooth" }), 100);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRegenerate() {
    setBusyAction("regen");
    setError("");
    try {
      const res = await callApi("/api/regenerate", { session_id: SESSION_ID });
      setData(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyAction("");
    }
  }

  async function handleRevise() {
    if (!revisionInput.trim()) return;
    setBusyAction("revise");
    setError("");
    setReviseMsg("");
    try {
      const res = await callApi("/api/revise", { session_id: SESSION_ID, instruction: revisionInput.trim() });
      setData(res);
      setReviseMsg(res.message || "");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyAction("");
    }
  }

  async function handleExportPdf() {
    setBusyAction("pdf");
    setError("");
    try {
      const res = await fetch(API_BASE + "/api/export/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: SESSION_ID }),
      });
      if (!res.ok) throw new Error("PDF export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "construction_plan_report.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyAction("");
    }
  }

  async function handleSavePlan() {
    setBusyAction("save");
    setError("");
    setSavedMsg("");
    try {
      const res = await callApi("/api/plans/save", { session_id: SESSION_ID, name: saveName.trim() });
      setSaveName("");
      setSavedMsg(`Saved as "${res.name}".`);
      await refreshSavedPlans();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyAction("");
    }
  }

  async function handleDeleteSavedPlan(id) {
    try {
      await fetch(API_BASE + `/api/plans/${id}`, { method: "DELETE" });
      setSelectedIds((prev) => prev.filter((i) => i !== id));
      setCompareData((prev) => (prev ? prev.filter((p) => p.id !== id) : prev));
      await refreshSavedPlans();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleComparePlans() {
    if (selectedIds.length < 2) return;
    setCompareBusy(true);
    setError("");
    try {
      const res = await callApi("/api/plans/compare", { ids: selectedIds });
      setCompareData(res.plans);
    } catch (e) {
      setError(e.message);
    } finally {
      setCompareBusy(false);
    }
  }

  function scrollToForm() {
    formRef.current && formRef.current.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <div>
      <nav className="nav">
        <div className="wrap nav-inner">
          <div className="logo">
            <div className="logo-mark">
              <svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2.2">
                <path d="M3 11l9-7 9 7" />
                <path d="M5 10v10h14V10" />
              </svg>
            </div>
            BuildPlan AI
          </div>
          <button className="nav-cta" onClick={scrollToForm}>
            New Plan
          </button>
        </div>
      </nav>

      <div className="hero-section">
        <div className="wrap">
          <div className="hero">
            <div>
              <div className="eyebrow">Multi-agent AI · Planning · Layout · Budget</div>
              <h1>
                Blueprint <span className="hl">your dream home</span> in minutes
              </h1>
              <p className="sub">
                Describe your plot, rooms and budget in plain English. Our agent pipeline drafts a Vaastu-aware floor
                plan, validates it, and prices it out floor by floor.
              </p>
              <div className="hero-actions">
                <button className="btn btn-primary" onClick={scrollToForm}>
                  Start Planning
                </button>
              </div>
            </div>
            <div className="hero-visual">
              <div className="hero-orb" />
              <div className="hero-particles">
                <span className="particle p1" />
                <span className="particle p2" />
                <span className="particle p3" />
                <span className="particle p4" />
              </div>
              <BlueprintArt />
              <div className="agent-chip chip-layout">
                <span className="chip-dot" />
                <div>
                  <div className="chip-title">Layout Agent</div>
                  <div className="chip-sub">drafting rooms…</div>
                </div>
              </div>
              <div className="agent-chip chip-budget">
                <span className="chip-dot" />
                <div>
                  <div className="chip-title">Budget Agent</div>
                  <div className="chip-sub">₹ pricing floor by floor</div>
                </div>
              </div>
              <div className="agent-chip chip-vaastu">
                <span className="chip-dot ok" />
                <div>
                  <div className="chip-title">Vaastu Check</div>
                  <div className="chip-sub">facing validated ✓</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="wrap" ref={formRef}>
        <section>
          <div className="section-head">
            <div className="kicker">Step 01</div>
            <h2>Tell us how you live, floor by floor</h2>
          </div>
          <div className="detail-card wizard-card">
            <div className="wizard-progress">
              {WIZARD_STEPS.map((s, i) => (
                <div key={s} className={"wizard-dot" + (i === wizStep ? " active" : i < wizStep ? " done" : "")} />
              ))}
            </div>

            {wizStep === 0 && (
              <div className="wizard-step">
                <label className="field-label">Who will live in this house?</label>
                <div className="wizard-option-grid">
                  {LIFESTYLES.map((l) => (
                    <button
                      type="button"
                      key={l.id}
                      className={"wizard-option" + (lifestyle === l.id ? " selected" : "")}
                      onClick={() => selectLifestyle(l.id)}
                    >
                      <div className="wizard-option-title">{l.label}</div>
                      <div className="wizard-option-blurb">{l.blurb}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {wizStep === 1 && (
              <div className="wizard-step">
                <label className="field-label">Number of floors</label>
                <div className="wizard-option-grid wizard-option-grid-narrow">
                  {["1", "2", "3", "4"].map((f) => (
                    <button
                      type="button"
                      key={f}
                      className={"wizard-option" + (wizFloors === f ? " selected" : "")}
                      onClick={() => { setWizFloors(f); wizNext(); }}
                    >
                      <div className="wizard-option-title">{f}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {wizStep === 2 && (
              <div className="wizard-step">
                <label className="field-label">Plot / land size (sqft)</label>
                <input
                  className="plain-input"
                  type="number"
                  value={wizLand}
                  onChange={(e) => setWizLand(e.target.value)}
                  placeholder="1000"
                  autoFocus
                />
              </div>
            )}

            {wizStep === 3 && (
              <div className="wizard-step">
                <label className="field-label">Facing direction</label>
                <div className="wizard-option-grid wizard-option-grid-narrow">
                  {["East", "West", "North", "South", "North-East", "South-East", "North-West", "South-West"].map((d) => (
                    <button
                      type="button"
                      key={d}
                      className={"wizard-option" + (wizFacing === d ? " selected" : "")}
                      onClick={() => setWizFacing(d)}
                    >
                      <div className="wizard-option-title">{d}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {wizStep === 4 && (
              <div className="wizard-step">
                <label className="field-label">Bedrooms</label>
                <div className="stepper">
                  <button type="button" onClick={() => setWizBedrooms((n) => Math.max(1, n - 1))}>−</button>
                  <span>{wizBedrooms}</span>
                  <button type="button" onClick={() => setWizBedrooms((n) => Math.min(10, n + 1))}>+</button>
                </div>
              </div>
            )}

            {wizStep === 5 && (
              <div className="wizard-step">
                <label className="field-label">Bathrooms</label>
                <div className="stepper">
                  <button type="button" onClick={() => setWizBathrooms((n) => Math.max(1, n - 1))}>−</button>
                  <span>{wizBathrooms}</span>
                  <button type="button" onClick={() => setWizBathrooms((n) => Math.min(10, n + 1))}>+</button>
                </div>
              </div>
            )}

            {wizStep === 6 && (
              <div className="wizard-step">
                <label className="field-label">Kitchen style</label>
                <div className="wizard-option-grid wizard-option-grid-narrow">
                  {KITCHEN_TYPES.map((k) => (
                    <button
                      type="button"
                      key={k}
                      className={"wizard-option" + (wizKitchen === k ? " selected" : "")}
                      onClick={() => setWizKitchen(k)}
                    >
                      <div className="wizard-option-title">{k}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {wizStep === 7 && (
              <div className="wizard-step">
                <label className="field-label">Parking</label>
                <div className="wizard-option-grid wizard-option-grid-narrow">
                  <button type="button" className={"wizard-option" + (wizParking === true ? " selected" : "")} onClick={() => setWizParking(true)}>
                    <div className="wizard-option-title">Yes</div>
                  </button>
                  <button type="button" className={"wizard-option" + (wizParking === false ? " selected" : "")} onClick={() => setWizParking(false)}>
                    <div className="wizard-option-title">No</div>
                  </button>
                </div>
              </div>
            )}

            {wizStep === 8 && (
              <div className="wizard-step">
                <label className="field-label">Pooja room</label>
                <div className="wizard-option-grid wizard-option-grid-narrow">
                  <button type="button" className={"wizard-option" + (wizPooja === true ? " selected" : "")} onClick={() => setWizPooja(true)}>
                    <div className="wizard-option-title">Yes</div>
                  </button>
                  <button type="button" className={"wizard-option" + (wizPooja === false ? " selected" : "")} onClick={() => setWizPooja(false)}>
                    <div className="wizard-option-title">No</div>
                  </button>
                </div>
              </div>
            )}

            {wizStep === 9 && (
              <div className="wizard-step">
                <label className="field-label">Balcony</label>
                <div className="wizard-option-grid wizard-option-grid-narrow">
                  <button type="button" className={"wizard-option" + (wizBalcony === true ? " selected" : "")} onClick={() => setWizBalcony(true)}>
                    <div className="wizard-option-title">Yes</div>
                  </button>
                  <button type="button" className={"wizard-option" + (wizBalcony === false ? " selected" : "")} onClick={() => setWizBalcony(false)}>
                    <div className="wizard-option-title">No</div>
                  </button>
                </div>
              </div>
            )}

            {wizStep === 10 && (
              <div className="wizard-step">
                <label className="field-label">Any special requirements? (optional)</label>
                <textarea
                  className="plain-input"
                  rows={3}
                  value={wizSpecial}
                  onChange={(e) => setWizSpecial(e.target.value)}
                  placeholder="e.g. wheelchair-accessible ground floor, home theatre, extra storage…"
                />
              </div>
            )}

            {wizStep > 0 && (
              <div className="wizard-nav">
                <button type="button" className="btn btn-ghost" onClick={wizBack}>Back</button>
                {wizStep < WIZARD_STEPS.length - 1 && (
                  <button
                    type="button"
                    className="btn btn-dark"
                    onClick={wizNext}
                    disabled={wizStep === 1 && !wizFloors}
                  >
                    Next
                  </button>
                )}
              </div>
            )}
          </div>
        </section>

        <section id="budget-section">
          <div className="section-head">
            <div className="kicker">Step 02</div>
            <h2>Set your target budget</h2>
          </div>
          <div style={{ marginTop: 18, maxWidth: 320 }}>
            <label className="field-label">Target budget (₹, optional)</label>
            <input
              className="plain-input"
              type="text"
              value={budgetInput}
              onChange={(e) => setBudgetInput(e.target.value)}
              placeholder="e.g. 3500000"
            />
          </div>
        </section>

        <section>
          <button
            className="btn btn-primary"
            style={{ width: "100%", padding: "16px", fontSize: 16 }}
            onClick={handleGenerateWizard}
            disabled={loading || !lifestyle || !wizFloors}
          >
            {loading ? "Generating your plan…" : "Generate Plan"}
          </button>
          {!lifestyle && <div className="banner" style={{ marginTop: 12 }}>Answer the wizard above (Step 01) to enable this.</div>}
          {error && <div className="banner bad" style={{ marginTop: 16 }}>⚠ {error}</div>}
        </section>

        {data && (
          <div ref={resultsRef}>
            <section>
              <div className="section-head">

                <div className="kicker">Result</div>
                <h2>Validation</h2>
              </div>
              {data.validation.valid ? (
                <div className="banner ok">✔ Layout passed all validation rules.</div>
              ) : (
                <div className="banner bad">
                  {data.validation.errors.map((e, i) => (
                    <div key={i}>• {e}</div>
                  ))}
                </div>
              )}
            </section>

            <section>
              <div className="section-head">
                <div className="kicker">AI Architect</div>
                <h2>AI Project Analysis</h2>
              </div>
              <AnalysisCard analysis={data.analysis} />
            </section>

            <section>
              <div className="section-head">
                <div className="kicker">Result</div>
                <h2>Floor plans</h2>
              </div>
              <div className="floors-grid">
                {Object.keys(data.svg_by_floor)
                  .sort()
                  .map((floorNum) => (
                    <div className="floor-card" key={floorNum}>
                      <div className="floor-card-head">
                        <h4>Floor {floorNum}</h4>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <button
                            type="button"
                            className="view-toggle-btn"
                            onClick={() => toggleFloor3D(floorNum)}
                          >
                            {floors3D[floorNum] ? "View 2D" : "View 3D"}
                          </button>
                          <span className="floor-tag mono">{floors3D[floorNum] ? "3D PREVIEW" : "BLUEPRINT"}</span>
                        </div>
                      </div>
                      {floors3D[floorNum] ? (
                        <FloorPlan3D layout={data.layout} floorNum={floorNum} />
                      ) : (
                        <div dangerouslySetInnerHTML={{ __html: data.svg_by_floor[floorNum] }} />
                      )}
                    </div>
                  ))}
              </div>
            </section>

            <section>
              <div className="section-head">
                <div className="kicker">Actions</div>
                <h2>Regenerate, revise or export</h2>
              </div>
              <div className="actions-card">
                <button className="btn btn-dark" onClick={handleRegenerate} disabled={busyAction !== ""}>
                  {busyAction === "regen" ? "Regenerating…" : "Regenerate layout"}
                </button>
                <div className="revise-row">
                  <input
                    className="plain-input"
                    type="text"
                    value={revisionInput}
                    onChange={(e) => setRevisionInput(e.target.value)}
                    placeholder="e.g. Kitchen konjam bigger venum / Move the kitchen near the living room"
                  />
                  <button className="btn btn-dark" onClick={handleRevise} disabled={busyAction !== ""}>
                    {busyAction === "revise" ? "Applying…" : "Apply revision"}
                  </button>
                </div>
                {reviseMsg && <div className="banner ok" style={{ width: "100%" }}>✔ {reviseMsg}</div>}
                <button className="btn btn-primary" onClick={handleExportPdf} disabled={busyAction !== ""}>
                  {busyAction === "pdf" ? "Exporting…" : "Export PDF report"}
                </button>
                <div className="revise-row">
                  <input
                    className="plain-input"
                    type="text"
                    value={saveName}
                    onChange={(e) => setSaveName(e.target.value)}
                    placeholder="Name this plan (e.g. 'Coimbatore option A')"
                  />
                  <button className="btn btn-dark" onClick={handleSavePlan} disabled={busyAction !== ""}>
                    {busyAction === "save" ? "Saving…" : "Save this plan"}
                  </button>
                </div>
                {savedMsg && <div className="banner ok" style={{ width: "100%" }}>✔ {savedMsg}</div>}
              </div>
            </section>

            <section>
              <div className="section-head">
                <div className="kicker">Result</div>
                <h2>Budget ledger</h2>
              </div>
              <BudgetLedger budget={data.budget} />
            </section>

            <section>
              <div className="section-head">
                <div className="kicker">Result</div>
                <h2>Construction timeline</h2>
              </div>
              <TimelineGantt timeline={data.timeline} />
            </section>

            <section>
              <div className="section-head">
                <div className="kicker">Result</div>
                <h2>Engineering recommendations</h2>
              </div>
              <div className="tips-card">
                <ul className="tips-list">
                  {data.recommendations.map((tip, i) => (
                    <li key={i}>{tip}</li>
                  ))}
                </ul>
              </div>
            </section>

          </div>
        )}

        <section>
          <div className="section-head">
            <div className="kicker">Save & Compare</div>
            <h2>Your saved plans</h2>
          </div>
          <SavedPlansPanel
            savedPlans={savedPlans}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelectPlan}
            onDelete={handleDeleteSavedPlan}
            onCompare={handleComparePlans}
            compareBusy={compareBusy}
          />
          {compareData && <ComparePanel plans={compareData} onClose={() => setCompareData(null)} />}
        </section>

        <footer>
          BuildPlan AI — Multi-Agent LLM + Deterministic Geometry Architecture · Preliminary planning tool, not a
          substitute for a licensed structural engineer.
        </footer>

      </div>
    </div>
  );
}

function BudgetLedger({ budget: b }) {
  const rows = Object.entries(b.cost_breakdown_inr);
  return (
    <div className="ledger-card">
      <div className="ledger-meta">
        <span>
          Built-up: <b>{b.built_up_area_sqft} sqft</b>
        </span>
        <span>
          Rate: <b>₹{b.rate_per_sqft_inr}/sqft</b>
        </span>
        {b.region && b.region !== "default" && (
          <span>
            Region: <b style={{ textTransform: "capitalize" }}>{b.region}</b> (x{b.region_multiplier})
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: "#93998A", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Estimated total
      </div>
      <div className="ledger-total">₹ {b.estimated_total_cost_inr.toLocaleString("en-IN")}</div>
      <table className="ledger-table">
        <tbody>
          {rows.map(([label, val]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>₹ {val.toLocaleString("en-IN")}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {b.material_estimate && (
        <div className="ledger-sub">
          <h4>Material-wise estimate (approx.)</h4>
          <table className="ledger-table">
            <tbody>
              {Object.entries(b.material_estimate).map(([label, qty]) => (
                <tr key={label}>
                  <td>{label}</td>
                  <td>{qty.toLocaleString("en-IN")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="disclaimer">{b.disclaimer}</div>
      <FitCallout fit={b.budget_fit} />
    </div>
  );
}