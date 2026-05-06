#!/usr/bin/env python3
"""
Real-time 2D LiDAR SLAM with shared-memory IPC, for a Raspberry Pi.

External producers (e.g., a C/C++ driver) write to two POSIX shared-memory
regions and post two POSIX named semaphores:

  - LiDAR     : 228x2 xy points + timestamp + sweep duration, ~10 Hz
  - Odometry  : integrated SE(2) pose (e.g. wheel + IMU), ~50 Hz

This Python process attaches by name and runs SLAM in four threads:

  OdomReader  ─ blocks on odom semaphore, fills 50 Hz pose ring buffer
  LidarReader ─ blocks on lidar semaphore, pushes scans onto a queue
  SLAM main   ─ pops scans, samples IMU pose at scan time, undistorts,
                runs PL-ICP vs cached submap, writes factors into iSAM2
  LoopClosure ─ runs loop-validation ICP off the critical path; results
                are re-injected into iSAM2 by the main thread

Optimizations vs. the previous version:
  - Asynchronous loop closure  (off the per-frame budget)
  - Float32 throughout the ICP pipeline
  - Submap KD-tree cached across consecutive keyframes
  - Append-only voxelized scan storage (raw scans dropped)
  - Scan motion-compensation using the 50 Hz IMU samples

iSAM2 is touched by the main thread only; loop closures cross thread
boundaries through a queue, so the GTSAM data structures stay single-writer.
"""

from __future__ import annotations

import os, time, queue, threading
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree
import gtsam
from gtsam.symbol_shorthand import X
from multiprocessing import shared_memory

import posix_ipc


# ---------------------------------------------------------------------------
# Wire format — must match the C producer side
# ---------------------------------------------------------------------------
N_BEAMS = 228

ODOM_DTYPE = np.dtype([
    ('seq',       '<u8'),   # 8
    ('timestamp', '<f8'),   # 8  (epoch seconds)
    ('x',         '<f8'),   # 8
    ('y',         '<f8'),   # 8
    ('theta',     '<f8'),   # 8  → 40 bytes
])

LIDAR_DTYPE = np.dtype([
    ('seq',            '<u8'),   # 8
    ('timestamp',      '<f8'),   # 8  (end of sweep)
    ('sweep_duration', '<f8'),   # 8
    ('n_points',       '<u4'),   # 4  (valid points; the rest are padding)
    ('capacity',       '<u4'),   # 4
    ('points',         '<f4', (N_BEAMS, 2)),  # 1824 → 1856 bytes total
])


# ---------------------------------------------------------------------------
# IPC wrappers
# ---------------------------------------------------------------------------
class ShmRegion:
    """A POSIX shared-memory region viewed as a numpy structured scalar."""
    def __init__(self, name: str, dtype: np.dtype, create: bool = False):
        self.name = name
        size = dtype.itemsize
        if create:
            try:
                old = shared_memory.SharedMemory(name=name, create=False)
                old.close(); old.unlink()
            except FileNotFoundError:
                pass
            self.shm = shared_memory.SharedMemory(name=name, create=True, size=size)
        else:
            self.shm = shared_memory.SharedMemory(name=name, create=False)
        self.array = np.ndarray((1,), dtype=dtype, buffer=self.shm.buf)

    def close(self):
        try: self.shm.close()
        except Exception: pass

    def unlink(self):
        try: self.shm.unlink()
        except Exception: pass


class NamedSemaphore:
    """A POSIX named semaphore. Same name across producer and consumer."""
    def __init__(self, name: str, create: bool = False, initial: int = 0):
        self.name = name
        if create:
            try:
                posix_ipc.unlink_semaphore(name)
            except posix_ipc.ExistentialError:
                pass
            self.sem = posix_ipc.Semaphore(
                name, flags=posix_ipc.O_CREAT | posix_ipc.O_EXCL,
                initial_value=initial)
        else:
            self.sem = posix_ipc.Semaphore(name)

    def acquire(self, timeout: Optional[float] = None) -> bool:
        try:
            self.sem.acquire(timeout)
            return True
        except posix_ipc.BusyError:
            return False

    def release(self):
        self.sem.release()

    def close(self):
        try: self.sem.close()
        except Exception: pass

    def unlink(self):
        try: posix_ipc.unlink_semaphore(self.name)
        except posix_ipc.ExistentialError: pass


# ---------------------------------------------------------------------------
# Reader threads
# ---------------------------------------------------------------------------
class OdomReader(threading.Thread):
    """Drains the odom semaphore, keeps a small ring buffer of (t, x, y, theta)."""
    def __init__(self, shm: ShmRegion, sem: NamedSemaphore, capacity: int = 256):
        super().__init__(daemon=True, name="OdomReader")
        self.shm = shm
        self.sem = sem
        self.buffer: deque = deque(maxlen=capacity)
        self.lock = threading.Lock()
        self.last_seq = -1
        self.received = 0
        self._stop = threading.Event()

    def stop(self): self._stop.set()

    def run(self):
        view = self.shm.array
        while not self._stop.is_set():
            if not self.sem.acquire(timeout=0.2):
                continue
            seq = int(view['seq'][0])
            if seq == self.last_seq:
                continue
            ts = float(view['timestamp'][0])
            x  = float(view['x'][0])
            y  = float(view['y'][0])
            th = float(view['theta'][0])
            self.last_seq = seq
            with self.lock:
                self.buffer.append((ts, x, y, th))
                self.received += 1

    def latest(self) -> Optional[Tuple[float, float, float, float]]:
        with self.lock:
            return self.buffer[-1] if self.buffer else None

    def pose_at(self, t: float, wait: float = 0.05
                ) -> Optional[Tuple[float, float, float]]:
        """Linearly interpolate pose at time t. Briefly waits for fresh IMU
        if the buffer hasn't reached t yet."""
        deadline = time.monotonic() + wait
        snap: List[Tuple[float, float, float, float]] = []
        while True:
            with self.lock:
                if self.buffer:
                    snap = list(self.buffer)
            if snap and snap[-1][0] >= t:
                break
            if time.monotonic() > deadline:
                if not snap:
                    return None
                break
            time.sleep(0.001)

        if t <= snap[0][0]:
            _, x, y, th = snap[0]; return x, y, th
        if t >= snap[-1][0]:
            _, x, y, th = snap[-1]; return x, y, th

        lo, hi = 0, len(snap) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if snap[mid][0] <= t: lo = mid
            else: hi = mid

        a, b = snap[lo], snap[hi]
        u = (t - a[0]) / max(b[0] - a[0], 1e-9)

        pose_a = gtsam.Pose2(a[1], a[2], a[3])
        pose_b = gtsam.Pose2(b[1], b[2], b[3])

        # Exact SE(2) interpolation
        delta = pose_a.between(pose_b)
        twist = gtsam.Pose2.Logmap(delta)
        interp = pose_a.compose(gtsam.Pose2.Expmap(u * twist))

        return interp.x(), interp.y(), interp.theta()


