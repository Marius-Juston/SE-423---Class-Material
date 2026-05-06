/* eslint-disable */
// Robot + LiDAR scene visualization, driven by the precomputed SLAM cache.
// All keyframe poses, scans, loop pairs, and the optimized trajectory come
// from data/slam_cache.json so the visuals match real SLAM math.

const { useMemo: useMemoR } = React;

// World matches lidar_slam_2d.py::_build_world
function buildWorld() {
  const segs = [];
  const poly = (pts) => {
    for (let i = 0; i < pts.length - 1; i++) segs.push([pts[i], pts[i+1]]);
  };
  poly([[-12,-12],[12,-12],[12,12],[-12,12],[-12,-12]]);
  poly([[-3,-3],[3,-3],[3,3],[-3,3],[-3,-3]]);
  poly([[-10,0],[-6,0]]);
  poly([[6,-6],[9,-3]]);
  poly([[-8,6],[-5,6],[-5,9]]);
  poly([[4,8],[8,8]]);
  return segs;
}
const WORLD = buildWorld();

function raycast(ox, oy, ang, walls, maxR) {
  const dx = Math.cos(ang), dy = Math.sin(ang);
  let best = maxR;
  for (const [a, b] of walls) {
    const sx = b[0]-a[0], sy = b[1]-a[1];
    const det = dx*(-sy) - dy*(-sx);
    if (Math.abs(det) < 1e-9) continue;
    const rx = a[0]-ox, ry = a[1]-oy;
    const t = (rx*(-sy) - ry*(-sx)) / det;
    const u = (dx*ry - dy*rx) / det;
    if (t >= 0 && u >= 0 && u <= 1 && t < best) best = t;
  }
  return best;
}

function makeRng(seed) {
  let s = seed | 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) | 0;
    return ((s >>> 0) / 0xffffffff) - 0.5;
  };
}

function simulateScan(pose, walls, opts={}) {
  const { nBeams=120, fov=Math.PI*4/3, maxR=10, noise=0.04, seed=1 } = opts;
  const rand = makeRng(seed);
  const [x, y, th] = pose;
  const pts = [];
  for (let i = 0; i < nBeams; i++) {
    const a = -fov/2 + (i/(nBeams-1)) * fov;
    let r = raycast(x, y, th + a, walls, maxR);
    if (r < maxR - 1e-3) {
      r += rand() * noise;
      pts.push([r*Math.cos(a), r*Math.sin(a)]);
    }
  }
  return pts;
}

function projectScan(scan, pose) {
  const [x, y, th] = pose;
  const c = Math.cos(th), s = Math.sin(th);
  return scan.map(([px, py]) => [x + c*px - s*py, y + s*px + c*py]);
}

function voxelDS(pts, cell) {
  const buckets = new Map();
  for (const [x, y] of pts) {
    const kx = Math.floor(x/cell), ky = Math.floor(y/cell);
    const key = kx + "," + ky;
    const b = buckets.get(key);
    if (b) { b[0] += x; b[1] += y; b[2]++; }
    else buckets.set(key, [x, y, 1]);
  }
  const out = [];
  for (const [, v] of buckets) out.push([v[0]/v[2], v[1]/v[2]]);
  return out;
}

