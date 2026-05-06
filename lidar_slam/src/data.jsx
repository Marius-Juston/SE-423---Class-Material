/* eslint-disable */
// Pipeline stage definitions. Each stage references code lines from
// lidar_slam_2d.py and configures which flow nodes are active and
// what the robot scene + subgraph should show.

const STAGES = [
  {
    id: "boot",
    title: "Boot — open shared memory",
    subtitle: "Attach to POSIX shm + named semaphores",
    summary: "The Python SLAM consumer attaches by name to two shared-memory regions and two POSIX named semaphores published by the C-side LiDAR/odom driver. No data is copied — both processes view the same bytes.",
    file: "lidar_slam_2d.py",
    lines: [50, 132],
    focus: [50, 96],
    active: ["shm-lidar", "shm-odom", "sem-lidar", "sem-odom", "consumer"],
    edges: [
      ["shm-lidar", "consumer"],
      ["shm-odom", "consumer"],
      ["sem-lidar", "consumer"],
      ["sem-odom", "consumer"],
    ],
    scene: { mode: "boot" },
    graph: { mode: "empty" },
    metrics: [
      { k: "lidar shm", v: "1856 B" },
      { k: "odom shm", v: "40 B" },
      { k: "beams / scan", v: "228" },
    ],
  },
  {
    id: "produce",
    title: "Producer publishes a LiDAR sweep",
    subtitle: "Diff-drive sim · noisy odom (k_d, k_th, ARW)",
    summary: "The simulated producer follows a differential-drive trajectory with rotate-in-place corners. Each odom sample applies an encoder-distance noise std proportional to √true_d, gyro scale-factor noise proportional to √|true_dθ|, plus angle-random-walk per dt. Mid-point (RK2) integration projects the noisy increments forward.",
    file: "lidar_slam_2d.py",
    lines: [847, 1024],
    focus: [847, 893],
    active: ["producer", "shm-lidar", "shm-odom", "sem-lidar", "sem-odom"],
    edges: [
      ["producer", "shm-lidar"],
      ["producer", "shm-odom"],
      ["producer", "sem-lidar"],
      ["producer", "sem-odom"],
    ],
    scene: { mode: "scan-fresh" },
    graph: { mode: "empty" },
    metrics: [
      { k: "lidar rate", v: "10 Hz" },
      { k: "odom rate", v: "50 Hz" },
      { k: "k_d", v: "0.15 m/√m" },
      { k: "k_θ", v: "0.10 rad/√rad" },
      { k: "ARW", v: "0.005" },
    ],
  },
  {
    id: "readers",
    title: "Reader threads drain the semaphores",
    subtitle: "OdomReader (50 Hz ring) + LidarReader (queue)",
    summary: "Two daemon threads block on sem_wait. OdomReader keeps a 256-deep ring buffer of (t, x, y, θ) for later interpolation. LidarReader copies the scan out of shm and drops it onto a 4-deep bounded queue, evicting the oldest scan if the consumer falls behind.",
    file: "lidar_slam_2d.py",
    lines: [135, 211],
    focus: [135, 211],
    active: ["sem-lidar", "sem-odom", "shm-lidar", "shm-odom", "odom-reader", "lidar-reader", "ring-buffer", "scan-queue"],
    edges: [
      ["sem-odom", "odom-reader"],
      ["shm-odom", "odom-reader"],
      ["odom-reader", "ring-buffer"],
      ["sem-lidar", "lidar-reader"],
      ["shm-lidar", "lidar-reader"],
      ["lidar-reader", "scan-queue"],
    ],
    scene: { mode: "scan-fresh" },
    graph: { mode: "empty" },
    metrics: [
      { k: "ring depth", v: "256" },
      { k: "scan queue", v: "4 (drop-oldest)" },
      { k: "lock", v: "OdomReader.lock" },
    ],
  },
  {
    id: "main-loop",
    title: "SLAM main loop pops a scan",
    subtitle: "Block on lidar_q, sample IMU pose at t_lidar",
    summary: "The SLAM thread pulls (seq, t_lidar, sweep, scan) off the queue, then asks OdomReader for the interpolated pose at the scan's timestamp. If the buffer hasn't reached t_lidar yet, it briefly waits up to 50 ms for a fresh sample.",
    file: "lidar_slam_2d.py",
    lines: [650, 692],
    focus: [650, 692],
    active: ["scan-queue", "ring-buffer", "main-loop"],
    edges: [
      ["scan-queue", "main-loop"],
      ["ring-buffer", "main-loop"],
    ],
    scene: { mode: "scan-fresh" },
    graph: { mode: "trace" },
    metrics: [
      { k: "queue.get timeout", v: "200 ms" },
      { k: "pose_at wait", v: "≤ 50 ms" },
    ],
  },
  {
    id: "undistort",
    title: "Motion-compensate the sweep",
    subtitle: "Re-project each beam into the end-of-sweep frame",
    summary: "A LiDAR sweep takes ~100 ms. While the laser rotates, the robot moves. We linearly index each beam's timestamp into the 50 Hz IMU buffer, recover the chassis pose at that beam, and rotate it into the end-of-sweep frame so the cloud is rigid before ICP.",
    file: "lidar_slam_2d.py",
    lines: [740, 778],
    focus: [740, 778],
    active: ["main-loop", "ring-buffer", "undistort"],
    edges: [
      ["main-loop", "undistort"],
      ["ring-buffer", "undistort"],
    ],
    scene: { mode: "undistort" },
    graph: { mode: "trace" },
    metrics: [
      { k: "sweep dur", v: "100 ms" },
      { k: "samples used", v: "5 IMU / sweep" },
      { k: "interp", v: "linear" },
    ],
  },
  {
    id: "voxel",
    title: "Voxel downsample (float32)",
    subtitle: "Bucket points by floor(p / cell), average each bucket",
    summary: "Reduces the cloud to one centroid per occupied 7 cm cell using lexsort + reduceat — branchless, allocator-friendly, and stays in float32 throughout. The same routine downsamples the merged submap before the KD-tree is built.",
    file: "lidar_slam_2d.py",
    lines: [254, 267],
    focus: [254, 267],
    active: ["main-loop", "voxel"],
    edges: [["main-loop", "voxel"]],
    scene: { mode: "voxel" },
    graph: { mode: "trace" },
    metrics: [
      { k: "cell size", v: "0.07 m" },
      { k: "dtype", v: "float32" },
    ],
  },
  {
    id: "submap",
    title: "Build / reuse the submap",
    subtitle: "Last 6 keyframes, transformed into base frame",
    summary: "The submap is the last 6 keyframe scans transformed into the most-recent keyframe's frame and voxel-merged. The cKDTree is cached and only rebuilt when a new keyframe is added — consecutive non-keyframe scans reuse it for free.",
    file: "lidar_slam_2d.py",
    lines: [442, 462],
    focus: [442, 462],
    active: ["voxel", "submap", "kf-store"],
    edges: [
      ["kf-store", "submap"],
      ["voxel", "submap"],
    ],
    scene: { mode: "submap" },
    graph: { mode: "trace" },
    metrics: [
      { k: "submap size", v: "6 keyframes" },
      { k: "tree", v: "cached cKDTree" },
    ],
  },
  {
    id: "icp",
    title: "PL-ICP — scan vs submap",
    subtitle: "Point-to-line residuals, Huber + percentile rejection",
    summary: "For each source point we find the two nearest target points, compute the perpendicular distance to the line they span, and Gauss-Newton on (Δx, Δy, Δθ). Outliers above the 85th percentile are dropped, the rest get Huber-clipped weights. Diverges → fall back to the odometry guess.",
    file: "lidar_slam_2d.py",
    lines: [269, 350],
    focus: [269, 350],
    active: ["voxel", "submap", "icp", "main-loop"],
    edges: [
      ["voxel", "icp"],
      ["submap", "icp"],
      ["icp", "main-loop"],
    ],
    scene: { mode: "icp" },
    graph: { mode: "trace" },
    metrics: [
      { k: "max iters", v: "20" },
      { k: "reject pct", v: "85th" },
      { k: "huber k", v: "0.1" },
      { k: "guard rmse", v: "≤ 0.30" },
    ],
  },
  {
    id: "keyframe",
    title: "Spawn a keyframe",
    subtitle: "Translation > 0.30 m or rotation > 0.175 rad",
    summary: "When odometry has drifted past the keyframe gate since the last KF, the refined ICP delta becomes a BetweenFactor X(j-1)→X(j). The new keyframe scan is stored, the submap cache is invalidated, and the keyframe id is enqueued for loop validation.",
    file: "lidar_slam_2d.py",
    lines: [428, 440],
    focus: [428, 440],
    active: ["icp", "kf-store", "isam", "loop-q-in"],
    edges: [
      ["icp", "kf-store"],
      ["kf-store", "isam"],
      ["kf-store", "loop-q-in"],
    ],
    scene: { mode: "keyframe" },
    graph: { mode: "kf-add" },
    metrics: [
      { k: "kf_trans", v: "0.30 m" },
      { k: "kf_rot", v: "0.175 rad" },
    ],
  },
  {
    id: "isam",
    title: "iSAM2 incremental update",
    subtitle: "Bayes-tree relinearize affected variables",
    summary: "Pending factors and initial values flush into iSAM2, which incrementally re-orders and relinearizes only the variables whose deltas crossed the threshold. The latest estimate writes back into kf_poses; nothing else touches GTSAM.",
    file: "lidar_slam_2d.py",
    lines: [474, 489],
    focus: [474, 489],
    active: ["isam", "kf-store"],
    edges: [["isam", "kf-store"]],
    scene: { mode: "keyframe" },
    graph: { mode: "isam" },
    metrics: [
      { k: "relin thresh", v: "0.01" },
      { k: "relin skip", v: "1" },
      { k: "writer", v: "main thread only" },
    ],
  },
  {
    id: "loop-search",
    title: "Loop-closure worker — search",
    subtitle: "KD-tree of past keyframes, radius + heading filter",
    summary: "On its own thread, the loop worker snapshots past keyframe (x, y, θ) under the SLAM lock, builds a KD-tree, and queries for KFs within 2.5 m of the current pose, gated by a 75° max heading difference and a 15-keyframe minimum gap.",
    file: "lidar_slam_2d.py",
    lines: [528, 558],
    focus: [528, 558],
    active: ["loop-q-in", "loop-worker", "kf-store"],
    edges: [
      ["loop-q-in", "loop-worker"],
      ["kf-store", "loop-worker"],
    ],
    scene: { mode: "loop-search" },
    graph: { mode: "loop-search" },
    metrics: [
      { k: "radius", v: "2.5 m" },
      { k: "min gap", v: "15 KF" },
      { k: "max heading", v: "75°" },
      { k: "candidates", v: "≤ 4" },
    ],
  },
  {
    id: "loop-icp",
    title: "Loop-closure worker — validate",
    subtitle: "Full PL-ICP per candidate, accept the best",
    summary: "Each candidate gets a fresh PL-ICP starting from the relative pose guess. Candidates pass only if rmse < 0.08, inlier ratio > 0.55, and inliers > 40. The best one (lowest rmse) becomes (j, i, rel, rmse) and goes back to the main thread via loop_out_q.",
    file: "lidar_slam_2d.py",
    lines: [560, 581],
    focus: [560, 581],
    active: ["loop-worker", "loop-q-out"],
    edges: [["loop-worker", "loop-q-out"]],
    scene: { mode: "loop-icp" },
    graph: { mode: "loop-search" },
    metrics: [
      { k: "rmse thresh", v: "0.08" },
      { k: "inlier ratio", v: "0.55" },
      { k: "min inliers", v: "40" },
    ],
  },
  {
    id: "loop-inject",
    title: "Inject loop factor → re-optimize",
    subtitle: "Huber-robust BetweenFactor X(j) → X(i)",
    summary: "The main thread drains loop_out_q, adds a robust BetweenFactor X(j)→X(i) wrapped in a Huber m-estimator, and flushes iSAM2 again. The full trajectory snaps to global consistency; the submap cache invalidates because every pose just shifted.",
    file: "lidar_slam_2d.py",
    lines: [724, 738],
    focus: [724, 738],
    active: ["loop-q-out", "main-loop", "isam", "kf-store"],
    edges: [
      ["loop-q-out", "main-loop"],
      ["main-loop", "isam"],
      ["isam", "kf-store"],
    ],
    scene: { mode: "loop-closed" },
    graph: { mode: "loop-closed" },
    metrics: [
      { k: "robust", v: "Huber, k = 0.3" },
      { k: "σ_loop", v: "(0.05, 0.05, 0.02)" },
    ],
  },
];