class LidarReader(threading.Thread):
    """Drains the lidar semaphore, pushes copies of scans onto a queue."""
    def __init__(self, shm: ShmRegion, sem: NamedSemaphore, q: queue.Queue):
        super().__init__(daemon=True, name="LidarReader")
        self.shm = shm
        self.sem = sem
        self.q = q
        self.last_seq = -1
        self.received = 0
        self.dropped = 0
        self._stop = threading.Event()

    def stop(self): self._stop.set()

    def run(self):
        view = self.shm.array
        while not self._stop.is_set():
            if not self.sem.acquire(timeout=0.2):
                continue
            seq = int(view['seq'][0])
            if seq == self.last_seq:
                continue
            n     = int(view['n_points'][0])
            ts    = float(view['timestamp'][0])
            sweep = float(view['sweep_duration'][0])
            pts   = np.array(view['points'][0, :n], dtype=np.float32, copy=True)
            self.last_seq = seq
            self.received += 1
            try:
                self.q.put_nowait((seq, ts, sweep, pts))
            except queue.Full:
                try: self.q.get_nowait()
                except queue.Empty: pass
                try: self.q.put_nowait((seq, ts, sweep, pts))
                except queue.Full: pass
                self.dropped += 1


# ---------------------------------------------------------------------------
# Voxel + PL-ICP (float32)
# ---------------------------------------------------------------------------
def voxel_downsample(points: np.ndarray, cell: float) -> np.ndarray:
    if len(points) == 0:
        return points.astype(np.float32, copy=False)
    p = points.astype(np.float32, copy=False)
    keys = np.floor(p / cell).astype(np.int32)
    order = np.lexsort((keys[:, 1], keys[:, 0]))
    kp = keys[order]; sp = p[order]
    edges = np.any(np.diff(kp, axis=0), axis=1)
    starts = np.concatenate([[0], np.flatnonzero(edges) + 1])
    ends = np.concatenate([starts[1:], [len(sp)]])
    counts = (ends - starts).astype(np.float32)
    sums = np.add.reduceat(sp, starts, axis=0)
    return (sums / counts[:, None]).astype(np.float32)


def pl_icp_2d(source: np.ndarray, target: np.ndarray,
              init_pose: gtsam.Pose2,
              max_iter: int = 20, tol: float = 1e-5,
              huber_k: float = 0.1, reject_pct: float = 85.0,
              max_neighbor_gap: float = 0.30,
              target_tree: Optional[cKDTree] = None
              ) -> Tuple[gtsam.Pose2, float, float, int]:
    if len(target) < 2 or len(source) < 3:
        return init_pose, float('inf'), 0.0, 0

    src = source.astype(np.float32, copy=False)
    tgt = target.astype(np.float32, copy=False)

    theta = float(init_pose.theta())
    c, s = np.cos(theta), np.sin(theta)
    R = np.array([[c, -s], [s, c]], dtype=np.float32)
    t = np.array([init_pose.x(), init_pose.y()], dtype=np.float32)

    if target_tree is None:
        target_tree = cKDTree(tgt)

    rmse = np.inf
    inlier_ratio = 0.0
    n_inl = 0
    prev_err = np.inf

    for _ in range(max_iter):
        rotated = src @ R.T
        transformed = rotated + t

        _, idx = target_tree.query(transformed, k=2)
        q1 = tgt[idx[:, 0]]; q2 = tgt[idx[:, 1]]
        seg = q2 - q1
        seg_len = np.linalg.norm(seg, axis=1)
        line_dir = seg / np.maximum(seg_len[:, None], 1e-9)
        normals = np.stack([-line_dir[:, 1], line_dir[:, 0]], axis=1)

        residuals = np.sum((transformed - q1) * normals, axis=1)
        abs_r = np.abs(residuals)

        valid = seg_len < max_neighbor_gap
        if valid.sum() < 6:
            valid = np.ones_like(valid)
        cutoff = np.percentile(abs_r[valid], reject_pct)
        inliers = valid & (abs_r < max(cutoff, 1e-6))
        n_inl = int(inliers.sum())
        inlier_ratio = n_inl / max(len(residuals), 1)
        if n_inl < 6:
            break

        w = np.zeros_like(residuals)
        w[inliers] = 1.0
        big = inliers & (abs_r > huber_k)
        w[big] = huber_k / abs_r[big]

        J = np.empty((len(residuals), 3), dtype=np.float32)
        J[:, 0] = normals[:, 0]
        J[:, 1] = normals[:, 1]
        J[:, 2] = -normals[:, 0] * rotated[:, 1] + normals[:, 1] * rotated[:, 0]

        Jw = J * w[:, None]
        H = Jw.T @ J + np.float32(1e-9) * np.eye(3, dtype=np.float32)
        g = Jw.T @ residuals
        try:
            delta = np.linalg.solve(H, -g)
        except np.linalg.LinAlgError:
            break

        t = t + delta[:2].astype(np.float32)
        theta += float(delta[2])
        c, s = np.cos(theta), np.sin(theta)
        R = np.array([[c, -s], [s, c]], dtype=np.float32)

        rmse = float(np.sqrt(np.mean(residuals[inliers] ** 2)))
        if abs(prev_err - rmse) < tol:
            break
        prev_err = rmse

    return gtsam.Pose2(float(t[0]), float(t[1]), theta), rmse, inlier_ratio, n_inl


