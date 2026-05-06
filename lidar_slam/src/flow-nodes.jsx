/* eslint-disable */
// Floating process-flow node graph. Renders the architecture: shared memory,
// readers, the SLAM main thread, the loop-closure thread, queues, and iSAM2.
// Nodes light up + edges animate based on the active stage.

const { useMemo: useMemoF } = React;

// Compute an SVG path for an edge between two nodes' anchor points.
function edgePath(a, b) {
  const ax = a.x + a.w / 2;
  const ay = a.y + a.h / 2;
  const bx = b.x + b.w / 2;
  const by = b.y + b.h / 2;
  // Pick a side: largest delta wins.
  const dx = bx - ax, dy = by - ay;
  let sx, sy, ex, ey;
  if (Math.abs(dx) > Math.abs(dy) * 0.6) {
    sx = ax + Math.sign(dx) * a.w / 2;
    sy = ay;
    ex = bx - Math.sign(dx) * b.w / 2;
    ey = by;
  } else {
    sx = ax;
    sy = ay + Math.sign(dy) * a.h / 2;
    ex = bx;
    ey = by - Math.sign(dy) * b.h / 2;
  }
  // Bezier control points
  const c1x = sx + (ex - sx) * 0.5;
  const c1y = sy;
  const c2x = sx + (ex - sx) * 0.5;
  const c2y = ey;
  return `M ${sx} ${sy} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${ex} ${ey}`;
}

