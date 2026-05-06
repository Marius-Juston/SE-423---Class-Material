/* eslint-disable */
// Main app: 4-pane layout — flow nodes (top-left), code panel (right),
// robot scene + factor graph (bottom-left), timeline (bottom strip).

const { useState, useEffect, useRef } = React;

function App() {
  const [pySource, setPySource] = useState(null);
  const [slamCache, setSlamCache] = useState(null);
  const [stageIdx, setStageIdx] = useState(0);
  const [step, setStep] = useState(20);
  const [playing, setPlaying] = useState(false);

// Control the 't' parameter (0.0 to 1.0) that the generate_cache.py script uses.
  const [severityT, setSeverityT] = useState(0.3);

  // Derive the 4 noise parameters exactly as the Python script does.
  const drift = React.useMemo(() => ({
    k_d: 0.5 * severityT,
    k_th: 0.4 * severityT,
    arw: 0.05 * severityT,
    lidar_noise: 0.10 * severityT
  }), [severityT]);

  // Map the noise model onto the cached drift levels: encoder distance noise
  // dominates xy drift. xy ≈ k_d * sqrt(step_dist), step_dist≈0.012 m at 50 Hz.
  const combinedSeverity = 
      (drift.k_d * 1.0) + 
      (drift.k_th * 1.0) + 
      (drift.arw * 10.0) + 
      (drift.lidar_noise * 5.0);

  const stages = window.STAGES;
  const stage = stages[stageIdx];

  // Load the python source.
  useEffect(() => {
    fetch("lidar_slam_2d.py")
      .then(r => r.text())
      .then(setPySource)
      .catch(() => setPySource("# (failed to load source)\n"));
  }, []);

  // Load the precomputed SLAM cache (per-drift snapshots).
  useEffect(() => {
    fetch("data/slam_cache.json")
      .then(r => r.json())
      .then(setSlamCache)
      .catch(() => setSlamCache({ levels: [], byLevel: {} }));
  }, []);

  // Snap driftXY to the nearest cached level.
  const activeCache = React.useMemo(() => {
    if (!slamCache || !slamCache.levels?.length) return null;
    const lvls = slamCache.levels;
    let best = lvls[0], bestD = Infinity;
    for (const l of lvls) {
      const d = Math.abs(l - combinedSeverity);
      if (d < bestD) { bestD = d; best = l; }
    }
    return slamCache.byLevel[best.toFixed(4)];
  }, [slamCache, combinedSeverity]);

  const totalSteps = activeCache?.nTraj || 200;

  // Auto-advance step a little so each stage looks "live" when you click it.
  useEffect(() => {
    if (!activeCache) return;
    const T = activeCache.nTraj;
    if (stage.id === "boot" && step > 5) setStep(2);
    if ((stage.id === "loop-search" || stage.id === "loop-icp" || stage.id === "loop-inject")
        && step < T * 0.55) setStep(Math.floor(T * 0.85));
    if (stage.id === "keyframe" && step < 30) setStep(60);
  }, [stageIdx, activeCache]);

  if (!pySource || !slamCache) {
    return (
      <div style={{
        height: "100vh", display: "flex",
        alignItems: "center", justifyContent: "center",
        color: "var(--text-2)",
        fontFamily: "JetBrains Mono, monospace",
      }}>
        loading lidar_slam_2d.py …
      </div>
    );
  }

  return (
    <div style={{
      height: "100vh", width: "100vw",
      display: "grid",
      gridTemplateRows: "auto 1fr auto",
      gap: 12,
      padding: 12,
      background: "var(--bg-0)",
    }}>
      <Header stage={stage} stageIdx={stageIdx} totalStages={stages.length} />

      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.35fr) minmax(0, 0.95fr)",
        gap: 12,
        minHeight: 0,
      }}>
        {/* Left column: flow nodes (top) + scene/graph (bottom) */}
        <div style={{
          display: "grid",
          gridTemplateRows: "minmax(0, 1.05fr) minmax(0, 1fr)",
          gap: 12,
          minHeight: 0,
        }}>
          <Panel title="Process Flow" eyebrow="threads · queues · IPC">
            <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
              <window.FlowNodes stage={stage} />
            </div>
          </Panel>

          <div style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
            gap: 12,
            minHeight: 0,
          }}>
            <Panel title="Robot · LiDAR" eyebrow="2D map · 240° fan">
              <div style={{
                flex: 1, minHeight: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                padding: 8,
              }}>
                <window.RobotScene stage={stage} step={step} totalSteps={totalSteps} drift={drift} cache={activeCache} />
              </div>
              <SceneLegend stage={stage} />
            </Panel>

            <Panel title="Subgraph · iSAM2" eyebrow="pose nodes · between-factors">
              <div style={{
                flex: 1, minHeight: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                padding: 8,
              }}>
                <window.FactorGraph stage={stage} step={step} cache={activeCache} />
              </div>
              <StageDetail stage={stage} />
            </Panel>
          </div>
        </div>

        {/* Right column: code panel */}
        <Panel title={stage.title} eyebrow={stage.subtitle} accent>
          <window.CodePanel source={pySource} stage={stage} />
        </Panel>
      </div>

      <DriftPanel severityT={severityT} setSeverityT={setSeverityT} drift={drift} />

      <window.Timeline
        stages={stages}
        stageIdx={stageIdx} setStageIdx={setStageIdx}
        step={step} setStep={setStep}
        totalSteps={totalSteps}
        playing={playing} setPlaying={setPlaying}
      />
    </div>
  );
}