# ---------------------------------------------------------------------------
# SLAM core (single-threaded; orchestrator serializes access)
# ---------------------------------------------------------------------------
@dataclass
class SLAMConfig:
    voxel_size:    float = 0.07

    prior_sigmas:  Tuple[float, float, float] = (1e-3, 1e-3, 1e-4)
    odom_sigmas:   Tuple[float, float, float] = (0.05, 0.05, 0.02)
    loop_sigmas:   Tuple[float, float, float] = (0.05, 0.05, 0.02)

    kf_trans:      float = 0.30
    kf_rot:        float = 0.175
    submap_size:   int   = 6

    loop_search_radius:    float = 2.5
    loop_min_kf_gap:       int   = 15
    loop_rmse_thresh:      float = 0.08
    loop_inlier_thresh:    float = 0.55
    loop_min_inliers:      int   = 40
    loop_max_heading_diff: float = np.deg2rad(75.0)
    loop_every_n_kf:       int   = 1
    loop_max_candidates:   int   = 4

    icp_max_trans_dev: float = 0.4
    icp_max_rot_dev:   float = 0.3
    icp_max_rmse:      float = 0.3

    use_huber_on_loops: bool = True
    huber_k: float = 0.3

    enable_undistort: bool = True


class LidarSLAM2D:
    def __init__(self, cfg: Optional[SLAMConfig] = None):
        self.cfg = cfg or SLAMConfig()
        params = gtsam.ISAM2Params()
        params.setRelinearizeThreshold(0.01)
        params.relinearizeSkip = 1
        self.isam = gtsam.ISAM2(params)

        self._pending_factors = gtsam.NonlinearFactorGraph()
        self._pending_values  = gtsam.Values()

        self.kf_scans: List[np.ndarray]  = []
        self.kf_poses: List[gtsam.Pose2] = []
        self.loop_closures: List[Tuple[int, int, float]] = []
        self.n_kf = 0
        self.current_pose = gtsam.Pose2(0, 0, 0)

        self._submap_pts:  Optional[np.ndarray] = None
        self._submap_tree: Optional[cKDTree] = None
        self._submap_anchor: int = -1

        self._prior_noise = gtsam.noiseModel.Diagonal.Sigmas(np.asarray(self.cfg.prior_sigmas))
        self._odom_noise  = gtsam.noiseModel.Diagonal.Sigmas(np.asarray(self.cfg.odom_sigmas))
        base_loop = gtsam.noiseModel.Diagonal.Sigmas(np.asarray(self.cfg.loop_sigmas))
        if self.cfg.use_huber_on_loops:
            self._loop_noise = gtsam.noiseModel.Robust.Create(
                gtsam.noiseModel.mEstimator.Huber.Create(self.cfg.huber_k),
                base_loop)
        else:
            self._loop_noise = base_loop

        self.timings = {"isam": []}

    # ---- API used by orchestrator (under slam_lock) -----------------------
    def add_first_scan(self, scan: np.ndarray, pose: gtsam.Pose2):
        scan_ds = voxel_downsample(scan, self.cfg.voxel_size)
        self._pending_factors.add(gtsam.PriorFactorPose2(X(0), pose, self._prior_noise))
        self._pending_values.insert(X(0), pose)
        self.kf_scans.append(scan_ds)
        self.kf_poses.append(pose)
        self.n_kf = 1
        self.current_pose = pose
        self._flush_isam()

    def add_keyframe(self, scan: np.ndarray, refined_delta: gtsam.Pose2) -> int:
        scan_ds = voxel_downsample(scan, self.cfg.voxel_size)
        j = self.n_kf
        new_pose = self.kf_poses[-1].compose(refined_delta)
        self._pending_factors.add(gtsam.BetweenFactorPose2(
            X(j-1), X(j), refined_delta, self._odom_noise))
        self._pending_values.insert(X(j), new_pose)
        self.kf_scans.append(scan_ds)
        self.kf_poses.append(new_pose)
        self.n_kf += 1
        self.current_pose = new_pose
        self._submap_anchor = -1   # invalidate cache
        return j

    def get_submap(self, base_idx: int) -> Tuple[np.ndarray, cKDTree]:
        if base_idx == self._submap_anchor and self._submap_tree is not None:
            return self._submap_pts, self._submap_tree
        start = max(0, base_idx - self.cfg.submap_size + 1)
        base_pose = self.kf_poses[base_idx]
        parts = []
        for k in range(start, base_idx + 1):
            rel = base_pose.between(self.kf_poses[k])
            cc, ss = np.cos(rel.theta()), np.sin(rel.theta())
            R = np.array([[cc, -ss], [ss, cc]], dtype=np.float32)
            t = np.array([rel.x(), rel.y()], dtype=np.float32)
            parts.append(self.kf_scans[k] @ R.T + t)
        if not parts:
            self._submap_pts = np.zeros((0, 2), dtype=np.float32)
            self._submap_tree = cKDTree(np.zeros((1, 2)))
        else:
            pts = voxel_downsample(np.vstack(parts), self.cfg.voxel_size)
            self._submap_pts = pts
            self._submap_tree = cKDTree(pts)
        self._submap_anchor = base_idx
        return self._submap_pts, self._submap_tree

    def inject_loop_factor(self, j: int, i: int, rel: gtsam.Pose2, rmse: float):
        if j >= self.n_kf or i >= self.n_kf:
            return
        self._pending_factors.add(gtsam.BetweenFactorPose2(
            X(j), X(i), rel, self._loop_noise))
        self.loop_closures.append((j, i, rmse))

    def flush(self):
        self._flush_isam()

    def _flush_isam(self):
        if self._pending_factors.size() == 0 and self._pending_values.size() == 0:
            return
        t0 = time.perf_counter()
        self.isam.update(self._pending_factors, self._pending_values)
        self._pending_factors = gtsam.NonlinearFactorGraph()
        self._pending_values  = gtsam.Values()
        result = self.isam.calculateEstimate()
        for k in range(self.n_kf):
            self.kf_poses[k] = result.atPose2(X(k))
        self.current_pose = self.kf_poses[-1]
        self._submap_anchor = -1
        self.timings["isam"].append((time.perf_counter() - t0) * 1e3)

    def trajectory(self) -> np.ndarray:
        return np.array([[p.x(), p.y(), p.theta()] for p in self.kf_poses])

    def global_map(self, stride: int = 1) -> np.ndarray:
        pts = []
        for k in range(0, self.n_kf, stride):
            p = self.kf_poses[k]
            cc, ss = np.cos(p.theta()), np.sin(p.theta())
            R = np.array([[cc, -ss], [ss, cc]], dtype=np.float32)
            pts.append(self.kf_scans[k] @ R.T
                       + np.array([p.x(), p.y()], dtype=np.float32))
        return np.vstack(pts) if pts else np.zeros((0, 2), dtype=np.float32)


