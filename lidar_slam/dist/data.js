(() => {
  const STAGES = [
    {
      id: "boot",
      title: "Boot \u2014 open shared memory",
      subtitle: "Attach to POSIX shm + named semaphores",
      summary: "The Python SLAM consumer attaches by name to two shared-memory regions and two POSIX named semaphores published by the C-side LiDAR/odom driver. Both processes view the same bytes. Each record starts with a seqlock counter: the writer makes it odd, writes, then makes it even, so a reader can detect and retry a half-written sample.",
      file: "lidar_slam_2d.py",
      lines: [67, 200],
      focus: [104, 142],
      active: ["shm-lidar", "shm-odom", "sem-lidar", "sem-odom", "consumer"],
      edges: [
        ["shm-lidar", "consumer"],
        ["shm-odom", "consumer"],
        ["sem-lidar", "consumer"],
        ["sem-odom", "consumer"]
      ],
      scene: { mode: "boot" },
      graph: { mode: "empty" },
      metrics: [
        { k: "lidar shm", v: "1856 B" },
        { k: "odom shm", v: "40 B" },
        { k: "beams / scan", v: "228" },
        { k: "torn reads", v: "seqlock" }
      ]
    },
    {
      id: "produce",
      title: "Producer publishes a LiDAR sweep",
      subtitle: "Diff-drive sim \xB7 noisy odom (k_d, k_\u03B8, ARW)",
      summary: "The simulated producer follows a differential-drive trajectory with rotate-in-place corners. Each 50 Hz odometry sample (wheel encoders + gyro) adds encoder-distance noise with \u03C3 = k_d\xB7\u221Ad, a heading random walk with \u03C3 = k_\u03B8\xB7\u221A|d\u03B8| (per radian turned), and gyro angle-random-walk \u03C3 = ARW\xB7\u221Adt, then integrates with the mid-point (RK2) rule. Every LiDAR beam is cast from the true pose at its own firing time, so each sweep carries real motion distortion; the scan is stamped at the end of the sweep. The metrics show run_demo()'s values; the slider on the right picks the noise level shown in the scene.",
      file: "lidar_slam_2d.py",
      lines: [1125, 1327],
      focus: [1253, 1305],
      active: ["producer", "shm-lidar", "shm-odom", "sem-lidar", "sem-odom"],
      edges: [
        ["producer", "shm-lidar"],
        ["producer", "shm-odom"],
        ["producer", "sem-lidar"],
        ["producer", "sem-odom"]
      ],
      scene: { mode: "scan-fresh" },
      graph: { mode: "empty" },
      metrics: [
        { k: "lidar rate", v: "10 Hz" },
        { k: "odom rate", v: "50 Hz" },
        { k: "demo k_d", v: "0.15 m/\u221Am" },
        { k: "demo k_\u03B8", v: "0.10 rad/\u221Arad" },
        { k: "demo ARW", v: "0.005 rad/\u221As" }
      ]
    },
    {
      id: "readers",
      title: "Reader threads drain the semaphores",
      subtitle: "OdomReader (50 Hz ring) + LidarReader (queue)",
      summary: "Two daemon threads block on sem_wait, then take a seqlock snapshot of the record (seqlock_read retries if the writer was mid-update). OdomReader keeps a 256-deep ring buffer of (t, x, y, \u03B8) for later interpolation. LidarReader copies the scan and drops it onto a 4-deep bounded queue, evicting the oldest scan if the consumer falls behind.",
      file: "lidar_slam_2d.py",
      lines: [245, 359],
      focus: [261, 278],
      active: ["sem-lidar", "sem-odom", "shm-lidar", "shm-odom", "odom-reader", "lidar-reader", "ring-buffer", "scan-queue"],
      edges: [
        ["sem-odom", "odom-reader"],
        ["shm-odom", "odom-reader"],
        ["odom-reader", "ring-buffer"],
        ["sem-lidar", "lidar-reader"],
        ["shm-lidar", "lidar-reader"],
        ["lidar-reader", "scan-queue"]
      ],
      scene: { mode: "scan-fresh" },
      graph: { mode: "empty" },
      metrics: [
        { k: "ring depth", v: "256" },
        { k: "scan queue", v: "4 (drop-oldest)" },
        { k: "lock", v: "OdomReader.lock" }
      ]
    },
    {
      id: "main-loop",
      title: "SLAM main loop pops a scan",
      subtitle: "Block on lidar_q, sample odometry pose at t_lidar",
      summary: "The SLAM thread pulls (seq, t_lidar, sweep, scan) off the queue, then asks OdomReader for the pose at the scan's end-of-sweep timestamp (SE(2) geodesic interpolation between the two bracketing samples). If the buffer hasn't reached t_lidar yet, it waits up to 50 ms for a fresh sample.",
      file: "lidar_slam_2d.py",
      lines: [943, 991],
      focus: [943, 991],
      active: ["scan-queue", "ring-buffer", "main-loop"],
      edges: [
        ["scan-queue", "main-loop"],
        ["ring-buffer", "main-loop"]
      ],
      scene: { mode: "scan-fresh" },
      graph: { mode: "trace" },
      metrics: [
        { k: "queue.get timeout", v: "200 ms" },
        { k: "pose_at wait", v: "\u2264 50 ms" }
      ]
    },
    {
      id: "undistort",
      title: "Motion-compensate the sweep",
      subtitle: "Re-project each beam into the end-of-sweep frame",
      summary: "A sweep takes 100 ms and the robot moves meanwhile. Each point's beam angle (atan2 of the point) gives its firing time within the sweep; the chassis pose at that time is SE(2)-interpolated from the 50 Hz odom buffer, and the point is re-expressed in the end-of-sweep frame so the cloud is rigid before ICP. The effect is largest while turning (0.1 rad per sweep at 1 rad/s).",
      file: "lidar_slam_2d.py",
      lines: [1031, 1068],
      focus: [1031, 1068],
      active: ["main-loop", "ring-buffer", "undistort"],
      edges: [
        ["main-loop", "undistort"],
        ["ring-buffer", "undistort"]
      ],
      scene: { mode: "undistort" },
      graph: { mode: "trace" },
      metrics: [
        { k: "sweep dur", v: "100 ms" },
        { k: "odom intervals", v: "5 / sweep" },
        { k: "interp", v: "SE(2) geodesic" }
      ]
    },
    {
      id: "voxel",
      title: "Voxel downsample (float32)",
      subtitle: "Bucket points by floor(p / cell), average each bucket",
      summary: "Reduces the cloud to one centroid per occupied 7 cm cell using lexsort + reduceat \u2014 vectorised, in float32. The same routine merges the submap before its KD-tree is built. (The scene draws 0.5 m cells so they are visible at this zoom; the code uses 0.07 m.)",
      file: "lidar_slam_2d.py",
      lines: [365, 377],
      focus: [365, 377],
      active: ["main-loop", "voxel"],
      edges: [["main-loop", "voxel"]],
      scene: { mode: "voxel" },
      graph: { mode: "trace" },
      metrics: [
        { k: "cell size", v: "0.07 m" },
        { k: "drawn cell", v: "0.5 m" },
        { k: "dtype", v: "float32" }
      ]
    },
    {
      id: "submap",
      title: "Build the local submap",
      subtitle: "Last 6 keyframes, transformed into base frame",
      summary: "The submap is the last 6 keyframe scans transformed into the newest keyframe's frame (using the current iSAM2 estimates) and voxel-merged, plus a cKDTree and a line normal per point (PCA of its 6 nearest neighbours). The result is memoised per base keyframe and reused only if the same base is requested again with no window pose moved by more than 0.1 mm / 0.1 mrad; the main loop requests it once per new keyframe, so it is normally built once per keyframe.",
      file: "lidar_slam_2d.py",
      lines: [687, 712],
      focus: [687, 712],
      active: ["voxel", "submap", "kf-store"],
      edges: [
        ["kf-store", "submap"],
        ["voxel", "submap"]
      ],
      scene: { mode: "submap" },
      graph: { mode: "trace" },
      metrics: [
        { k: "submap size", v: "6 keyframes" },
        { k: "tree", v: "cKDTree + normals (memoised)" }
      ]
    },
    {
      id: "icp",
      title: "PL-ICP \u2014 scan vs submap",
      subtitle: "Point-to-line residuals, adaptive gate + Geman-McClure",
      summary: "Each scan point is paired with its nearest submap point and measured along that point's line normal \u2014 the point-to-line metric of PL-ICP (Censi, ICRA 2008). As in KISS-ICP (Vizzo et al., RA-L 2023), pairs farther than 3\u03C3 are ignored and the rest get Geman-McClure weights with \u03BA = \u03C3/3, where \u03C3 is the running RMS of how far past ICP results deviated from the odometry prediction (AdaptiveThreshold). Gauss-Newton runs in float64 until the step is < 1e-4; RMSE and the information matrix H are re-evaluated at the returned pose.",
      file: "lidar_slam_2d.py",
      lines: [380, 525],
      focus: [403, 487],
      active: ["voxel", "submap", "icp", "main-loop"],
      edges: [
        ["voxel", "icp"],
        ["submap", "icp"],
        ["icp", "main-loop"]
      ],
      scene: { mode: "icp" },
      graph: { mode: "trace" },
      metrics: [
        { k: "gate", v: "3\u03C3 (adaptive)" },
        { k: "kernel", v: "Geman-McClure, \u03BA = \u03C3/3" },
        { k: "normals", v: "PCA, 6 neighbours" },
        { k: "stop", v: "\u2016\u03B4\u2016 < 1e-4" }
      ]
    },
    {
      id: "keyframe",
      title: "Spawn a keyframe",
      subtitle: "Translation > 0.30 m or rotation > 0.175 rad",
      summary: "When odometry has moved past the keyframe gate (0.30 m or 0.175 rad) since the last KF, two factors link X(j-1)\u2192X(j): a wheel-odometry factor whose \u03C3 follows the odometry noise model (always), and \u2014 only if ICP passed its guards (\u2264 0.4 m / 0.3 rad from odometry or within 5\u03C3 of the wheel model, rmse \u2264 0.3 m) \u2014 a scan-matching factor with the ICP covariance \u03C3\xB2(A\u1D40HA)\u207B\xB9 inflated \xD730. A rejected ICP therefore never pretends to be precise. The scan is stored and the keyframe id goes to the loop worker.",
      file: "lidar_slam_2d.py",
      lines: [588, 685],
      focus: [640, 685],
      active: ["icp", "kf-store", "isam", "loop-q-in"],
      edges: [
        ["icp", "kf-store"],
        ["kf-store", "isam"],
        ["kf-store", "loop-q-in"]
      ],
      scene: { mode: "keyframe" },
      graph: { mode: "kf-add" },
      metrics: [
        { k: "kf_trans", v: "0.30 m" },
        { k: "kf_rot", v: "0.175 rad" },
        { k: "factors", v: "wheel + ICP" },
        { k: "ICP cov", v: "\xD730 + floor" }
      ]
    },
    {
      id: "isam",
      title: "iSAM2 incremental update",
      subtitle: "Bayes-tree update, relinearize where needed",
      summary: "Pending factors and initial values flush into iSAM2, which re-eliminates the affected part of the Bayes tree and relinearizes variables whose linearization point moved more than the threshold. After a loop closure three extra update() iterations run before calculateEstimate(). The estimate writes back into kf_poses; only the main thread touches GTSAM.",
      file: "lidar_slam_2d.py",
      lines: [729, 747],
      focus: [729, 747],
      active: ["isam", "kf-store"],
      edges: [["isam", "kf-store"]],
      scene: { mode: "keyframe" },
      graph: { mode: "isam" },
      metrics: [
        { k: "relin thresh", v: "0.01" },
        { k: "relin skip", v: "1" },
        { k: "extra iters (loop)", v: "3" },
        { k: "writer", v: "main thread only" }
      ]
    },
    {
      id: "loop-search",
      title: "Loop-closure worker \u2014 search",
      subtitle: "KD-tree of past keyframes, radius + heading filter",
      summary: "On its own thread, the loop worker snapshots the current SLAM estimates of all keyframes under the lock, builds a KD-tree over keyframes at least 15 older (i \u2212 j \u2265 15), and queries those within 2.5 m of the newest keyframe's estimate, gated by a 75\xB0 heading difference. Up to 4 candidates go to ICP. After a loop is accepted the next 2 keyframes are skipped, since they would re-close almost the same loop with correlated errors. Because the search uses estimates, a large drift can hide a real revisit.",
      file: "lidar_slam_2d.py",
      lines: [778, 866],
      focus: [778, 804],
      active: ["loop-q-in", "loop-worker", "kf-store"],
      edges: [
        ["loop-q-in", "loop-worker"],
        ["kf-store", "loop-worker"]
      ],
      scene: { mode: "loop-search" },
      graph: { mode: "loop-search" },
      metrics: [
        { k: "radius", v: "2.5 m" },
        { k: "min gap", v: "15 KF" },
        { k: "max heading", v: "75\xB0" },
        { k: "candidates", v: "\u2264 4" },
        { k: "cooldown", v: "3 KF" }
      ]
    },
    {
      id: "loop-icp",
      title: "Loop-closure worker \u2014 validate",
      subtitle: "PL-ICP per candidate, accept the best",
      summary: "Each candidate gets a fresh PL-ICP of the new scan against the old keyframe's scan, starting from the relative pose between their estimates. A match is rejected if its translation is poorly constrained (\u03BB_min/trace of H's translation block < 0.1, cf. Zhang et al., ICRA 2016) or it moved more than 1.0 m / 0.35 rad from that guess; otherwise it passes only if rmse < 0.08 m, > 55 % of the points fall inside the gate and > 40 inliers. The lowest-rmse pass, with its ICP covariance, returns to the main thread via loop_out_q. In a repetitive room these checks can still accept a wrong match (perceptual aliasing).",
      file: "lidar_slam_2d.py",
      lines: [778, 819],
      focus: [804, 819],
      active: ["loop-worker", "loop-q-out"],
      edges: [["loop-worker", "loop-q-out"]],
      scene: { mode: "loop-icp" },
      graph: { mode: "loop-search" },
      metrics: [
        { k: "rmse", v: "< 0.08 m" },
        { k: "in gate", v: "> 55 %" },
        { k: "min inliers", v: "40" },
        { k: "degeneracy", v: "\u2265 0.1" },
        { k: "max dev", v: "1.0 m / 0.35 rad" }
      ]
    },
    {
      id: "loop-inject",
      title: "Inject loop factor \u2192 re-optimize",
      subtitle: "Cauchy-robust BetweenFactor X(j) \u2192 X(i)",
      summary: "The main thread drains loop_out_q and adds a BetweenFactor X(j)\u2192X(i) whose covariance is the loop ICP covariance plus diag(0.05 m, 0.05 m, 0.02 rad)\xB2, wrapped in a Cauchy kernel (k = 1 on the whitened residual). Unlike Huber, Cauchy's influence falls off for large errors, so a wrong loop is largely ignored instead of bending the map \u2014 the idea behind Dynamic Covariance Scaling (Agarwal et al., ICRA 2013). iSAM2 then runs 3 extra iterations. The poses along the loop are pulled into agreement; how close they get to the truth depends on the loop being correct.",
      file: "lidar_slam_2d.py",
      lines: [714, 727],
      focus: [714, 727],
      active: ["loop-q-out", "main-loop", "isam", "kf-store"],
      edges: [
        ["loop-q-out", "main-loop"],
        ["main-loop", "isam"],
        ["isam", "kf-store"]
      ],
      scene: { mode: "loop-closed" },
      graph: { mode: "loop-closed" },
      metrics: [
        { k: "robust", v: "Cauchy, k = 1\u03C3" },
        { k: "\u03C3_loop", v: "ICP cov + (0.05, 0.05, 0.02)\xB2" },
        { k: "extra iters", v: "3" }
      ]
    }
  ];
  window.STAGES = STAGES;
  const NODES = [
    // Producer (left)
    { id: "producer", label: "C Producer", sub: "diff-drive + noise", x: 70, y: 320, w: 130, h: 56, group: "producer" },
    // IPC (left-center column)
    { id: "shm-lidar", label: "shm: lidar", sub: "1856 B slot", x: 240, y: 220, w: 120, h: 50, group: "ipc" },
    { id: "sem-lidar", label: "sem: lidar", sub: "POSIX", x: 240, y: 280, w: 120, h: 38, group: "ipc" },
    { id: "shm-odom", label: "shm: odom", sub: "40 B slot", x: 240, y: 380, w: 120, h: 50, group: "ipc" },
    { id: "sem-odom", label: "sem: odom", sub: "POSIX", x: 240, y: 440, w: 120, h: 38, group: "ipc" },
    // Reader threads
    { id: "lidar-reader", label: "LidarReader", sub: "thread", x: 410, y: 220, w: 130, h: 50, group: "readers" },
    { id: "odom-reader", label: "OdomReader", sub: "thread", x: 410, y: 380, w: 130, h: 50, group: "readers" },
    { id: "scan-queue", label: "lidar_q", sub: "queue \xB7 4", x: 580, y: 220, w: 110, h: 44, group: "readers" },
    { id: "ring-buffer", label: "odom ring", sub: "deque \xB7 256", x: 580, y: 380, w: 110, h: 44, group: "readers" },
    // SLAM main thread
    { id: "main-loop", label: "SLAM main", sub: "thread", x: 730, y: 300, w: 130, h: 56, group: "slam", emphasis: true },
    { id: "undistort", label: "Undistort", sub: "per-beam reproject", x: 580, y: 110, w: 130, h: 44, group: "slam" },
    { id: "voxel", label: "Voxel ds", sub: "0.07 m", x: 740, y: 110, w: 110, h: 44, group: "slam" },
    { id: "submap", label: "Submap", sub: "cKDTree \xB7 6 KF", x: 880, y: 110, w: 130, h: 44, group: "slam" },
    { id: "icp", label: "PL-ICP", sub: "scan \u2192 submap", x: 880, y: 200, w: 130, h: 50, group: "slam", emphasis: true },
    { id: "kf-store", label: "kf_scans / poses", sub: "append-only", x: 880, y: 300, w: 130, h: 50, group: "slam" },
    { id: "isam", label: "iSAM2", sub: "Bayes tree", x: 880, y: 390, w: 130, h: 50, group: "slam", emphasis: true },
    // Loop closure (right column)
    { id: "loop-q-in", label: "loop_in_q", sub: "queue \xB7 8", x: 730, y: 510, w: 110, h: 42, group: "loop" },
    { id: "loop-worker", label: "LoopClosure", sub: "thread", x: 880, y: 510, w: 130, h: 50, group: "loop", emphasis: true },
    { id: "loop-q-out", label: "loop_out_q", sub: "queue \xB7 16", x: 730, y: 580, w: 110, h: 42, group: "loop" },
    // Misc
    { id: "consumer", label: "Python SLAM", sub: "this process", x: 410, y: 540, w: 140, h: 50, group: "ipc" }
  ];
  window.NODES = NODES;
  window.GROUP_STYLE = {
    producer: { stroke: "var(--text-3)", fill: "var(--bg-2)" },
    ipc: { stroke: "var(--text-3)", fill: "var(--bg-2)" },
    readers: { stroke: "var(--cyan-d)", fill: "var(--bg-2)" },
    slam: { stroke: "var(--cyan-d)", fill: "var(--bg-2)" },
    loop: { stroke: "var(--amber-d)", fill: "var(--bg-2)" }
  };
})();