window.STAGES = STAGES;

// ----- Flow node positions on the canvas (logical 1100x720 grid) -----
// Grouped into producer / IPC / readers / SLAM core / loop closure / output.
const NODES = [
  // Producer (left)
  { id: "producer",     label: "C Producer",        sub: "diff-drive + noise", x: 70,  y: 320, w: 130, h: 56, group: "producer" },

  // IPC (left-center column)
  { id: "shm-lidar",    label: "shm: lidar",        sub: "1856 B slot",        x: 240, y: 220, w: 120, h: 50, group: "ipc" },
  { id: "sem-lidar",    label: "sem: lidar",        sub: "POSIX",              x: 240, y: 280, w: 120, h: 38, group: "ipc" },
  { id: "shm-odom",     label: "shm: odom",         sub: "40 B slot",          x: 240, y: 380, w: 120, h: 50, group: "ipc" },
  { id: "sem-odom",     label: "sem: odom",         sub: "POSIX",              x: 240, y: 440, w: 120, h: 38, group: "ipc" },

  // Reader threads
  { id: "lidar-reader", label: "LidarReader",       sub: "thread",             x: 410, y: 220, w: 130, h: 50, group: "readers" },
  { id: "odom-reader",  label: "OdomReader",        sub: "thread",             x: 410, y: 380, w: 130, h: 50, group: "readers" },
  { id: "scan-queue",   label: "lidar_q",           sub: "queue · 4",          x: 580, y: 220, w: 110, h: 44, group: "readers" },
  { id: "ring-buffer",  label: "odom ring",         sub: "deque · 256",        x: 580, y: 380, w: 110, h: 44, group: "readers" },

  // SLAM main thread
  { id: "main-loop",    label: "SLAM main",         sub: "thread",             x: 730, y: 300, w: 130, h: 56, group: "slam", emphasis: true },
  { id: "undistort",    label: "Undistort",         sub: "per-beam reproject", x: 580, y: 110, w: 130, h: 44, group: "slam" },
  { id: "voxel",        label: "Voxel ds",          sub: "0.07 m",             x: 740, y: 110, w: 110, h: 44, group: "slam" },
  { id: "submap",       label: "Submap",            sub: "cKDTree · 6 KF",     x: 880, y: 110, w: 130, h: 44, group: "slam" },
  { id: "icp",          label: "PL-ICP",            sub: "scan → submap",      x: 880, y: 200, w: 130, h: 50, group: "slam", emphasis: true },
  { id: "kf-store",     label: "kf_scans / poses",  sub: "append-only",        x: 880, y: 300, w: 130, h: 50, group: "slam" },
  { id: "isam",         label: "iSAM2",             sub: "Bayes tree",         x: 880, y: 390, w: 130, h: 50, group: "slam", emphasis: true },

  // Loop closure (right column)
  { id: "loop-q-in",    label: "loop_in_q",         sub: "queue · 8",          x: 730, y: 510, w: 110, h: 42, group: "loop" },
  { id: "loop-worker",  label: "LoopClosure",       sub: "thread",             x: 880, y: 510, w: 130, h: 50, group: "loop", emphasis: true },
  { id: "loop-q-out",   label: "loop_out_q",        sub: "queue · 16",         x: 730, y: 580, w: 110, h: 42, group: "loop" },

  // Misc
  { id: "consumer",     label: "Python SLAM",       sub: "this process",       x: 410, y: 540, w: 140, h: 50, group: "ipc" },
];

window.NODES = NODES;

// Group colors
window.GROUP_STYLE = {
  producer: { stroke: "var(--text-3)",  fill: "var(--bg-2)" },
  ipc:      { stroke: "var(--text-3)",  fill: "var(--bg-2)" },
  readers:  { stroke: "var(--cyan-d)",  fill: "var(--bg-2)" },
  slam:     { stroke: "var(--cyan-d)",  fill: "var(--bg-2)" },
  loop:     { stroke: "var(--amber-d)", fill: "var(--bg-2)" },
};