# ---------------------------------------------------------------------------
# Loop-closure worker
# ---------------------------------------------------------------------------
class LoopClosureWorker(threading.Thread):
    """Runs ICP loop validation off the SLAM main thread."""
    def __init__(self, slam: LidarSLAM2D, slam_lock: threading.Lock,
                 in_q: queue.Queue, out_q: queue.Queue, cfg: SLAMConfig):
        super().__init__(daemon=True, name="LoopClosure")
        self.slam = slam
        self.slam_lock = slam_lock
        self.in_q = in_q
        self.out_q = out_q
        self.cfg = cfg
        self._stop = threading.Event()
        self.timings: List[float] = []

    def stop(self): self._stop.set()

    @staticmethod
    def _wrap(a: float) -> float:
        return float(np.arctan2(np.sin(a), np.cos(a)))

    def run(self):
        while not self._stop.is_set():
            try:
                i = self.in_q.get(timeout=0.2)
            except queue.Empty:
                continue
            t0 = time.perf_counter()

            # Snapshot under the lock; scans are append-only so we can keep
            # reading them without the lock as long as indices are bounded.
            with self.slam_lock:
                if i >= self.slam.n_kf:
                    continue
                current = self.slam.kf_poses[i]
                max_j = i - self.cfg.loop_min_kf_gap
                if max_j <= 0:
                    self.timings.append((time.perf_counter() - t0) * 1e3)
                    continue
                xy  = np.array([[p.x(), p.y()] for p in self.slam.kf_poses[:max_j]])
                ths = np.array([p.theta()        for p in self.slam.kf_poses[:max_j]])

            cx, cy, cth = current.x(), current.y(), current.theta()
            tree = cKDTree(xy)
            cand = tree.query_ball_point([cx, cy], self.cfg.loop_search_radius)
            if not cand:
                self.timings.append((time.perf_counter() - t0) * 1e3)
                continue
            cand.sort(key=lambda j: (cx - xy[j, 0])**2 + (cy - xy[j, 1])**2)
            cand = cand[: self.cfg.loop_max_candidates * 3]

            scan_i = self.slam.kf_scans[i]   # immutable once added

            best = None
            tried = 0
            for j in cand:
                if tried >= self.cfg.loop_max_candidates:
                    break
                if abs(self._wrap(cth - float(ths[j]))) > self.cfg.loop_max_heading_diff:
                    continue
                tried += 1
                old_pose = gtsam.Pose2(float(xy[j, 0]), float(xy[j, 1]), float(ths[j]))
                guess = old_pose.between(current)
                scan_j = self.slam.kf_scans[j]
                rel, rmse, ratio, ninl = pl_icp_2d(scan_i, scan_j, guess)
                if (rmse  < self.cfg.loop_rmse_thresh
                        and ratio > self.cfg.loop_inlier_thresh
                        and ninl  > self.cfg.loop_min_inliers
                        and (best is None or rmse < best[0])):
                    best = (rmse, j, rel)

            if best is not None:
                rmse, j, rel = best
                try: self.out_q.put_nowait((j, i, rel, rmse))
                except queue.Full: pass
            self.timings.append((time.perf_counter() - t0) * 1e3)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class RealtimeLidarSLAM:
    def __init__(self,
                 lidar_shm_name: str, lidar_sem_name: str,
                 odom_shm_name:  str, odom_sem_name:  str,
                 cfg: Optional[SLAMConfig] = None):
        self.cfg = cfg or SLAMConfig()
        self.lidar_shm = ShmRegion(lidar_shm_name, LIDAR_DTYPE, create=False)
        self.lidar_sem = NamedSemaphore(lidar_sem_name)
        self.odom_shm  = ShmRegion(odom_shm_name,  ODOM_DTYPE,  create=False)
        self.odom_sem  = NamedSemaphore(odom_sem_name)

        self.slam = LidarSLAM2D(self.cfg)
        self.slam_lock = threading.Lock()

        self.lidar_q   : queue.Queue = queue.Queue(maxsize=4)
        self.loop_in_q : queue.Queue = queue.Queue(maxsize=8)
        self.loop_out_q: queue.Queue = queue.Queue(maxsize=16)

        self.odom_reader  = OdomReader(self.odom_shm, self.odom_sem)
        self.lidar_reader = LidarReader(self.lidar_shm, self.lidar_sem, self.lidar_q)
        self.loop_worker  = LoopClosureWorker(
            self.slam, self.slam_lock, self.loop_in_q, self.loop_out_q, self.cfg)

        self._stop = threading.Event()
        self._main_thread = threading.Thread(
            target=self._main_loop, daemon=True, name="SLAM")

        self.timings = {"frame": [], "kf": [], "icp": [], "undistort": []}

    def start(self):
        self.odom_reader.start()
        self.lidar_reader.start()
        self.loop_worker.start()
        self._main_thread.start()

    def stop(self):
        self._stop.set()
        self.lidar_reader.stop()
        self.odom_reader.stop()
        self.loop_worker.stop()
        # nudge readers blocked on semaphores
        try: self.lidar_sem.release()
        except Exception: pass
        try: self.odom_sem.release()
        except Exception: pass
        for t in (self._main_thread, self.lidar_reader, self.odom_reader, self.loop_worker):
            try: t.join(timeout=1.0)
            except Exception: pass
        self.lidar_shm.close()
        self.odom_shm.close()
        self.lidar_sem.close()
        self.odom_sem.close()

    def trajectory(self) -> np.ndarray:
        with self.slam_lock:
            return self.slam.trajectory()

    def global_map(self, stride: int = 1) -> np.ndarray:
        with self.slam_lock:
            return self.slam.global_map(stride)

    def loop_count(self) -> int:
        with self.slam_lock:
            return len(self.slam.loop_closures)

    # ---- main loop --------------------------------------------------------
    def _main_loop(self):
        last_imu_pose: Optional[gtsam.Pose2] = None
        delta_since_kf = gtsam.Pose2(0, 0, 0)

        while not self._stop.is_set():
            try:
                seq, t_lidar, sweep, scan = self.lidar_q.get(timeout=0.2)
            except queue.Empty:
                continue
            t_frame = time.perf_counter()

            imu_xyt = self.odom_reader.pose_at(t_lidar)
            if imu_xyt is None:
                continue
            imu_pose = gtsam.Pose2(*imu_xyt)

            # Scan motion-compensation using 50 Hz IMU samples
            if self.cfg.enable_undistort and last_imu_pose is not None:
                t_un = time.perf_counter()
                scan = self._undistort(scan, t_lidar - sweep, sweep, imu_xyt)
                self.timings["undistort"].append((time.perf_counter() - t_un) * 1e3)

            if last_imu_pose is None:
                with self.slam_lock:
                    self.slam.add_first_scan(scan, imu_pose)
                last_imu_pose = imu_pose
                continue

            odom_delta = last_imu_pose.between(imu_pose)
            delta_since_kf = delta_since_kf.compose(odom_delta)

            # Inject loop closures discovered by the worker
            self._drain_loop_results()

            # Spawn a keyframe?
            d = delta_since_kf
            if (np.hypot(d.x(), d.y()) > self.cfg.kf_trans
                    or abs(d.theta()) > self.cfg.kf_rot):
                self._handle_keyframe(scan, delta_since_kf)
                delta_since_kf = gtsam.Pose2(0, 0, 0)

            last_imu_pose = imu_pose
            self.timings["frame"].append((time.perf_counter() - t_frame) * 1e3)

    def _handle_keyframe(self, scan: np.ndarray, odom_delta: gtsam.Pose2):
        t0 = time.perf_counter()
        scan_ds = voxel_downsample(scan, self.cfg.voxel_size)

        with self.slam_lock:
            base_idx = self.slam.n_kf - 1
            submap, tree = self.slam.get_submap(base_idx)

        t_icp = time.perf_counter()
        if len(submap) > 10:
            refined, rmse, _, _ = pl_icp_2d(scan_ds, submap, odom_delta, target_tree=tree)
            diff = odom_delta.between(refined)
            if (np.hypot(diff.x(), diff.y()) > self.cfg.icp_max_trans_dev
                    or abs(diff.theta()) > self.cfg.icp_max_rot_dev
                    or rmse > self.cfg.icp_max_rmse):
                refined = odom_delta
        else:
            refined = odom_delta
        self.timings["icp"].append((time.perf_counter() - t_icp) * 1e3)

        with self.slam_lock:
            j_new = self.slam.add_keyframe(scan_ds, refined)
            self.slam.flush()

        if j_new % self.cfg.loop_every_n_kf == 0:
            try: self.loop_in_q.put_nowait(j_new)
            except queue.Full: pass

        self.timings["kf"].append((time.perf_counter() - t0) * 1e3)

    def _drain_loop_results(self):
        if self.loop_out_q.empty():
            return
        injected = False
        while True:
            try:
                j, i, rel, rmse = self.loop_out_q.get_nowait()
            except queue.Empty:
                break
            with self.slam_lock:
                self.slam.inject_loop_factor(j, i, rel, rmse)
                injected = True
        if injected:
            with self.slam_lock:
                self.slam.flush()

    def _undistort(self, pts: np.ndarray, t_start: float, sweep: float,
                   ref_xyth: Tuple[float, float, float]) -> np.ndarray:
        n = len(pts)
        if n == 0:
            return pts
        ts = t_start + (np.arange(n, dtype=np.float64) / max(n - 1, 1)) * sweep
        with self.odom_reader.lock:
            buf = list(self.odom_reader.buffer)
        if len(buf) < 2:
            return pts
        bts  = np.array([b[0] for b in buf])
        bxs  = np.array([b[1] for b in buf])
        bys  = np.array([b[2] for b in buf])
        bths = np.array([b[3] for b in buf])

        idx = np.searchsorted(bts, ts) - 1
        idx = np.clip(idx, 0, len(bts) - 2)
        t0 = bts[idx]; t1 = bts[idx + 1]
        u  = np.clip((ts - t0) / np.maximum(t1 - t0, 1e-9), 0.0, 1.0)
        x_i = bxs[idx] + u * (bxs[idx + 1] - bxs[idx])
        y_i = bys[idx] + u * (bys[idx + 1] - bys[idx])
        dth_raw = bths[idx + 1] - bths[idx]
        dth_raw = (dth_raw + np.pi) % (2 * np.pi) - np.pi
        th_i = bths[idx] + u * dth_raw

        rx, ry, rth = ref_xyth
        dxw = x_i - rx; dyw = y_i - ry
        cc, ss = np.cos(-rth), np.sin(-rth)
        dx = (cc * dxw - ss * dyw).astype(np.float32)
        dy = (ss * dxw + cc * dyw).astype(np.float32)
        dth = (th_i - rth).astype(np.float32)
        cc2 = np.cos(dth); ss2 = np.sin(dth)

        out = np.empty_like(pts)
        out[:, 0] = dx + cc2 * pts[:, 0] - ss2 * pts[:, 1]
        out[:, 1] = dy + ss2 * pts[:, 0] + cc2 * pts[:, 1]
        return out


