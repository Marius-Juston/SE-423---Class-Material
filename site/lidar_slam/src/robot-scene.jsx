/* eslint-disable */
(() => {
// Robot + LiDAR scene visualization, driven by the precomputed SLAM data
// (data/index.json + data/level_XX.json from generate_cache.py). Keyframe
// poses, keyframe scans, loop candidates / edges and trajectories come from
// that replay of lidar_slam_2d.py; only the *current* scan between keyframes
// is ray-cast here in the browser.
//
// Everything SLAM-related is drawn where SLAM believes it is: the robot, its
// scan and the submap use the SLAM estimate, so misalignment with the walls
// is real estimation error. The true pose is shown as a dashed ghost.

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

// ---- SE(2) helpers (poses are [x, y, θ]) ----------------------------------
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
function compose(a, b) {
  const c = Math.cos(a[2]), s = Math.sin(a[2]);
  return [a[0] + c*b[0] - s*b[1], a[1] + s*b[0] + c*b[1], wrap(a[2] + b[2])];
}
function between(a, b) {            // a⁻¹ ⊕ b
  const c = Math.cos(a[2]), s = Math.sin(a[2]);
  const dx = b[0] - a[0], dy = b[1] - a[1];
  return [c*dx + s*dy, -s*dx + c*dy, wrap(b[2] - a[2])];
}
function sincTerms(w) {             // sin(w)/w, (1 - cos w)/w
  if (Math.abs(w) < 1e-6) return [1 - w*w/6, w/2];
  return [Math.sin(w)/w, (1 - Math.cos(w))/w];
}
function interpSE2(a, b, u) {       // a ⊕ Exp(u · Log(a⁻¹ ⊕ b))
  const [dx, dy, w] = between(a, b);
  const [A, B] = sincTerms(w);
  const det = A*A + B*B;
  const rx = (A*dx + B*dy) / det, ry = (-B*dx + A*dy) / det;
  const [A2, B2] = sincTerms(u*w);
  return compose(a, [u*(A2*rx - B2*ry), u*(B2*rx + A2*ry), u*w]);
}
function transformPts(pts, pose) {
  const [x, y, th] = pose;
  const c = Math.cos(th), s = Math.sin(th);
  return pts.map(([px, py]) => [x + c*px - s*py, y + s*px + c*py]);
}

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

// Seeded standard-normal generator (LCG + Box-Muller).
function makeGauss(seed) {
  let s = (seed | 0) || 1;
  const uni = () => {
    s = (Math.imul(s, 1664525) + 1013904223) | 0;
    return ((s >>> 0) + 0.5) / 4294967296;          // (0, 1)
  };
  return () => Math.sqrt(-2 * Math.log(uni())) * Math.cos(2 * Math.PI * uni());
}

// Simulated sweep like lidar_slam_2d._simulate_scan: beam k fires at angle
// a_k; `beamPose(k)` gives the pose it is cast from. Returns points in each
// beam's own sensor frame, plus the beam index of each point.
function simulateScan(beamPose, opts) {
  const { nBeams, fov, maxR = 10, sigma, seed } = opts;
  const gauss = makeGauss(seed);
  const pts = [], idx = [];
  for (let k = 0; k < nBeams; k++) {
    const a = -fov/2 + (k/(nBeams-1)) * fov;
    const [x, y, th] = beamPose(k);
    let r = raycast(x, y, th + a, WORLD, maxR);
    if (r < maxR - 1e-3) {
      r += gauss() * sigma;
      pts.push([r*Math.cos(a), r*Math.sin(a)]);
      idx.push(k);
    }
  }
  return { pts, idx };
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

// k nearest target points, closest first (brute force; the submap is small).
function kNearest(p, pts, k) {
  const best = [];                       // [dist², index], sorted
  for (let i = 0; i < pts.length; i++) {
    const d = (p[0]-pts[i][0])**2 + (p[1]-pts[i][1])**2;
    if (best.length < k || d < best[best.length-1][0]) {
      best.push([d, i]); best.sort((a, b) => a[0] - b[0]);
      if (best.length > k) best.pop();
    }
  }
  return best;
}

// Line normal at a point: smallest-eigenvalue eigenvector of the covariance
// of its neighbours (PCA), like lidar_slam_2d.estimate_normals.
function pcaNormal(nbrs) {
  let mx = 0, my = 0;
  for (const [x, y] of nbrs) { mx += x; my += y; }
  mx /= nbrs.length; my /= nbrs.length;
  let sxx = 0, sxy = 0, syy = 0;
  for (const [x, y] of nbrs) { sxx += (x-mx)**2; sxy += (x-mx)*(y-my); syy += (y-my)**2; }
  const ang = 0.5 * Math.atan2(2*sxy, sxx - syy);      // major-axis direction
  return [-Math.sin(ang), Math.cos(ang)];
}

const VOXEL_DRAW = 0.5;          // drawn voxel size (m) — see data.jsx text

function RobotScene(props) {
  const W = 460, H = 460;
  // Guard before any hooks run (hooks live in RobotSceneInner).
  if (!props.cache) return <div style={{ width: W, height: H }} />;
  return <RobotSceneInner {...props} />;
}

function RobotSceneInner({ stage, step, cache }) {
  const W = 460, H = 460;
  const SCALE = W / 26;
  const wx = (x) => W/2 + x * SCALE;
  const wy = (y) => H/2 - y * SCALE;
  const cfg = cache.config;
  const mode = stage.scene.mode;
  const isLoopClosed = mode === "loop-closed";
  const sigma = cache.noise.lidar;

  const trajStep = Math.min(step, cache.nTraj - 1);
  const gtPose = cache.gtTraj[trajStep];

  // Most-recent keyframe at or before the current trajectory step.
  const activeKfIdx = useMemoR(() => {
    let last = 0;
    for (let k = 0; k < cache.kfTrajIdx.length; k++) {
      if (cache.kfTrajIdx[k] <= trajStep) last = k;
      else break;
    }
    return last;
  }, [cache, trajStep]);

  // Keyframe estimates to draw: as estimated when each keyframe was added,
  // or the final optimized estimates in the loop-closed stage.
  const kfEst = isLoopClosed ? cache.kfOpt : cache.kfOptOnline;

  // SLAM belief of the current pose: last keyframe estimate ⊕ odometry
  // motion since that keyframe (opt_now = opt_kf ⊕ (odom_kf⁻¹ ⊕ odom_now)).
  const estPose = useMemoR(() => {
    const kfStep = cache.kfTrajIdx[activeKfIdx];
    const dOdom = between(cache.odomTraj[kfStep], cache.odomTraj[trajStep]);
    return compose(kfEst[activeKfIdx], dOdom);
  }, [cache, kfEst, activeKfIdx, trajStep]);

  const slamPath = useMemoR(() => {
    const out = [];
    for (let k = 0; k <= activeKfIdx; k++) out.push([kfEst[k][0], kfEst[k][1]]);
    out.push([estPose[0], estPose[1]]);
    return out;
  }, [kfEst, activeKfIdx, estPose]);

  const odomPath = useMemoR(() => {
    if (isLoopClosed) return null;
    const out = [];
    for (let i = 0; i <= trajStep; i += 5) out.push([cache.odomTraj[i][0], cache.odomTraj[i][1]]);
    out.push([cache.odomTraj[trajStep][0], cache.odomTraj[trajStep][1]]);
    return out;
  }, [cache, trajStep, isLoopClosed]);

  const gtPath = useMemoR(() => {
    const out = [];
    for (let i = 0; i <= trajStep; i += 5) out.push([cache.gtTraj[i][0], cache.gtTraj[i][1]]);
    out.push([gtPose[0], gtPose[1]]);
    return out;
  }, [cache, trajStep, gtPose]);

  // Current sweep. In the undistort stage each beam is cast from the true
  // pose at its own firing time (sweep = cfg.lidarEvery odom steps = 100 ms),
  // exactly like ProducerSim; otherwise from the end-of-sweep pose.
  const distort = mode === "undistort";
  const sweep = useMemoR(() => {
    const n = cfg.nBeams, per = cfg.lidarEvery;
    const i0 = Math.max(0, trajStep - per);
    const beamFrac = (k) => k / (n - 1);
    const poseAtFrac = (traj, u) => {
      const f = i0 + u * (trajStep - i0);
      const lo = Math.min(Math.floor(f), cache.nTraj - 2);
      return interpSE2(traj[lo], traj[lo + 1], f - lo);
    };
    const beamPose = distort ? (k) => poseAtFrac(cache.gtTraj, beamFrac(k)) : () => gtPose;
    const { pts, idx } = simulateScan(beamPose, {
      nBeams: n, fov: cfg.lidarFov, sigma, seed: trajStep + 1 });
    if (!distort) return { raw: pts, comp: pts };
    // Compensation as in RealtimeLidarSLAM._undistort: odometry pose at the
    // beam time, re-expressed in the end-of-sweep odometry frame.
    const odomEnd = cache.odomTraj[trajStep];
    const comp = pts.map((p, m) => {
      const rel = between(odomEnd, poseAtFrac(cache.odomTraj, beamFrac(idx[m])));
      return transformPts([p], rel)[0];
    });
    return { raw: pts, comp };
  }, [cache, cfg, trajStep, sigma, distort, gtPose]);

  const scanWorld = useMemoR(() => transformPts(sweep.comp, estPose), [sweep, estPose]);
  const rawWorld = useMemoR(
    () => (distort ? transformPts(sweep.raw, estPose) : null), [sweep, estPose, distort]);

  const voxelized = useMemoR(() => {
    if (mode !== "voxel") return null;
    return voxelDS(scanWorld, VOXEL_DRAW);
  }, [mode, scanWorld]);

  // Submap = last cfg.submapSize keyframe scans placed at their estimates
  // and merged with the real voxel size, like LidarSLAM2D.get_submap.
  const submap = useMemoR(() => {
    if (!["submap","icp","keyframe","loop-search","loop-icp","loop-closed"].includes(mode))
      return null;
    const start = Math.max(0, activeKfIdx - cfg.submapSize + 1);
    const out = [];
    for (let k = start; k <= activeKfIdx; k++) {
      out.push(...transformPts(cache.kfScans[k], kfEst[k]));
    }
    return voxelDS(out, cfg.voxelSize);
  }, [mode, activeKfIdx, cache, cfg, kfEst]);

  // ICP correspondences, point-to-line like pl_icp_2d: each sampled scan
  // point is paired with its nearest submap point q (if within the 3σ gate)
  // and joined to its perpendicular foot on q's local line (PCA normal of
  // q's 6 nearest submap points). σ here is the level's final adaptive σ.
  const gate = 3 * cache.stats.icpSigma;
  const corr = useMemoR(() => {
    if (mode !== "icp" || !submap || submap.length < 6) return null;
    const lines = [];
    scanWorld.forEach((p, n) => {
      if (n % 4 !== 0) return;
      const [[d2, iq]] = kNearest(p, submap, 1);
      if (Math.sqrt(d2) > gate) return;
      const q = submap[iq];
      const nb = kNearest(q, submap, 6).map(([, i]) => submap[i]);
      const [nx, ny] = pcaNormal(nb);
      const r = (p[0]-q[0])*nx + (p[1]-q[1])*ny;           // point-to-line residual
      const foot = [p[0] - r*nx, p[1] - r*ny];
      const tx = -ny * 0.25, ty = nx * 0.25;                // ±25 cm of the line
      lines.push([p, foot, [q[0]-tx, q[1]-ty], [q[0]+tx, q[1]+ty]]);
    });
    return lines;
  }, [mode, scanWorld, submap, gate]);

  // Loop candidates actually tried by search_loop_closure for this keyframe,
  // at the estimates used during that search; the search centre is the
  // keyframe's own estimate at that time (kfOptOnline).
  const searchCentre = cache.kfOptOnline[activeKfIdx];
  const loopCands = useMemoR(() => {
    if (!["loop-search","loop-icp","loop-closed"].includes(mode)) return null;
    return (cache.kfCands[activeKfIdx] || []).map(([k, x, y]) => ({ k, p: [x, y] }));
  }, [mode, activeKfIdx, cache]);

  // The loop edge accepted for this keyframe (if any).
  const matchedLoop = useMemoR(() => {
    if (!loopCands) return null;
    for (const e of cache.loopEdges) {
      if (e[0] === activeKfIdx) {
        const i = e[1];
        const cand = loopCands.find((c) => c.k === i);
        const p = isLoopClosed ? cache.kfOpt[i] : (cand ? cand.p : cache.kfOptOnline[i]);
        return { i, p, err: e[3], wrong: e[3] > cfg.wrongLoopM, gtAssisted: !!e[2] };
      }
    }
    return null;
  }, [activeKfIdx, cache, cfg, isLoopClosed, loopCands]);

  const markerPose = isLoopClosed ? cache.kfOpt[activeKfIdx] : searchCentre;
  const pathColor = isLoopClosed ? "var(--green)" : "var(--cyan)";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
         style={{ display: "block", width: "100%", height: "100%", maxWidth: W, maxHeight: H }}
         role="img" aria-label="Robot, LiDAR scan and SLAM trajectory">
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

      {/* Raw odometry (thin) */}
      {odomPath && odomPath.length > 1 && (
        <polyline
          points={odomPath.map(([x,y]) => `${wx(x)},${wy(y)}`).join(" ")}
          fill="none" stroke="oklch(0.74 0.14 25)" strokeWidth="1" opacity="0.7" />
      )}

      {/* SLAM trajectory: keyframe estimates + odometry tail */}
      {slamPath.length > 1 && (
        <polyline
          points={slamPath.map(([x,y]) => `${wx(x)},${wy(y)}`).join(" ")}
          fill="none" stroke={pathColor}
          strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      )}

      {/* Past keyframes */}
      {kfEst.slice(0, activeKfIdx + 1).map((p, i) => (
        <circle key={i} cx={wx(p[0])} cy={wy(p[1])} r="2.2"
                fill={isLoopClosed ? "oklch(0.70 0.10 150)" : "oklch(0.65 0.10 220)"}
                opacity="0.85" />
      ))}

      {/* Submap — warm amber so it pops against the cyan scan */}
      {submap && submap.map(([x,y], i) => (
        <circle key={i} cx={wx(x)} cy={wy(y)} r="1.4"
                fill="oklch(0.78 0.16 60)" opacity="0.95" />
      ))}

      {/* Voxel grid overlay */}
      {voxelized && (
        <g>
          {voxelized.map(([x,y], i) => {
            const cx = Math.floor(x / VOXEL_DRAW) * VOXEL_DRAW, cy = Math.floor(y / VOXEL_DRAW) * VOXEL_DRAW;
            return (
              <g key={i}>
                <rect x={wx(cx)} y={wy(cy + VOXEL_DRAW)}
                      width={SCALE*VOXEL_DRAW} height={SCALE*VOXEL_DRAW}
                      fill="oklch(0.80 0.13 220 / 0.30)"
                      stroke="oklch(0.80 0.13 220 / 0.85)" strokeWidth="0.6" />
                <circle cx={wx(x)} cy={wy(y)} r="1.3" fill="var(--cyan)" />
              </g>
            );
          })}
        </g>
      )}

      {rawWorld && rawWorld.map(([x,y], i) => (
        <circle key={i} cx={wx(x)} cy={wy(y)} r="1.3"
                fill="oklch(0.74 0.14 25)" opacity="0.75" />
      ))}

      {corr && corr.map(([s, f, q1, q2], i) => (
        <g key={i}>
          <line x1={wx(q1[0])} y1={wy(q1[1])} x2={wx(q2[0])} y2={wy(q2[1])}
                stroke="oklch(0.85 0.15 90)" strokeWidth="1.4" opacity="0.6" />
          <line x1={wx(s[0])} y1={wy(s[1])} x2={wx(f[0])} y2={wy(f[1])}
                stroke="oklch(0.85 0.15 90)" strokeWidth="0.8" opacity="0.9" />
        </g>
      ))}

      {/* Loop search radius — drawn at the keyframe's estimate */}
      {mode === "loop-search" && (
        <>
          <circle cx={wx(markerPose[0])} cy={wy(markerPose[1])} r={cfg.loopRadius * SCALE}
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
      {(mode === "loop-icp" || isLoopClosed) && matchedLoop && (
        <g>
          <line x1={wx(markerPose[0])} y1={wy(markerPose[1])}
                x2={wx(matchedLoop.p[0])} y2={wy(matchedLoop.p[1])}
                stroke={matchedLoop.wrong ? "var(--rose)" : "oklch(0.82 0.13 75)"} strokeWidth="1.8"
                strokeDasharray={isLoopClosed ? "0" : "4 3"} />
          <text x={12} y={18} fontSize="10" fontFamily="JetBrains Mono, monospace"
                fill={matchedLoop.wrong ? "var(--rose)" : "oklch(0.82 0.13 75)"}>
            X({activeKfIdx}) ↔ X({matchedLoop.i})
            {matchedLoop.wrong
              ? ` · wrong match: ${matchedLoop.err.toFixed(2)} m off (aliasing)`
              : ` · ICP vs truth: ${(matchedLoop.err * 100).toFixed(1)} cm`}
            {matchedLoop.gtAssisted ? " · GT-assisted" : ""}
          </text>
        </g>
      )}
      {(mode === "loop-icp" || mode === "loop-search") && !matchedLoop && (
        <text x={12} y={18} fontSize="10" fontFamily="JetBrains Mono, monospace" fill="var(--text-3)">
          X({activeKfIdx}): {loopCands && loopCands.length ? `${loopCands.length} candidate(s), none accepted` : "no candidates"}
        </text>
      )}

      {/* LiDAR fan from the estimated pose */}
      {mode !== "boot" && (
        <g opacity="0.55">
          {scanWorld.filter((_, i) => i % 8 === 0).map(([ex, ey], i) => (
            <line key={i}
                  x1={wx(estPose[0])} y1={wy(estPose[1])}
                  x2={wx(ex)} y2={wy(ey)}
                  stroke="var(--cyan)" strokeWidth="0.4" opacity="0.5" />
          ))}
        </g>
      )}

      {/* Current scan at the SLAM-estimated pose (cyan) */}
      {(mode !== "boot" && mode !== "voxel") && scanWorld.map(([x,y], i) => (
        <circle key={i} cx={wx(x)} cy={wy(y)} r="1.3"
                fill="var(--cyan)" opacity="0.95" />
      ))}

      <GhostRobot x={wx(gtPose[0])} y={wy(gtPose[1])} th={gtPose[2]} scale={SCALE} />
      <Robot x={wx(estPose[0])} y={wy(estPose[1])} th={estPose[2]} scale={SCALE} />

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

function GhostRobot({ x, y, th, scale }) {
  const r = scale * 0.42;
  return (
    <g opacity="0.8">
      <circle cx={x} cy={y} r={r} fill="none" stroke="var(--text-2)" strokeWidth="1.1" strokeDasharray="2 2" />
      <line x1={x} y1={y} x2={x + Math.cos(-th) * r} y2={y + Math.sin(-th) * r}
            stroke="var(--text-2)" strokeWidth="1.1" />
    </g>
  );
}

window.RobotScene = RobotScene;
})();