function RobotScene({ stage, step, totalSteps, drift, cache }) {
  const noise = drift?.lidar_noise ?? 0.015;
  const W = 460, H = 460;
  const SCALE = W / 26;
  const wx = (x) => W/2 + x * SCALE;
  const wy = (y) => H/2 - y * SCALE;

  if (!cache) {
    return <div style={{ width: W, height: H }} />;
  }

  // Clamp step into the cached trajectory and find the active KF (the
  // most-recent keyframe at or before the current trajectory step).
  const trajStep = Math.min(step, cache.nTraj - 1);
  const pose = cache.gtTraj[trajStep];
  const odomPose = cache.odomTraj[trajStep];

  const activeKfIdx = useMemoR(() => {
    let last = 0;
    for (let k = 0; k < cache.kfTrajIdx.length; k++) {
      if (cache.kfTrajIdx[k] <= trajStep) last = k;
      else break;
    }
    return last;
  }, [cache, trajStep]);

  const isLoopClosed = stage.scene.mode === "loop-closed";
  // Trajectory to draw: optimized cached poses (loop-closed) vs. drifted odom.
  const slamPath = useMemoR(() => {
    const out = [];
    if (isLoopClosed) {
      // Use optimized KF poses, interpolating between them along ground-truth
      // trajectory shape so we have a smooth line.
      for (let k = 0; k <= activeKfIdx; k++) out.push([cache.kfOpt[k][0], cache.kfOpt[k][1]]);
      // tail to current step (linear extension from last KF using odom)
      const lastKfTraj = cache.kfTrajIdx[activeKfIdx];
      if (trajStep > lastKfTraj) {
        const last = cache.kfOpt[activeKfIdx];
        const odomLast = cache.odomTraj[lastKfTraj];
        const odomNow = cache.odomTraj[trajStep];
        out.push([last[0] + (odomNow[0]-odomLast[0]),
                  last[1] + (odomNow[1]-odomLast[1])]);
      }
    } else {
      for (let i = 0; i <= trajStep; i++) out.push([cache.odomTraj[i][0], cache.odomTraj[i][1]]);
    }
    return out;
  }, [cache, trajStep, activeKfIdx, isLoopClosed]);

  const gtPath = useMemoR(() => cache.gtTraj.slice(0, trajStep + 1).map(p => [p[0], p[1]]),
    [cache, trajStep]);

  // Current scan (live raycast for visual freshness)
  const scanLocal = useMemoR(() =>
    simulateScan(pose, WORLD, { nBeams: 120, seed: trajStep, noise }),
    [trajStep, noise]);
  const scanWorld = useMemoR(() => projectScan(scanLocal, pose), [scanLocal, pose]);

  // Distorted scan for undistort viz.
  const distorted = useMemoR(() => {
    if (stage.scene.mode !== "undistort") return null;
    const prev = cache.gtTraj[Math.max(0, trajStep - 3)] || pose;
    const out = [];
    for (let i = 0; i < scanLocal.length; i++) {
      const u = i / Math.max(scanLocal.length - 1, 1);
      const x = prev[0] + u*(pose[0]-prev[0]);
      const y = prev[1] + u*(pose[1]-prev[1]);
      const th = prev[2] + u*(pose[2]-prev[2]);
      const [px, py] = scanLocal[i];
      const c = Math.cos(th), s = Math.sin(th);
      out.push([x + c*px - s*py, y + s*px + c*py]);
    }
    return out;
  }, [stage.scene.mode, scanLocal, trajStep, cache, pose]);

  const voxelized = useMemoR(() => {
    if (stage.scene.mode !== "voxel") return null;
    return voxelDS(scanWorld, 0.5);
  }, [stage.scene.mode, scanWorld]);

  // Submap = last 6 keyframe scans, projected via cached KF poses.
  const submap = useMemoR(() => {
    if (!["submap","icp","keyframe","loop-search","loop-icp","loop-closed"].includes(stage.scene.mode))
      return null;
    const start = Math.max(0, activeKfIdx - 5);
    const out = [];
    for (let k = start; k <= activeKfIdx; k++) {
      const kfPose = isLoopClosed ? cache.kfOpt[k] : cache.kfGt[k];
      const proj = projectScan(cache.kfScans[k], kfPose);
      out.push(...proj);
    }
    return voxelDS(out, 0.18);
  }, [stage.scene.mode, activeKfIdx, cache, isLoopClosed]);

  // ICP correspondences: real nearest-neighbor between current scan and submap.
  const corr = useMemoR(() => {
    if (stage.scene.mode !== "icp" || !submap || !submap.length) return null;
    const lines = [];
    const sample = scanWorld.filter((_, i) => i % 6 === 0);
    for (const [sx, sy] of sample) {
      let best = null, bestD = Infinity;
      for (const [tx, ty] of submap) {
        const d = (sx-tx)**2 + (sy-ty)**2;
        if (d < bestD) { bestD = d; best = [tx, ty]; }
      }
      if (best && bestD < 1) lines.push([[sx, sy], best]);
    }
    return lines;
  }, [stage.scene.mode, scanWorld, submap]);

  // Loop candidates: real KD-tree-style search using ODOMETRY poses (what the
  // SLAM thread sees), filtered by loop edges from the cached pose-graph.
  const loopCands = useMemoR(() => {
    if (!["loop-search","loop-icp","loop-closed"].includes(stage.scene.mode)) return null;
    const cur = cache.kfOdom[activeKfIdx];
    const minGap = cache.config.minGap;
    const radius = cache.config.loopRadius;
    const out = [];
    for (let k = 0; k < activeKfIdx - minGap; k++) {
      const kp = cache.kfOdom[k];
      const d = Math.hypot(kp[0]-cur[0], kp[1]-cur[1]);
      const dth = Math.abs(Math.atan2(Math.sin(cur[2]-kp[2]), Math.cos(cur[2]-kp[2])));
      if (d < radius && dth < cache.config.headingLimit) {
        out.push({ k, p: kp, d });
      }
    }
    out.sort((a,b) => a.d - b.d);
    return out.slice(0, 4);
  }, [stage.scene.mode, activeKfIdx, cache]);

  // The loop edge actually selected by the cached SLAM (if any matches activeKfIdx).
  const matchedLoop = useMemoR(() => {
    if (!loopCands) return null;
    for (const [j, i] of cache.loopEdges) {
      if (j === activeKfIdx) {
        const kp = isLoopClosed ? cache.kfOpt[i] : cache.kfOdom[i];
        return { i, p: kp };
      }
    }
    return null;
  }, [activeKfIdx, cache, isLoopClosed, loopCands]);

  // Current-pose marker location for loop viz: in odometry frame for search,
  // in optimized frame after loop-closed.
  const markerPose = isLoopClosed
    ? (activeKfIdx < cache.kfOpt.length ? cache.kfOpt[activeKfIdx] : odomPose)
    : odomPose;

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
      <defs>
        <pattern id="grid" width={SCALE} height={SCALE} patternUnits="userSpaceOnUse">
          <path d={`M ${SCALE} 0 L 0 0 0 ${SCALE}`} fill="none" stroke="oklch(0.24 0.013 248)" strokeWidth="0.5" />
        </pattern>
      </defs>

      <rect x="0" y="0" width={W} height={H} fill="var(--bg-1)" />
      <rect x="0" y="0" width={W} height={H} fill="url(#grid)" />

      <line x1={wx(-13)} y1={wy(0)} x2={wx(13)} y2={wy(0)} stroke="oklch(0.30 0.014 248)" strokeWidth="0.6" />
      <line x1={wx(0)} y1={wy(-13)} x2={wx(0)} y2={wy(13)} stroke="oklch(0.30 0.014 248)" strokeWidth="0.6" />

      {WORLD.map(([a, b], i) => (
        <line key={i}
          x1={wx(a[0])} y1={wy(a[1])} x2={wx(b[0])} y2={wy(b[1])}
          stroke="oklch(0.55 0.013 248)" strokeWidth="1.4" strokeLinecap="round" />
      ))}

      {/* Ground truth (dashed soft) */}
      {gtPath.length > 1 && (
        <polyline
          points={gtPath.map(([x,y]) => `${wx(x)},${wy(y)}`).join(" ")}
          fill="none" stroke="var(--text-3)" strokeWidth="1" strokeDasharray="3 3" />
      )}

      {/* SLAM trajectory */}
      {slamPath.length > 1 && (
        <polyline
          points={slamPath.map(([x,y]) => `${wx(x)},${wy(y)}`).join(" ")}
          fill="none"
          stroke={isLoopClosed ? "var(--green)" : "var(--cyan)"}
          strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      )}

      {/* Past keyframes */}
      {cache.kfOdom.slice(0, activeKfIdx + 1).map(([x,y], i) => {
        const drawn = isLoopClosed ? cache.kfOpt[i] : cache.kfOdom[i];
        return (
          <circle key={i} cx={wx(drawn[0])} cy={wy(drawn[1])} r="2.2"
                  fill={isLoopClosed ? "oklch(0.70 0.10 150)" : "oklch(0.65 0.10 220)"}
                  opacity="0.85" />
        );
      })}

      {/* Submap — high-contrast warm amber so it pops against the cyan scan */}
      {submap && submap.map(([x,y], i) => (
        <circle key={i} cx={wx(x)} cy={wy(y)} r="1.6"
                fill="oklch(0.78 0.16 60)" opacity="0.95" />
      ))}

      {/* Voxel grid overlay */}
      {voxelized && (
        <g>
          {voxelized.map(([x,y], i) => (
            <rect key={i}
                  x={wx(x) - SCALE*0.25} y={wy(y) - SCALE*0.25}
                  width={SCALE*0.5} height={SCALE*0.5}
                  fill="oklch(0.80 0.13 220 / 0.30)"
                  stroke="oklch(0.80 0.13 220 / 0.85)" strokeWidth="0.6" />
          ))}
        </g>
      )}

      {distorted && distorted.map(([x,y], i) => (
        <circle key={i} cx={wx(x)} cy={wy(y)} r="1.3"
                fill="oklch(0.74 0.14 25)" opacity="0.55" />
      ))}

      {corr && corr.map(([s, t], i) => (
        <line key={i}
              x1={wx(s[0])} y1={wy(s[1])} x2={wx(t[0])} y2={wy(t[1])}
              stroke="oklch(0.85 0.15 90)" strokeWidth="0.8" opacity="0.85" />
      ))}

      {/* Loop search radius — drawn at the SLAM-believed pose (odom) */}
      {stage.scene.mode === "loop-search" && (
        <>
          <circle cx={wx(markerPose[0])} cy={wy(markerPose[1])} r={cache.config.loopRadius * SCALE}
                  fill="oklch(0.82 0.13 75 / 0.06)"
                  stroke="oklch(0.82 0.13 75)" strokeWidth="1" strokeDasharray="3 3" />
          {loopCands && loopCands.map((c, i) => (
            <g key={i}>
              <circle cx={wx(c.p[0])} cy={wy(c.p[1])} r="6"
                      fill="oklch(0.82 0.13 75 / 0.22)"
                      stroke="oklch(0.82 0.13 75)" strokeWidth="1.2" />
              <text x={wx(c.p[0])} y={wy(c.p[1]) - 9}
                    textAnchor="middle" fontSize="9"
                    fontFamily="JetBrains Mono, monospace"
                    fill="oklch(0.82 0.13 75)">
                X({c.k})
              </text>
            </g>
          ))}
        </>
      )}

      {/* Loop validate / closed — line to the matched keyframe */}
      {(stage.scene.mode === "loop-icp" || isLoopClosed) && matchedLoop && (
        <line x1={wx(markerPose[0])} y1={wy(markerPose[1])}
              x2={wx(matchedLoop.p[0])} y2={wy(matchedLoop.p[1])}
              stroke="oklch(0.82 0.13 75)" strokeWidth="1.8"
              strokeDasharray={isLoopClosed ? "0" : "4 3"} />
      )}

      {/* LiDAR fan */}
      {stage.scene.mode !== "boot" && (
        <g opacity="0.55">
          {scanLocal.filter((_, i) => i % 8 === 0).map(([px, py], i) => {
            const c = Math.cos(pose[2]), s = Math.sin(pose[2]);
            const ex = pose[0] + c*px - s*py;
            const ey = pose[1] + s*px + c*py;
            return (
              <line key={i}
                    x1={wx(pose[0])} y1={wy(pose[1])}
                    x2={wx(ex)} y2={wy(ey)}
                    stroke="var(--cyan)" strokeWidth="0.4" opacity="0.5" />
            );
          })}
        </g>
      )}

      {/* Current scan in world frame (cyan) */}
      {(stage.scene.mode !== "boot" && stage.scene.mode !== "voxel") && scanWorld.map(([x,y], i) => (
        <circle key={i} cx={wx(x)} cy={wy(y)} r="1.3"
                fill="var(--cyan)" opacity="0.95" />
      ))}

      <Robot x={wx(pose[0])} y={wy(pose[1])} th={pose[2]} scale={SCALE} />

      {/* Compass */}
      <g transform={`translate(${W - 50}, ${H - 40})`}>
        <line x1="0" y1="0" x2="20" y2="0" stroke="var(--rose)" strokeWidth="1.2" />
        <line x1="0" y1="0" x2="0" y2="-20" stroke="var(--green)" strokeWidth="1.2" />
        <text x="24" y="3" fill="var(--rose)" fontSize="9" fontFamily="JetBrains Mono, monospace">x</text>
        <text x="-3" y="-22" fill="var(--green)" fontSize="9" fontFamily="JetBrains Mono, monospace">y</text>
      </g>
    </svg>
  );
}

function Robot({ x, y, th, scale }) {
  const r = scale * 0.42;
  const dirX = x + Math.cos(-th) * r * 0.85;
  const dirY = y + Math.sin(-th) * r * 0.85;
  return (
    <g>
      <circle cx={x} cy={y} r={r * 1.6} fill="oklch(0.80 0.13 220 / 0.08)" />
      <circle cx={x} cy={y} r={r} fill="var(--bg-3)" stroke="var(--cyan)" strokeWidth="1.4" />
      <line x1={x} y1={y} x2={dirX} y2={dirY} stroke="var(--cyan)" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx={x} cy={y} r={r * 0.45} fill="var(--cyan)" />
      <circle cx={x} cy={y} r={r * 0.20} fill="var(--bg-0)" />
    </g>
  );
}

window.RobotScene = RobotScene;