# ===========================================================================
# DEMO: simulated producer + the real consumer talking through real shm/sems
# ===========================================================================
def _build_world():
    segs = []
    def poly(pts):
        arr = np.asarray(pts, dtype=float)
        for a, b in zip(arr[:-1], arr[1:]):
            segs.append((a, b))
    poly([[-12, -12], [12, -12], [12, 12], [-12, 12], [-12, -12]])
    poly([[-3, -3], [3, -3], [3, 3], [-3, 3], [-3, -3]])
    poly([[-10, 0], [-6, 0]])
    poly([[6, -6], [9, -3]])
    poly([[-8, 6], [-5, 6], [-5, 9]])
    poly([[4, 8], [8, 8]])
    return segs


def _raycast(origin, angle, walls, max_range):
    d = np.array([np.cos(angle), np.sin(angle)])
    best = max_range
    for a, b in walls:
        seg = b - a
        det = d[0] * (-seg[1]) - d[1] * (-seg[0])
        if abs(det) < 1e-9:
            continue
        rhs = a - origin
        t = (rhs[0] * (-seg[1]) - rhs[1] * (-seg[0])) / det
        u = (d[0] * rhs[1] - d[1] * rhs[0]) / det
        if t >= 0 and 0 <= u <= 1 and t < best:
            best = t
    return best


