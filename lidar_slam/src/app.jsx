/* eslint-disable */
(() => {
// Main app: 4-pane layout — flow nodes (top-left), code panel (right),
// robot scene + factor graph (bottom-left), timeline (bottom strip).

const { useState, useEffect, useMemo } = React;

// Heading drift model of the producer: σ_θ² = k_θ²·Θ + ARW²·T, where Θ is the
// total angle turned and T the elapsed time (see ProducerSim._odom_loop).
function totalTurn(gtTraj, upTo) {
  let s = 0;
  for (let i = 1; i <= upTo; i++) s += Math.abs(Math.atan2(
    Math.sin(gtTraj[i][2] - gtTraj[i-1][2]), Math.cos(gtTraj[i][2] - gtTraj[i-1][2])));
  return s;
}

function App() {
  const [pySource, setPySource] = useState(null);
  const [index, setIndex] = useState(null);         // data/index.json
  const [levelData, setLevelData] = useState({});   // file → level_XX.json
  const [loadError, setLoadError] = useState(null);
  const [stageIdx, setStageIdx] = useState(0);
  const [step, setStep] = useState(20);
  const [playing, setPlaying] = useState(false);
  // Noise level index into index.levels (the 12 cached levels, t = i/11).
  const [levelIdx, setLevelIdx] = useState(3);

  const stages = window.STAGES;
  const stage = stages[stageIdx];

  // Load the python source.
  useEffect(() => {
    fetch("lidar_slam_2d.py")
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.text(); })
      .then(setPySource)
      .catch((e) => setPySource(`# (failed to load lidar_slam_2d.py: ${e.message})\n`));
  }, []);

  // Load the level index once.
  useEffect(() => {
    fetch("data/index.json")
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setIndex)
      .catch((e) => setLoadError(`could not load data/index.json (${e.message})`));
  }, []);

  const level = index ? index.levels[Math.min(levelIdx, index.levels.length - 1)] : null;

  // Lazily load the selected level's file.
  useEffect(() => {
    if (!level || levelData[level.file]) return;
    let cancelled = false;
    fetch(`data/${level.file}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => { if (!cancelled) setLevelData((m) => ({ ...m, [level.file]: d })); })
      .catch((e) => { if (!cancelled) setLoadError(`could not load data/${level.file} (${e.message})`); });
    return () => { cancelled = true; };
  }, [level, levelData]);

  const activeCache = useMemo(() => {
    if (!index || !level || !levelData[level.file]) return null;
    return {
      ...levelData[level.file],
      nTraj: index.nTraj,
      gtTraj: index.gtTraj,
      config: index.config,
      noise: level.noise,
      stats: level.stats,
    };
  }, [index, level, levelData]);

  const totalSteps = index?.nTraj || 200;

  // Jump to a representative step when a stage is selected.
  useEffect(() => {
    if (!activeCache) return;
    const T = activeCache.nTraj;
    if (stage.id === "boot" && step > 5) setStep(2);
    if (stage.id === "keyframe" && step < 30) setStep(60);
    if (stage.id === "undistort") {
      // A corner, where the robot turns in place and distortion is visible.
      const g = activeCache.gtTraj;
      for (let i = Math.max(step, 5); i < T; i++) {
        if (Math.abs(g[i][2] - g[i-5][2]) > 0.05 && Math.abs(g[i][2] - g[i-5][2]) < 1) { setStep(i); break; }
      }
    }
    if (stage.id.startsWith("loop")) {
      // Snap to the trajectory step of a keyframe with an accepted loop edge,
      // preferring the one closest to 85 % of the run.
      const edges = activeCache.loopEdges;
      if (edges.length) {
        const target = T * 0.85;
        let best = null;
        for (const e of edges) {
          const s = activeCache.kfTrajIdx[e[0]];
          if (best === null || Math.abs(s - target) < Math.abs(best - target)) best = s;
        }
        const kfAt = (st) => { let l = 0; activeCache.kfTrajIdx.forEach((t, k) => { if (t <= st) l = k; }); return l; };
        if (!edges.some((e) => e[0] === kfAt(step))) setStep(best);
      } else if (step < T * 0.55) setStep(Math.floor(T * 0.85));
    }
  }, [stageIdx, activeCache]);

  // Actual errors at the current step (odometry and SLAM estimate vs truth).
  const liveErr = useMemo(() => {
    if (!activeCache) return null;
    const c = activeCache, i = Math.min(step, c.nTraj - 1);
    const g = c.gtTraj[i], o = c.odomTraj[i];
    let k = 0;
    for (let n = 0; n < c.kfTrajIdx.length && c.kfTrajIdx[n] <= i; n++) k = n;
    const e = c.kfOptOnline[k], og = c.kfGt[k];
    const angErr = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
    return {
      odomXY: Math.hypot(o[0] - g[0], o[1] - g[1]),
      odomTh: angErr(o[2], g[2]),
      slamXY: Math.hypot(e[0] - og[0], e[1] - og[1]),
      kf: k,
    };
  }, [activeCache, step]);

  const thetaModel = useMemo(() => {
    if (!index || !level) return null;
    const Theta = totalTurn(index.gtTraj, index.nTraj - 1);
    const T = (index.nTraj - 1) / index.config.hz;
    const { k_th, arw } = level.noise;
    return { sigma: Math.sqrt(k_th * k_th * Theta + arw * arw * T), Theta, T };
  }, [index, level]);

  if (loadError) {
    return (
      <div role="alert" style={{
        height: "100vh", display: "flex", flexDirection: "column", gap: 8,
        alignItems: "center", justifyContent: "center",
        color: "var(--amber)", fontFamily: "JetBrains Mono, monospace", padding: 24, textAlign: "center",
      }}>
        <div>Failed to load the SLAM data: {loadError}.</div>
        <div style={{ color: "var(--text-2)" }}>
          Serve this folder over HTTP (e.g. <code>python3 -m http.server</code>) and reload.
        </div>
      </div>
    );
  }

  if (!pySource || !index) {
    return (
      <div style={{
        height: "100vh", display: "flex",
        alignItems: "center", justifyContent: "center",
        color: "var(--text-2)",
        fontFamily: "JetBrains Mono, monospace",
      }}>
        loading lidar_slam_2d.py and data/index.json …
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
                flex: 1, minHeight: 0, minWidth: 0, overflow: "hidden",
                display: "flex", alignItems: "center", justifyContent: "center",
                padding: 8,
              }}>
                {activeCache
                  ? <window.RobotScene stage={stage} step={step} cache={activeCache} />
                  : <div style={{ color: "var(--text-3)", fontFamily: "JetBrains Mono, monospace" }}>loading {level.file} …</div>}
              </div>
              <SceneLegend stage={stage} />
            </Panel>

            <Panel title="Subgraph · iSAM2" eyebrow="pose nodes · between-factors">
              <div style={{
                flex: 1, minHeight: 0, minWidth: 0, overflow: "hidden",
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

      <DriftPanel index={index} levelIdx={levelIdx} setLevelIdx={setLevelIdx}
                  level={level} liveErr={liveErr} thetaModel={thetaModel} />

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
  const closed = m === "loop-closed";
  items.push({ c: "var(--cyan)", t: "robot + scan @ SLAM estimate" });
  items.push({ c: "var(--text-2)", t: "truth (dashed)", ring: true });
  if (!closed) items.push({ c: "var(--cyan)", t: "SLAM path", line: true });
  if (!closed) items.push({ c: "oklch(0.74 0.14 25)", t: "raw odometry", line: true });
  if (["submap","icp","keyframe","loop-search","loop-icp","loop-closed"].includes(m)) {
    items.push({ c: "oklch(0.78 0.16 60)", t: "submap" });
  }
  if (m === "icp") items.push({ c: "oklch(0.85 0.15 90)", t: "point → local line (PCA), 3σ gate", line: true });
  if (m === "voxel") items.push({ c: "oklch(0.80 0.13 220 / 0.7)", t: "voxel cell (drawn 0.5 m)", sq: true });
  if (m === "undistort") items.push({ c: "oklch(0.74 0.14 25)", t: "uncompensated sweep" });
  if (m === "loop-search") items.push({ c: "var(--amber)", t: "candidates tried" });
  if (m === "loop-icp" || closed) items.push({ c: "var(--rose)", t: "wrong loop", line: true });
  if (closed) items.push({ c: "var(--green)", t: "final optimized path", line: true });
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
            : it.line
              ? <span style={{ width: 12, height: 2, background: it.c }} />
              : it.ring
                ? <span style={{ width: 8, height: 8, borderRadius: 4, border: `1px dashed ${it.c}` }} />
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

function DriftPanel({ index, levelIdx, setLevelIdx, level, liveErr, thetaModel }) {
  const n = index.levels.length;
  const reset = () => setLevelIdx(3);
  const { k_d, k_th, arw, lidar } = level.noise;
  const st = level.stats;
  const Row = ({ k, v, warn }) => (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
      <span style={{ color: "var(--text-3)" }}>{k}</span>
      <span style={{ color: warn ? "var(--rose)" : "var(--cyan)" }}>{v}</span>
    </div>
  );

  return (
    <div style={{
      position: "fixed",
      right: 24, bottom: 132,
      width: 290,
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

      {/* MASTER SLIDER — snaps to the precomputed levels t = i/(n-1) */}
      <DriftSlider label={`Overall severity · level ${levelIdx + 1}/${n}`} unit="%"
                   min={0} max={n - 1} step={1}
                   value={levelIdx} onChange={(e) => setLevelIdx(parseInt(e.target.value, 10))}
                   display={Math.round(level.t * 100)}
                   master={true} />

      <div style={{ height: 1, background: "var(--line)", margin: "12px 0 10px 0" }} />

      {/* READ-ONLY INDICATORS: k_d = 0.5t, k_θ = 0.4t, ARW = 0.05t, lidar = 0.10t */}
      <DriftSlider label="k_d  encoder distance" unit="m / √m"
                   min={0} max={0.5} step={0.005} value={k_d} readOnly
                   display={k_d.toFixed(3)} />
      <DriftSlider label="k_θ  heading random walk" unit="rad / √rad"
                   min={0} max={0.4} step={0.005} value={k_th} readOnly
                   display={k_th.toFixed(3)} />
      <DriftSlider label="ARW  gyro angle random walk" unit="rad / √s"
                   min={0} max={0.05} step={0.0005} value={arw} readOnly
                   display={arw.toFixed(4)} />
      <DriftSlider label="lidar range noise" unit="m σ"
                   min={0} max={0.10} step={0.002} value={lidar} readOnly
                   display={lidar.toFixed(3)} />

      <div style={{
        marginTop: 8, padding: "6px 8px",
        background: "var(--bg-2)", border: "1px solid var(--line)",
        borderRadius: 4,
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10, color: "var(--text-2)",
        display: "flex", flexDirection: "column", gap: 3,
      }}>
        <Row k={`model θ drift 1σ (full run, Θ=${thetaModel.Theta.toFixed(1)} rad)`}
             v={`${thetaModel.sigma.toFixed(3)} rad`} warn={thetaModel.sigma > 0.5} />
        {liveErr && <Row k="odometry xy error @ step" v={`${liveErr.odomXY.toFixed(2)} m`} warn={liveErr.odomXY > 1} />}
        {liveErr && <Row k="odometry θ error @ step" v={`${liveErr.odomTh.toFixed(3)} rad`} warn={liveErr.odomTh > 0.2} />}
        {liveErr && <Row k={`SLAM X(${liveErr.kf}) error (when added)`} v={`${liveErr.slamXY.toFixed(2)} m`} warn={liveErr.slamXY > 1} />}
        <Row k="final KF RMSE: odom → SLAM" v={`${st.odomRmse.toFixed(2)} → ${st.optRmse.toFixed(2)} m`} />
        <Row k="final ICP gate 3σ (adaptive)" v={`${(3 * st.icpSigma).toFixed(2)} m`} />
        <Row k="loops accepted (wrong vs truth)" v={`${st.nLoops} (${st.nWrongLoops})`} warn={st.nWrongLoops > 0} />
        {st.gtAssisted && <Row k="loop search" v="GT-assisted fallback" warn />}
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
})();
