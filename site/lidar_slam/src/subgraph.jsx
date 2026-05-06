/* eslint-disable */
// Factor graph / iSAM2 subgraph visualization, driven by the SLAM cache.
// Nodes are real cached keyframe poses (odom or optimized); loop edges are
// the actual cached loop closures. The "isam" mode highlights nodes whose
// optimized pose differs most from the odom-only estimate.

const { useMemo: useMemoG } = React;

function FactorGraph({ stage, step, cache }) {
  const W = 460, H = 240;
  const PAD_L = 28, PAD_R = 28, PAD_T = 60, PAD_B = 50;

  if (!cache) return <div style={{ width: W, height: H }} />;

  const isLoopClosed = stage.graph.mode === "loop-closed";
  const useOpt = isLoopClosed;

  // Active KF cap based on trajectory step.
  const activeKfIdx = useMemoG(() => {
    let last = 0;
    for (let k = 0; k < cache.kfTrajIdx.length; k++) {
      if (cache.kfTrajIdx[k] <= step) last = k;
      else break;
    }
    return last;
  }, [cache, step]);

  const nodes = useMemoG(() => {
    const out = [];
    for (let k = 0; k <= activeKfIdx; k++) {
      const pos = useOpt ? cache.kfOpt[k] : cache.kfOdom[k];
      out.push({ idx: k, pos });
    }
    return out;
  }, [cache, activeKfIdx, useOpt]);

  if (stage.graph.mode === "empty" || nodes.length === 0) {
    return (
      <div style={{
        width: W, height: H,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "var(--text-3)", fontFamily: "JetBrains Mono, monospace", fontSize: 11,
        border: "1px dashed var(--line)", borderRadius: 6,
      }}>
        factor graph — no keyframes yet
      </div>
    );
  }

  const xs = nodes.map(n => n.pos[0]);
  const ys = nodes.map(n => n.pos[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const sx = (W - PAD_L - PAD_R) / Math.max(maxX - minX, 0.1);
  const sy = (H - PAD_T - PAD_B) / Math.max(maxY - minY, 0.1);
  const s = Math.min(sx, sy);
  const cx = (x) => PAD_L + (x - minX) * s + ((W - PAD_L - PAD_R) - (maxX - minX) * s) / 2;
  const cy = (y) => H - PAD_B - (y - minY) * s - ((H - PAD_T - PAD_B) - (maxY - minY) * s) / 2;

  const lastIdx = activeKfIdx;
  const newKf = stage.graph.mode === "kf-add";
  const isamMode = stage.graph.mode === "isam";

  // Active loop edges: anything from cache with j ≤ activeKfIdx, plus an
  // emphasized "current" pair if any edge ends at lastIdx.
  const activeLoops = cache.loopEdges.filter(([j, i]) => j <= activeKfIdx);
  const currentLoop = activeLoops.find(([j]) => j === lastIdx);
  const showLoop = stage.graph.mode === "loop-search" || stage.graph.mode === "loop-closed";

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
      <text x={PAD_L} y={20} fontSize="11" fontWeight="600" fill="var(--text-1)"
            fontFamily="Inter, sans-serif">
        Factor Graph · iSAM2
      </text>
      <text x={PAD_L} y={36} fontSize="10" fill="var(--text-3)"
            fontFamily="JetBrains Mono, monospace">
        {nodes.length} keyframes · {activeLoops.length} loop edges · {useOpt ? "optimized" : "odometry"}
      </text>

      <g transform={`translate(${W - 200}, 12)`} fontFamily="JetBrains Mono, monospace" fontSize="9">
        <circle cx="6" cy="6" r="3" fill="var(--cyan)" />
        <text x="14" y="9" fill="var(--text-2)">X(k) pose</text>
        <line x1="80" y1="6" x2="100" y2="6" stroke="var(--text-2)" strokeWidth="1.2" />
        <text x="106" y="9" fill="var(--text-2)">odom</text>
        <line x1="140" y1="6" x2="160" y2="6" stroke="var(--amber)" strokeWidth="1.2" strokeDasharray="2 2" />
        <text x="166" y="9" fill="var(--text-2)">loop</text>
      </g>

      {/* Odometry edges along KF chain */}
      {nodes.slice(0, -1).map((n, i) => {
        const next = nodes[i+1];
        const ax = cx(n.pos[0]), ay = cy(n.pos[1]);
        const bx = cx(next.pos[0]), by = cy(next.pos[1]);
        const isNewest = newKf && i === nodes.length - 2;
        return (
          <line key={i} x1={ax} y1={ay} x2={bx} y2={by}
                stroke={isNewest ? "var(--cyan)" : "oklch(0.5 0.013 248)"}
                strokeWidth={isNewest ? 1.8 : 1.1} />
        );
      })}

      {/* All discovered loop edges so far */}
      {showLoop && activeLoops.map(([j, i], k) => {
        const a = nodes[i], b = nodes[j];
        if (!a || !b) return null;
        const ax = cx(a.pos[0]), ay = cy(a.pos[1]);
        const bx = cx(b.pos[0]), by = cy(b.pos[1]);
        const mx = (ax+bx)/2, my = (ay+by)/2 - 14;
        const closed = isLoopClosed;
        const isCurrent = currentLoop && j === currentLoop[0] && i === currentLoop[1];
        return (
          <path key={k}
                d={`M ${ax} ${ay} Q ${mx} ${my} ${bx} ${by}`}
                fill="none"
                stroke="var(--amber)"
                strokeWidth={isCurrent ? 2.2 : (closed ? 1.6 : 1.2)}
                strokeDasharray={closed ? "0" : "4 3"}
                opacity={isCurrent ? 1 : 0.7} />
        );
      })}

      {/* Nodes */}
      {nodes.map((n, k) => {
        const x = cx(n.pos[0]), y = cy(n.pos[1]);
        const last = k === lastIdx;
        const inLoop = activeLoops.some(([j, i]) => j === k || i === k);
        // Relinearized = nodes whose optimized pose differs from odom by > thresh
        let relinearized = false;
        if (isamMode && k > 0) {
          const od = cache.kfOdom[k], op = cache.kfOpt[k];
          relinearized = Math.hypot(od[0]-op[0], od[1]-op[1]) > 0.05;
        }
        let fill = "var(--bg-3)", stroke = "oklch(0.55 0.13 220)", r = 5.5;
        if (last) { fill = "var(--cyan)"; stroke = "var(--cyan)"; r = 7; }
        if (inLoop && showLoop) { fill = "var(--amber)"; stroke = "var(--amber)"; r = 7; }
        if (relinearized && !last) { fill = "oklch(0.30 0.10 220)"; stroke = "var(--cyan)"; r = 6.5; }
        return (
          <g key={k}>
            {(last || (inLoop && showLoop)) && (
              <circle cx={x} cy={y} r={r + 5}
                      fill={inLoop && showLoop ? "oklch(0.82 0.13 75 / 0.18)" : "oklch(0.80 0.13 220 / 0.18)"} />
            )}
            <circle cx={x} cy={y} r={r} fill={fill} stroke={stroke} strokeWidth="1.3" />
            {(last || (inLoop && showLoop) || (k % 5 === 0)) && (
              <text x={x} y={y - r - 4}
                    textAnchor="middle" fontSize="8.5"
                    fontFamily="JetBrains Mono, monospace"
                    fill={last ? "var(--cyan)" : ((inLoop && showLoop) ? "var(--amber)" : "var(--text-3)")}>
                X({k})
              </text>
            )}
          </g>
        );
      })}

      <text x={PAD_L} y={H - 12} fontSize="9.5"
            fontFamily="JetBrains Mono, monospace" fill="var(--text-3)">
        {isamMode && "isam.update() · relinearizing affected vars"}
        {newKf && "+1 BetweenFactor X(j-1) → X(j) (odom-noisy)"}
        {stage.graph.mode === "loop-search" && `KD-tree query · ${activeLoops.length} active loop edges`}
        {isLoopClosed && `+robust BetweenFactor · graph re-optimized`}
        {stage.graph.mode === "trace" && "main thread holds the lock · single-writer"}
      </text>
    </svg>
  );
}

window.FactorGraph = FactorGraph;