def _simulate_scan(pose, walls, n_beams=N_BEAMS, fov=np.deg2rad(240),
                   max_range=10.0, noise_std=0.015):
    x, y, th = pose
    origin = np.array([x, y])
    angles = np.linspace(-fov / 2, fov / 2, n_beams)
    pts = np.empty((n_beams, 2), dtype=np.float32)
    valid = 0
    for a in angles:
        r = _raycast(origin, th + a, walls, max_range)
        if r < max_range - 1e-3:
            r += np.random.randn() * noise_std
            pts[valid, 0] = r * np.cos(a)
            pts[valid, 1] = r * np.sin(a)
            valid += 1
    return pts[:valid]


def _make_trajectory_50hz(speed=0.6, side=8.0, laps=2):
    """Return a 50 Hz sample of a rectangular trajectory at given speed."""
    dt = 0.02
    step = speed * dt
    legs = [(0.0, side), (np.pi / 2, side), (np.pi, side), (-np.pi / 2, side)]
    x, y = -side / 2, -side / 2
    traj = [(x, y, 0.0)]
    for _ in range(laps):
        for heading, length in legs:
            n = int(length / step)
            for _ in range(n):
                x += step * np.cos(heading)
                y += step * np.sin(heading)
                traj.append((x, y, heading))
    return traj


def _make_diff_drive_trajectory(hz=50, speed=0.6, side=8.0, laps=2):
    """
    Simulates a differential drive robot following a specific set of legs.
    Uses exact circular arc integration.
    """
    dt = 1.0 / hz
    x, y = -side / 2, -side / 2
    curr_theta = 0.0
    traj = [(x, y, curr_theta)]

    legs = [(0.0, side), (np.pi / 2, side), (np.pi, side), (-np.pi / 2, side)]

    for _ in range(laps):
        for target_heading, length in legs:
            # Calculate the shortest angular distance (wrap to -pi to pi)
            d_theta = (target_heading - curr_theta + np.pi) % (2 * np.pi) - np.pi

            # We assume a fixed angular velocity for the turn (e.g., 1.0 rad/s)
            w_turn = 1.0 if d_theta > 0 else -1.0
            if abs(d_theta) > 1e-6:
                turn_duration = abs(d_theta / w_turn)
                turn_steps = int(turn_duration / dt)

                for _ in range(turn_steps):
                    x, y, th = traj[-1]
                    # Since v=0, this is pure rotation
                    nth = (th + w_turn * dt + np.pi) % (2 * np.pi) - np.pi
                    traj.append((x, y, nth))

                # Snap to exact heading to prevent drift
                x, y, _ = traj[-1]
                traj[-1] = (x, y, target_heading)
                curr_theta = target_heading

            v = speed
            w = 0.0  # Straight line
            duration = length / v
            move_steps = int(duration / dt)

            for _ in range(move_steps):
                x, y, th = traj[-1]
                # Straight line integration (v > 0, w = 0)
                nx = x + v * np.cos(th) * dt
                ny = y + v * np.sin(th) * dt
                traj.append((nx, ny, th))

    return traj