function FlowNodes({ stage }) {
  const W = 1080, H = 680;
  const nodeMap = useMemoF(() => {
    const m = {};
    for (const n of window.NODES) m[n.id] = n;
    return m;
  }, []);

  const activeSet = new Set(stage.active || []);
  const edgeSet = new Set((stage.edges || []).map(([a,b]) => `${a}::${b}`));

  // Build the static set of *all* edges so the architecture is always visible
  // (just dim by default, accent when this stage uses them).
  const ALL_EDGES = useMemoF(() => [
    ["producer", "shm-lidar"],
    ["producer", "shm-odom"],
    ["producer", "sem-lidar"],
    ["producer", "sem-odom"],
    ["shm-lidar", "lidar-reader"],
    ["sem-lidar", "lidar-reader"],
    ["shm-odom", "odom-reader"],
    ["sem-odom", "odom-reader"],
    ["lidar-reader", "scan-queue"],
    ["odom-reader", "ring-buffer"],
    ["scan-queue", "main-loop"],
    ["ring-buffer", "main-loop"],
    ["main-loop", "undistort"],
    ["undistort", "voxel"],
    ["voxel", "submap"],
    ["submap", "icp"],
    ["voxel", "icp"],
    ["icp", "main-loop"],
    ["main-loop", "kf-store"],
    ["kf-store", "submap"],
    ["main-loop", "isam"],
    ["isam", "kf-store"],
    ["main-loop", "loop-q-in"],
    ["loop-q-in", "loop-worker"],
    ["kf-store", "loop-worker"],
    ["loop-worker", "loop-q-out"],
    ["loop-q-out", "main-loop"],
    ["shm-lidar", "consumer"],
    ["shm-odom", "consumer"],
    ["sem-lidar", "consumer"],
    ["sem-odom", "consumer"],
  ], []);

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`}
         preserveAspectRatio="xMidYMid meet"
         style={{ display: "block" }}>
      <defs>
        <pattern id="dotgrid" width="20" height="20" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.7" fill="oklch(0.30 0.013 248)" />
        </pattern>
        <marker id="arrowhead-soft" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="5" markerHeight="5" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="oklch(0.40 0.013 248)" />
        </marker>
        <marker id="arrowhead-cyan" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="5" markerHeight="5" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--cyan)" />
        </marker>
        <marker id="arrowhead-amber" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="5" markerHeight="5" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--amber)" />
        </marker>

        {/* Animated dash flow */}
        <style>{`
          .edge-flow { stroke-dasharray: 6 6; animation: dashflow 1.2s linear infinite; }
          @keyframes dashflow { to { stroke-dashoffset: -24; } }
          .node-pulse { animation: nodepulse 1.6s ease-in-out infinite; }
          @keyframes nodepulse {
            0%, 100% { filter: drop-shadow(0 0 0 oklch(0.80 0.13 220 / 0)); }
            50%      { filter: drop-shadow(0 0 6px oklch(0.80 0.13 220 / 0.5)); }
          }
        `}</style>
      </defs>

      {/* Bg dot grid */}
      <rect width={W} height={H} fill="url(#dotgrid)" opacity="0.5" />

      {/* Group regions (faint) */}
      <RegionLabel x={20} y={50} w={350} h={500} label="IPC · POSIX shm + sem" />
      <RegionLabel x={385} y={50} w={310} h={420} label="reader threads · 50 Hz / 10 Hz" />
      <RegionLabel x={710} y={50} w={350} h={420} label="SLAM main thread" />
      <RegionLabel x={710} y={485} w={350} h={170} label="loop-closure thread" stroke="var(--amber-d)" />

      {/* All edges (dim) */}
      {ALL_EDGES.map(([a, b], i) => {
        const A = nodeMap[a], B = nodeMap[b];
        if (!A || !B) return null;
        const isActive = edgeSet.has(`${a}::${b}`);
        const isLoop = (a.startsWith("loop") || b.startsWith("loop"));
        return (
          <path key={i} d={edgePath(A, B)}
                fill="none"
                stroke={isActive ? (isLoop ? "var(--amber)" : "var(--cyan)") : "oklch(0.32 0.014 248)"}
                strokeWidth={isActive ? 1.8 : 1}
                opacity={isActive ? 1 : 0.55}
                className={isActive ? "edge-flow" : ""}
                markerEnd={isActive ? (isLoop ? "url(#arrowhead-amber)" : "url(#arrowhead-cyan)") : "url(#arrowhead-soft)"} />
        );
      })}

      {/* Nodes */}
      {window.NODES.map((n) => {
        const isActive = activeSet.has(n.id);
        const groupColor = window.GROUP_STYLE[n.group] || {};
        const isLoopGroup = n.group === "loop";
        const accent = isLoopGroup ? "var(--amber)" : "var(--cyan)";
        const stroke = isActive ? accent : groupColor.stroke;
        const fill = isActive
          ? (isLoopGroup ? "oklch(0.82 0.13 75 / 0.12)" : "oklch(0.80 0.13 220 / 0.10)")
          : groupColor.fill;
        return (
          <g key={n.id}
             className={isActive && n.emphasis ? "node-pulse" : ""}>
            <rect x={n.x} y={n.y} width={n.w} height={n.h}
                  rx="6" ry="6"
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={isActive ? 1.6 : 1} />
            {isActive && (
              <rect x={n.x} y={n.y} width="3" height={n.h}
                    rx="2" ry="2" fill={accent} />
            )}
            <text x={n.x + n.w/2} y={n.y + 20}
                  textAnchor="middle"
                  fontFamily="Inter, sans-serif"
                  fontSize="12" fontWeight="600"
                  fill={isActive ? "var(--text-0)" : "var(--text-1)"}>
              {n.label}
            </text>
            {n.h >= 44 && (
              <text x={n.x + n.w/2} y={n.y + 36}
                    textAnchor="middle"
                    fontFamily="JetBrains Mono, monospace"
                    fontSize="9.5"
                    fill={isActive ? "var(--text-1)" : "var(--text-3)"}>
                {n.sub}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function RegionLabel({ x, y, w, h, label, stroke = "oklch(0.30 0.014 248)" }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="10"
            fill="oklch(0.18 0.014 248 / 0.4)"
            stroke={stroke} strokeWidth="0.8" strokeDasharray="3 4" />
      <text x={x + 12} y={y + 18}
            fontFamily="JetBrains Mono, monospace" fontSize="10"
            letterSpacing="0.5"
            fill="var(--text-3)">
        {label}
      </text>
    </g>
  );
}

window.FlowNodes = FlowNodes;