function Header({ stage, stageIdx, totalStages }) {
  const isLoop = stage.id.startsWith("loop");
  const accent = isLoop ? "var(--amber)" : "var(--cyan)";
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "6px 4px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: "var(--bg-2)", border: "1px solid var(--line)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <svg width="14" height="14" viewBox="0 0 14 14">
            <circle cx="7" cy="7" r="2.5" fill="var(--cyan)" />
            <circle cx="7" cy="7" r="6" fill="none" stroke="var(--cyan)" strokeWidth="1" strokeDasharray="2 2" opacity="0.7" />
          </svg>
        </div>
        <div>
          <div style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10.5, color: "var(--text-3)", letterSpacing: 0.5,
          }}>
            REAL-TIME 2D LIDAR SLAM · SHM-IPC · iSAM2
          </div>
          <div style={{
            fontFamily: "Inter, sans-serif",
            fontSize: 14, fontWeight: 600, color: "var(--text-0)",
            marginTop: 1,
          }}>
            lidar_slam_2d.py — process walkthrough
          </div>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <KeyValueChip k="stage" v={`${String(stageIdx+1).padStart(2,"0")}/${String(totalStages).padStart(2,"0")}`} />
        <KeyValueChip k="step" v={stage.id} />
        <div style={{
          width: 8, height: 8, borderRadius: 4, background: accent,
          boxShadow: `0 0 8px ${accent}`,
        }} />
      </div>
    </div>
  );
}

function KeyValueChip({ k, v }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      fontFamily: "JetBrains Mono, monospace", fontSize: 10.5,
      padding: "5px 10px",
      background: "var(--bg-2)", border: "1px solid var(--line)",
      borderRadius: 5,
    }}>
      <span style={{ color: "var(--text-3)" }}>{k}</span>
      <span style={{ color: "var(--text-0)" }}>{v}</span>
    </div>
  );
}

function Panel({ title, eyebrow, children, accent }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column",
      background: "var(--bg-1)",
      border: `1px solid ${accent ? "oklch(0.32 0.05 220)" : "var(--line)"}`,
      borderRadius: 8,
      minHeight: 0, minWidth: 0,
      overflow: "hidden",
    }}>
      {title && (
        <div style={{
          display: "flex", alignItems: "baseline", justifyContent: "space-between",
          padding: "8px 14px",
          borderBottom: "1px solid var(--line)",
          background: "var(--bg-2)",
          flexShrink: 0,
        }}>
          <div style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10.5, color: "var(--text-3)", letterSpacing: 0.5,
            textTransform: "uppercase",
          }}>
            {title}
          </div>
          {eyebrow && (
            <div style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 10, color: "var(--text-3)",
            }}>
              {eyebrow}
            </div>
          )}
        </div>
      )}
      {children}
    </div>
  );
}

function SceneLegend({ stage }) {
  const items = [];
  const m = stage.scene.mode;
  items.push({ c: "var(--cyan)", t: "current scan" });
  if (["submap","icp","keyframe","loop-search","loop-icp","loop-closed"].includes(m)) {
    items.push({ c: "oklch(0.65 0.08 220)", t: "submap" });
  }
  if (m === "icp") items.push({ c: "var(--amber)", t: "ICP correspondence" });
  if (m === "voxel") items.push({ c: "oklch(0.80 0.13 220 / 0.7)", t: "voxel cell", sq: true });
  if (m === "undistort") items.push({ c: "var(--rose)", t: "uncompensated" });
  if (m === "loop-search") items.push({ c: "var(--amber)", t: "loop candidate" });
  if (m === "loop-closed") items.push({ c: "var(--green)", t: "optimized path" });
  return (
    <div style={{
      borderTop: "1px solid var(--line)",
      padding: "8px 12px",
      display: "flex", flexWrap: "wrap", gap: 12,
      fontFamily: "JetBrains Mono, monospace",
      fontSize: 10, color: "var(--text-2)",
    }}>
      {items.map((it, i) => (
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {it.sq
            ? <span style={{ width: 8, height: 8, background: it.c, border: "1px solid var(--cyan)" }} />
            : <span style={{ width: 8, height: 8, borderRadius: 4, background: it.c }} />}
          {it.t}
        </span>
      ))}
    </div>
  );
}