class ProducerSim:
    """Simulates the C-side producer: writes shm + posts semaphores at the
    requested rates. A `sim_speed` of 1 means real time."""
    def __init__(self,
                 lidar_shm: ShmRegion, lidar_sem: NamedSemaphore,
                 odom_shm:  ShmRegion, odom_sem:  NamedSemaphore,
                 trajectory_50hz, walls,
                 sim_speed: float = 1.0,
                 odom_k_d: float = 0.05,  # Encoder distance error std dev (m/sqrt(m))
                 odom_k_th: float = 0.02,  # Gyro scale factor error std dev (rad/sqrt(rad))
                 gyro_arw: float = 0.005):
        self.lidar_shm = lidar_shm; self.lidar_sem = lidar_sem
        self.odom_shm  = odom_shm;  self.odom_sem  = odom_sem
        self.traj = trajectory_50hz
        self.walls = walls
        self.sim_speed = sim_speed
        self.odom_dt  = 0.020 / sim_speed
        self.lidar_dt = 0.100 / sim_speed
        self.lidar_sweep = self.lidar_dt

        # Noise parameters
        self.odom_k_d = odom_k_d
        self.odom_k_th = odom_k_th
        self.gyro_arw = gyro_arw

        self._stop = threading.Event()
        self._done = threading.Event()
        self.odom_seq = 0
        self.lidar_seq = 0
        self.cum = np.zeros(3)

        self.noisy_pose = np.zeros(3, dtype=float)
        self.odom_history = []
        self.rng = np.random.default_rng(0)
        self._odom_t  = threading.Thread(target=self._odom_loop,  daemon=True, name="ProdOdom")
        self._lidar_t = threading.Thread(target=self._lidar_loop, daemon=True, name="ProdLidar")

    def start(self):
        self._odom_t.start()
        self._lidar_t.start()

    def stop(self):
        self._stop.set()

    def is_done(self) -> bool:
        return self._done.is_set()

    def _odom_loop(self):
        next_t = time.monotonic()
        i = 0
        n = len(self.traj)

        while not self._stop.is_set() and i < n:
            now = time.monotonic()
            if now < next_t:
                time.sleep(next_t - now)

            gt = self.traj[i]

            if i == 0:
                # Initialize the estimator precisely at the ground-truth start
                self.noisy_pose[:] = gt
                noisy_x, noisy_y, noisy_th = gt
            else:
                gt_prev = self.traj[i - 1]

                # Extract true incremental motion
                dx = gt[0] - gt_prev[0]
                dy = gt[1] - gt_prev[1]
                true_d = np.hypot(dx, dy)
                true_dth = (gt[2] - gt_prev[2] + np.pi) % (2 * np.pi) - np.pi

                # 1. Simulate encoder distance measurement
                var_d = (self.odom_k_d ** 2) * true_d
                noisy_d = true_d + self.rng.normal(0.0, np.sqrt(var_d))

                # 2. Simulate gyroscope heading measurement (Scale factor + ARW)
                # Note: true delta-t of integration is 0.020s, scaling by sim_speed
                # preserves the mathematical variance accumulation with respect to virtual time.
                var_th = (self.odom_k_th ** 2) * abs(true_dth) + (self.gyro_arw ** 2) * (self.odom_dt * self.sim_speed)
                noisy_dth = true_dth + self.rng.normal(0.0, np.sqrt(var_th))

                # 3. Mid-point integration (Runge-Kutta 2nd Order)
                mid_th = self.noisy_pose[2] + noisy_dth / 2.0

                self.noisy_pose[0] += noisy_d * np.cos(mid_th)
                self.noisy_pose[1] += noisy_d * np.sin(mid_th)
                self.noisy_pose[2] = (self.noisy_pose[2] + noisy_dth + np.pi) % (2 * np.pi) - np.pi

                noisy_x, noisy_y, noisy_th = self.noisy_pose

            self.odom_history.append((noisy_x, noisy_y, noisy_th))

            view = self.odom_shm.array
            self.odom_seq += 1
            view['seq'][0] = self.odom_seq
            view['timestamp'][0] = time.time()
            view['x'][0] = noisy_x
            view['y'][0] = noisy_y
            view['theta'][0] = noisy_th
            self.odom_sem.release()

            i += 1
            next_t += self.odom_dt

        self._done.set()

    def _lidar_loop(self):
        next_t = time.monotonic()
        i = 0
        n = len(self.traj)
        while not self._stop.is_set() and i < n:
            now = time.monotonic()
            if now < next_t:
                time.sleep(next_t - now)
            gt = self.traj[i]
            scan = _simulate_scan(gt, self.walls)
            view = self.lidar_shm.array
            self.lidar_seq += 1
            view['seq'][0]            = self.lidar_seq
            view['timestamp'][0]      = time.time()
            view['sweep_duration'][0] = self.lidar_sweep
            k = len(scan)
            view['n_points'][0]       = k
            view['capacity'][0]       = N_BEAMS
            view['points'][0, :k]     = scan
            self.lidar_sem.release()
            i += 5  # 50 Hz / 5 = 10 Hz
            next_t += self.lidar_dt