function StageDetail({ stage }) {
  return (
    <div style={{
      borderTop: "1px solid var(--line)",
      padding: "10px 14px 12px",
      background: "var(--bg-1)",
    }}>
      <div style={{
        fontFamily: "Inter, sans-serif",
        fontSize: 12, lineHeight: 1.55,
        color: "var(--text-1)",
        textWrap: "pretty",
      }}>
        {stage.summary}
      </div>
      {stage.metrics && stage.metrics.length > 0 && (
        <div style={{
          marginTop: 10,
          display: "flex", flexWrap: "wrap", gap: 6,
        }}>
          {stage.metrics.map((m, i) => (
            <div key={i} style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "3px 8px",
              border: "1px solid var(--line)",
              borderRadius: 4,
              background: "var(--bg-2)",
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 10,
            }}>
              <span style={{ color: "var(--text-3)" }}>{m.k}</span>
              <span style={{ color: "var(--cyan)" }}>{m.v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DriftPanel({ severityT, setSeverityT, drift }) {
  const reset = () => setSeverityT(0.3);
  
  // Approximate cumulative drift
  const totalDist = 64;
  const xyStd = (drift.k_d * Math.sqrt(totalDist)).toFixed(2);
  const thStd = (drift.k_th * Math.sqrt(2 * Math.PI * 2) +
                 drift.arw * Math.sqrt(totalDist / 0.6)).toFixed(2);
                 
  return (
    <div style={{
      position: "fixed",
      right: 24, bottom: 132,
      width: 270,
      background: "var(--bg-1)",
      border: "1px solid var(--line)",
      borderRadius: 8,
      padding: "12px 14px",
      boxShadow: "0 6px 18px oklch(0 0 0 / 0.4)",
      zIndex: 50,
      fontFamily: "Inter, sans-serif",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 10,
      }}>
        <div style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10.5, color: "var(--text-3)",
          letterSpacing: 0.5, textTransform: "uppercase",
        }}>
          Producer noise model
        </div>
        <button onClick={reset} style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 9.5,
          background: "transparent", border: "1px solid var(--line)",
          color: "var(--text-2)", padding: "2px 7px", borderRadius: 4,
          cursor: "pointer",
        }}>reset</button>
      </div>

      {/* MASTER SLIDER */}
      <DriftSlider label="Overall Severity" unit="%"
                   min={0} max={1} step={0.01}
                   value={severityT} onChange={(e) => setSeverityT(parseFloat(e.target.value))}
                   display={Math.round(severityT * 100)} 
                   master={true} />

      <div style={{ height: 1, background: "var(--line)", margin: "12px 0 10px 0" }} />

      {/* READ-ONLY INDICATORS */}
      <DriftSlider label="k_d  encoder dist" unit="m / √m"
                   min={0} max={0.5} step={0.005}
                   value={drift.k_d} readOnly
                   display={drift.k_d.toFixed(3)} />
      <DriftSlider label="k_θ  gyro scale" unit="rad / √rad"
                   min={0} max={0.4} step={0.005}
                   value={drift.k_th} readOnly
                   display={drift.k_th.toFixed(3)} />
      <DriftSlider label="ARW  gyro walk" unit="rad / √s"
                   min={0} max={0.05} step={0.0005}
                   value={drift.arw} readOnly
                   display={drift.arw.toFixed(4)} />
      <DriftSlider label="lidar noise" unit="m σ"
                   min={0} max={0.10} step={0.002}
                   value={drift.lidar_noise} readOnly
                   display={drift.lidar_noise.toFixed(3)} />

      <div style={{
        marginTop: 8, padding: "6px 8px",
        background: "var(--bg-2)", border: "1px solid var(--line)",
        borderRadius: 4,
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10, color: "var(--text-2)",
        display: "flex", flexDirection: "column", gap: 3,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ color: "var(--text-3)" }}>est. xy drift (1σ, 2 laps)</span>
          <span style={{ color: drift.k_d > 0.25 ? "var(--rose)" : "var(--cyan)" }}>
            ~{xyStd} m
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ color: "var(--text-3)" }}>est. θ drift (1σ)</span>
          <span style={{ color: drift.k_th > 0.20 ? "var(--rose)" : "var(--cyan)" }}>
            ~{thStd} rad
          </span>
        </div>
      </div>
    </div>
  );
}

function DriftSlider({ label, unit, value, onChange, min, max, step, display, readOnly, master }) {
  return (
    <div style={{ marginBottom: 9, opacity: readOnly ? 0.6 : 1 }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "baseline",
        marginBottom: 3,
      }}>
        <span style={{ 
          fontSize: 11, 
          color: master ? "var(--text-0)" : "var(--text-1)",
          fontWeight: master ? 600 : 400 
        }}>{label}</span>
        <span style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10, color: master ? "var(--amber)" : "var(--cyan)",
        }}>
          {display} <span style={{ color: "var(--text-3)" }}>{unit}</span>
        </span>
      </div>
      <input type="range"
             min={min} max={max} step={step} value={value}
             onChange={readOnly ? () => {} : onChange}
             style={{
               width: "100%", 
               accentColor: master ? "var(--amber)" : "var(--text-3)",
               height: readOnly ? 2 : (master ? 6 : 4),
               pointerEvents: readOnly ? "none" : "auto",
             }} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