def run_demo():
    import matplotlib.pyplot as plt

    pid = os.getpid()
    lidar_shm_name = f"/lslam_lidar_{pid}"
    odom_shm_name  = f"/lslam_odom_{pid}"
    lidar_sem_name = f"/lslam_lsem_{pid}"
    odom_sem_name  = f"/lslam_osem_{pid}"

    lidar_shm = ShmRegion(lidar_shm_name, LIDAR_DTYPE, create=True)
    odom_shm  = ShmRegion(odom_shm_name,  ODOM_DTYPE,  create=True)
    lidar_sem = NamedSemaphore(lidar_sem_name, create=True, initial=0)
    odom_sem  = NamedSemaphore(odom_sem_name,  create=True, initial=0)

    slam = None
    prod = None
    try:
        np.random.seed(0)
        walls = _build_world()
        # traj = _make_trajectory_50hz(speed=0.6, side=8.0, laps=2)
        traj = _make_diff_drive_trajectory(hz=50, side=8.0, laps=2)

        # sim_speed=1.0 means real-time. Larger values stress-test the pipeline.
        SIM_SPEED = 4.0

        prod = ProducerSim(lidar_shm, lidar_sem, odom_shm, odom_sem,
                           traj, walls, sim_speed=SIM_SPEED,
                           odom_k_d=0.15, odom_k_th=0.1, gyro_arw=0.005)

        slam = RealtimeLidarSLAM(
            lidar_shm_name=lidar_shm_name, lidar_sem_name=lidar_sem_name,
            odom_shm_name=odom_shm_name,  odom_sem_name=odom_sem_name)
        slam.start()
        prod.start()

        # Wait for producer to finish + drain
        while not prod.is_done():
            time.sleep(0.05)
        time.sleep(0.5)

        traj_opt = slam.trajectory()
        map_pts  = slam.global_map()
        odom_arr = np.asarray(prod.odom_history)

        def stat(xs):
            if not xs: return (0.0, 0.0, 0.0)
            return (float(np.mean(xs)), float(np.percentile(xs, 95)), float(np.max(xs)))

        fr_m, fr_p, fr_x = stat(slam.timings["frame"])
        kf_m, kf_p, kf_x = stat(slam.timings["kf"])
        ic_m, ic_p, _    = stat(slam.timings["icp"])
        un_m, un_p, _    = stat(slam.timings["undistort"])
        is_m, is_p, _    = stat(slam.slam.timings["isam"])
        lc_m, lc_p, lc_x = stat(slam.loop_worker.timings)

        print(f"\n---- Real-time demo (sim speed {SIM_SPEED}×) ----")
        print(f"odom samples consumed:    {slam.odom_reader.received}")
        print(f"lidar scans consumed:     {slam.lidar_reader.received}")
        print(f"lidar scans dropped:      {slam.lidar_reader.dropped}")
        print(f"keyframes:                {slam.slam.n_kf}")
        print(f"loop closures:            {slam.loop_count()}")
        print(f"\n---- Per-call timings (ms) — this machine ----")
        print(f"per LiDAR frame:          mean {fr_m:6.2f}  p95 {fr_p:6.2f}  max {fr_x:6.2f}")
        print(f"per keyframe (total):     mean {kf_m:6.2f}  p95 {kf_p:6.2f}  max {kf_x:6.2f}")
        print(f"  PL-ICP scan→submap:     mean {ic_m:6.2f}  p95 {ic_p:6.2f}")
        print(f"  scan undistortion:      mean {un_m:6.2f}  p95 {un_p:6.2f}")
        print(f"  iSAM2 update:           mean {is_m:6.2f}  p95 {is_p:6.2f}")
        print(f"loop ICP (background):    mean {lc_m:6.2f}  p95 {lc_p:6.2f}  max {lc_x:6.2f}")
        print(f"  (background work — does NOT block the per-frame budget)")

        fig, ax = plt.subplots(figsize=(8, 8))
        for a, b in walls:
            ax.plot([a[0], b[0]], [a[1], b[1]], 'lightgray', lw=1)
        if len(map_pts):
            ax.scatter(map_pts[:, 0], map_pts[:, 1], s=0.4, c='k', alpha=0.4)
        gt_arr = np.asarray(traj)
        ax.plot(gt_arr[:, 0], gt_arr[:, 1], 'g--', lw=1.0, label='ground truth')
        if len(odom_arr):
            ax.plot(odom_arr[:, 0], odom_arr[:, 1], 'r-.', lw=1.0, alpha=0.7, label='raw odometry')
        if len(traj_opt):
            ax.plot(traj_opt[:, 0], traj_opt[:, 1], 'b-', lw=1.4, label='SLAM optimized')
        ax.set_aspect('equal'); ax.grid(True); ax.legend()
        ax.set_title(f"Real-time SLAM through SHM+sem — "
                     f"{slam.slam.n_kf} keyframes, {slam.loop_count()} loops")
        plt.tight_layout()
        plt.savefig("slam_v4_result.png", dpi=130)
        plt.close(fig)
        print("\nfigure saved to slam_v4_result.png")
    finally:
        try:
            if prod is not None: prod.stop()
        except Exception: pass
        try:
            if slam is not None: slam.stop()
        except Exception: pass
        time.sleep(0.1)
        for r in (lidar_shm, odom_shm):
            r.close(); r.unlink()
        for s in (lidar_sem, odom_sem):
            s.close(); s.unlink()


if __name__ == "__main__":
    run_demo()
