#!/usr/bin/env python3
"""
Real-time 2D LiDAR SLAM with shared-memory IPC, for a Raspberry Pi.

External producers (e.g., a C/C++ driver) write to two POSIX shared-memory
regions and post two POSIX named semaphores:

  - LiDAR     : 228x2 xy points + timestamp + sweep duration, ~10 Hz
  - Odometry  : integrated SE(2) pose (wheel encoders + gyro), ~50 Hz

Every region is guarded by a seqlock (see "Wire format" below), so a reader
never keeps a half-written sample.

This Python process attaches by name and runs SLAM in four threads:

  OdomReader  ─ blocks on odom semaphore, fills 50 Hz pose ring buffer
  LidarReader ─ blocks on lidar semaphore, pushes scans onto a queue
  SLAM main   ─ pops scans, samples the odometry pose at scan time,
                undistorts, runs PL-ICP vs the local submap, writes
                wheel-odometry + scan-matching factors into iSAM2
  LoopClosure ─ runs loop-validation ICP off the critical path; results
                are re-injected into iSAM2 by the main thread

Design notes:
  - Point-to-line ICP (Censi, ICRA 2008) with KISS-ICP's adaptive
    correspondence gate and Geman-McClure kernel (Vizzo et al., RA-L 2023)
  - Two factors per keyframe: wheel odometry (σ from the odometry noise
    model) always, plus scan matching (inflated ICP covariance) when ICP
    passes its guards — a rejected ICP never masquerades as a precise one
  - Loop closures: degeneracy check (cf. Zhang et al., ICRA 2016), ICP
    covariance, and a Cauchy kernel so a wrong loop cannot wreck the map
    (cf. Dynamic Covariance Scaling, Agarwal et al., ICRA 2013); run
    asynchronously, off the per-frame budget
  - Points stored as float32; ICP normal equations solved in float64
  - Submap points + KD-tree + normals memoised per base keyframe: reused only
    while the base keyframe is unchanged AND no pose in the submap window has
    moved (relative to the base) since it was built; rebuilt otherwise. The
    main loop asks for it once per new keyframe, so in practice it is built
    once per keyframe and only saves work on repeated requests.
  - Append-only voxelized scan storage (raw scans dropped)
  - Per-beam scan motion-compensation using the 50 Hz odometry samples and
    SE(2) geodesic interpolation

iSAM2 is touched by the main thread only; loop closures cross thread
boundaries through a queue, so the GTSAM data structures stay single-writer.

Run `python lidar_slam_2d.py` for the full demo, or
`python lidar_slam_2d.py --smoke` for a short headless start/stop test.
"""

from __future__ import annotations

import os, sys, time, queue, threading
from collections import deque
from dataclasses import dataclass
from typing import List, NamedTuple, Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree
import gtsam
from gtsam.symbol_shorthand import X
from multiprocessing import shared_memory

import posix_ipc


# ---------------------------------------------------------------------------
# Wire format — must match the C producer side
# ---------------------------------------------------------------------------
# `seq` is a seqlock counter. The writer makes it odd, writes the payload,
# then makes it even again:
#     seq = s + 1  (odd: write in progress)   [release fence]
#     ...payload...                            [release fence]
#     seq = s + 2  (even: stable)             then sem_post()
# A reader copies the record and accepts it only if `seq` was even and
# unchanged across the copy; otherwise it retries. In C use
# __atomic_store_n / __atomic_thread_fence for the fences. Python cannot emit
# fences itself, so on weakly-ordered CPUs the reader side is best-effort;
# the sem_post/sem_wait pair still orders the common case.
N_BEAMS = 228
LIDAR_FOV = np.deg2rad(240.0)   # beams swept from -FOV/2 to +FOV/2 in time order

ODOM_DTYPE = np.dtype([
    ('seq',       '<u8'),   # 8  seqlock counter (even = stable)
    ('timestamp', '<f8'),   # 8  (epoch seconds)
    ('x',         '<f8'),   # 8
    ('y',         '<f8'),   # 8
    ('theta',     '<f8'),   # 8  → 40 bytes
])

LIDAR_DTYPE = np.dtype([
    ('seq',            '<u8'),   # 8  seqlock counter (even = stable)
    ('timestamp',      '<f8'),   # 8  (end of sweep)
    ('sweep_duration', '<f8'),   # 8
    ('n_points',       '<u4'),   # 4  (valid points; the rest are padding)
    ('capacity',       '<u4'),   # 4
    ('points',         '<f4', (N_BEAMS, 2)),  # 1824 → 1856 bytes total
])


# ---------------------------------------------------------------------------
# IPC wrappers
# ---------------------------------------------------------------------------
_CREATED_HERE: set = set()   # shm names this process created (and owns)


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
            _CREATED_HERE.add(name)
        elif sys.version_info >= (3, 13):
            # Attaching must not register the segment with resource_tracker,
            # or it would unlink the producer's memory when we exit.
            self.shm = shared_memory.SharedMemory(name=name, create=False, track=False)
        else:
            self.shm = shared_memory.SharedMemory(name=name, create=False)
            if name not in _CREATED_HERE:
                try:
                    from multiprocessing import resource_tracker
                    resource_tracker.unregister(self.shm._name, "shared_memory")
                except Exception:
                    pass
        self.array = np.ndarray((1,), dtype=dtype, buffer=self.shm.buf)

    def close(self):
        self.array = None
        try: self.shm.close()
        except Exception: pass

    def unlink(self):
        try: self.shm.unlink()
        except Exception: pass
        _CREATED_HERE.discard(self.name)


def seqlock_read(view: np.ndarray, max_tries: int = 1000
                 ) -> Optional[Tuple[int, np.void]]:
    """Consistent snapshot of a seqlock-guarded record: (seq, record copy)."""
    for _ in range(max_tries):
        s1 = int(view['seq'][0])
        if s1 & 1:                 # writer is mid-update
            time.sleep(0)
            continue
        snap = view[0].copy()      # one memcpy of the whole record
        s2 = int(view['seq'][0])
        if s1 == s2:
            return s1, snap
    return None


def seqlock_write(view: np.ndarray, write_payload) -> int:
    """Writer side of the seqlock (used by the simulated producer)."""
    s = int(view['seq'][0])
    view['seq'][0] = s + 1         # odd: in progress
    write_payload(view)
    view['seq'][0] = s + 2         # even: stable
    return s + 2


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
# SE(2) geodesic interpolation (vectorised) — shared by pose_at + _undistort
# ---------------------------------------------------------------------------
def _sinc_terms(w: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """A = sin(w)/w, B = (1 - cos w)/w, with Taylor series near w = 0."""
    small = np.abs(w) < 1e-6
    ws = np.where(small, 1.0, w)
    A = np.where(small, 1.0 - w * w / 6.0, np.sin(ws) / ws)
    B = np.where(small, w / 2.0, (1.0 - np.cos(ws)) / ws)
    return A, B


def se2_interp(xa, ya, tha, xb, yb, thb, u):
    """Pose at fraction u along the SE(2) geodesic from a to b:
    a ⊕ Exp(u · Log(a⁻¹ ⊕ b)). Arguments broadcast as numpy arrays."""
    xa, ya, tha, xb, yb, thb, u = map(np.asarray, (xa, ya, tha, xb, yb, thb, u))
    ca, sa = np.cos(tha), np.sin(tha)
    # a⁻¹ ⊕ b
    dxw, dyw = xb - xa, yb - ya
    dx = ca * dxw + sa * dyw
    dy = -sa * dxw + ca * dyw
    w = np.arctan2(np.sin(thb - tha), np.cos(thb - tha))
    # Log: rho = V(w)⁻¹ · [dx, dy],  V = [[A, -B], [B, A]]
    A, B = _sinc_terms(w)
    det = A * A + B * B
    rx = ( A * dx + B * dy) / det
    ry = (-B * dx + A * dy) / det
    # Exp(u · [rho, w]) = [V(u w) · u rho, u w]
    uw = u * w
    A2, B2 = _sinc_terms(uw)
    tx = u * (A2 * rx - B2 * ry)
    ty = u * (B2 * rx + A2 * ry)
    # a ⊕ (tx, ty, uw)
    x = xa + ca * tx - sa * ty
    y = ya + sa * tx + ca * ty
    th = np.arctan2(np.sin(tha + uw), np.cos(tha + uw))
    return x, y, th


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
        self.torn_retries_failed = 0
        # NB: not `_stop` — that would shadow threading.Thread._stop()
        self._stop_evt = threading.Event()

    def stop(self): self._stop_evt.set()

    def run(self):
        view = self.shm.array
        while not self._stop_evt.is_set():
            if not self.sem.acquire(timeout=0.2):
                continue
            got = seqlock_read(view)
            if got is None:
                self.torn_retries_failed += 1
                continue
            seq, rec = got
            if seq == self.last_seq or seq == 0:
                continue
            self.last_seq = seq
            sample = (float(rec['timestamp']), float(rec['x']),
                      float(rec['y']), float(rec['theta']))
            with self.lock:
                self.buffer.append(sample)
                self.received += 1

    def latest(self) -> Optional[Tuple[float, float, float, float]]:
        with self.lock:
            return self.buffer[-1] if self.buffer else None

    def pose_at(self, t: float, wait: float = 0.05
                ) -> Optional[Tuple[float, float, float]]:
        """SE(2)-geodesic interpolation of the pose at time t. Briefly waits
        for a fresh odom sample if the buffer hasn't reached t yet."""
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
        x, y, th = se2_interp(a[1], a[2], a[3], b[1], b[2], b[3], u)
        return float(x), float(y), float(th)


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
        self.torn_retries_failed = 0
        self._stop_evt = threading.Event()

    def stop(self): self._stop_evt.set()

    def run(self):
        view = self.shm.array
        while not self._stop_evt.is_set():
            if not self.sem.acquire(timeout=0.2):
                continue
            got = seqlock_read(view)
            if got is None:
                self.torn_retries_failed += 1
                continue
            seq, rec = got
            if seq == self.last_seq or seq == 0:
                continue
            n     = min(int(rec['n_points']), N_BEAMS)
            ts    = float(rec['timestamp'])
            sweep = float(rec['sweep_duration'])
            pts   = np.array(rec['points'][:n], dtype=np.float32, copy=True)
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
# Voxel + PL-ICP
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


class ICPResult(NamedTuple):
    pose: gtsam.Pose2       # source frame expressed in target frame
    rmse: float             # point-to-line RMSE of gated pairs at the returned pose
    inlier_ratio: float     # fraction of source points within the gate
    n_inliers: int
    H: np.ndarray           # 3x3 JᵀJ of gated pairs at the returned pose, in
                            # (tx, ty, θ) of the target frame
    degeneracy: float       # λ_min / trace of H's translation block, in [0, 0.5]
                            # (≈0: one direction unconstrained, e.g. a corridor)


def estimate_normals(points: np.ndarray, tree: cKDTree, k: int = 6) -> np.ndarray:
    """Unit normal of the local line at every point: the eigenvector with the
    smallest eigenvalue of its k-neighbourhood covariance (PCA)."""
    k = min(k, len(points))
    _, idx = tree.query(points, k=k)
    nb = points[idx].astype(np.float64)
    nb -= nb.mean(axis=1, keepdims=True)
    C = np.einsum('nki,nkj->nij', nb, nb)
    _, V = np.linalg.eigh(C)
    return V[:, :, 0]


def pl_icp_2d(source: np.ndarray, target: np.ndarray,
              init_pose: gtsam.Pose2,
              max_corr_dist: float, kernel: float,
              target_tree: Optional[cKDTree] = None,
              target_normals: Optional[np.ndarray] = None,
              max_iter: int = 50, tol: float = 1e-4) -> ICPResult:
    """Point-to-line ICP (the metric of Censi, ICRA 2008 "PL-ICP"), solved by
    Gauss-Newton with robust IRLS weights.

    Each source point is paired with its nearest target point q and measured
    along q's line normal n (PCA of q's 6 nearest neighbours):
        r = (R p + t − q) · n
    Pairs farther apart than `max_corr_dist` are ignored and the rest are
    weighted with the Geman-McClure kernel w = κ² / (κ + r²)². Both come from
    KISS-ICP (Vizzo et al., RA-L 2023), where the gate is 3σ and κ = σ/3 for
    an adaptively estimated σ (see AdaptiveThreshold).

    Stops when the update step ‖δ‖ < `tol`, then re-evaluates RMSE, inliers
    and the information matrix H at the returned pose. Solved in float64 with
    a tiny trace-scaled damping term.
    """
    fail = ICPResult(init_pose, float('inf'), 0.0, 0, np.zeros((3, 3)), 0.0)
    if len(target) < 6 or len(source) < 6:
        return fail

    src = np.asarray(source, dtype=np.float64)
    tgt = np.asarray(target, dtype=np.float64)
    if target_tree is None:
        target_tree = cKDTree(tgt)
    if target_normals is None:
        target_normals = estimate_normals(tgt, target_tree)

    theta = float(init_pose.theta())
    t = np.array([init_pose.x(), init_pose.y()], dtype=np.float64)

    def correspond(theta, t):
        c, s = np.cos(theta), np.sin(theta)
        rotated = src @ np.array([[c, -s], [s, c]]).T
        transformed = rotated + t
        dist, idx = target_tree.query(transformed, k=1,
                                      distance_upper_bound=max_corr_dist)
        gated = np.isfinite(dist)               # within the correspondence gate
        idx = np.where(gated, idx, 0)
        normals = target_normals[idx]
        residuals = np.sum((transformed - tgt[idx]) * normals, axis=1)
        return rotated, normals, residuals, gated

    def jacobian(rotated, normals):
        J = np.empty((len(normals), 3))
        J[:, 0] = normals[:, 0]
        J[:, 1] = normals[:, 1]
        J[:, 2] = -normals[:, 0] * rotated[:, 1] + normals[:, 1] * rotated[:, 0]
        return J

    for _ in range(max_iter):
        rotated, normals, residuals, gated = correspond(theta, t)
        if gated.sum() < 6:
            return fail
        w = np.where(gated, kernel**2 / (kernel + residuals**2)**2, 0.0)
        J = jacobian(rotated, normals)
        Jw = J * w[:, None]
        H = Jw.T @ J
        g = Jw.T @ residuals
        H += (1e-9 * np.trace(H) + 1e-12) * np.eye(3)
        try:
            delta = np.linalg.solve(H, -g)
        except np.linalg.LinAlgError:
            return fail
        t = t + delta[:2]
        theta += float(delta[2])
        if np.linalg.norm(delta) < tol:
            break

    # Final evaluation at the pose we actually return.
    pose = gtsam.Pose2(float(t[0]), float(t[1]), theta)
    rotated, normals, residuals, gated = correspond(theta, t)
    n_inl = int(gated.sum())
    if n_inl < 6:
        return ICPResult(pose, float('inf'), n_inl / len(src), n_inl, np.zeros((3, 3)), 0.0)
    rmse = float(np.sqrt(np.mean(residuals[gated] ** 2)))
    J = jacobian(rotated[gated], normals[gated])
    H = J.T @ J
    Ht = H[:2, :2]
    degeneracy = float(np.linalg.eigvalsh(Ht)[0] / max(np.trace(Ht), 1e-12))
    return ICPResult(pose, rmse, n_inl / len(src), n_inl, H, degeneracy)


def icp_covariance(res: ICPResult, min_rmse: float = 0.01) -> np.ndarray:
    """Gauss-Newton covariance σ²·(AᵀHA)⁻¹ of an ICP pose, in the tangent space
    GTSAM uses for Pose2 (right perturbation T ⊕ Exp(ξ): δt = R(θ)·ξ_xy, so
    A = blockdiag(R(θ), 1)). σ is the residual RMSE (floored). This is an
    optimistic, local estimate — callers add a floor / inflate it."""
    c, s = np.cos(res.pose.theta()), np.sin(res.pose.theta())
    A = np.eye(3)
    A[:2, :2] = [[c, -s], [s, c]]
    info = A.T @ res.H @ A / max(res.rmse, min_rmse) ** 2
    return np.linalg.inv(info + 1e-6 * np.eye(3))


class AdaptiveThreshold:
    """KISS-ICP's adaptive correspondence threshold (Vizzo et al., RA-L 2023).

    σ is the running RMS of the *model deviation* between the odometry
    prediction and the ICP result, measured as ‖Δt‖ + 2·r_max·sin(|Δθ|/2)
    (the largest displacement that error causes on any point within r_max).
    Deviations below `min_deviation` are not counted. ICP then gates
    correspondences at 3σ and uses a Geman-McClure kernel with κ = σ/3."""
    def __init__(self, initial_sigma: float, max_range: float, min_deviation: float):
        self.sse = initial_sigma ** 2      # the initial guess counts as one sample
        self.n = 1
        self.max_range = max_range
        self.min_deviation = min_deviation

    @property
    def sigma(self) -> float:
        return float(np.sqrt(self.sse / self.n))

    def update(self, predicted: gtsam.Pose2, corrected: gtsam.Pose2):
        d = predicted.between(corrected)
        dev = np.hypot(d.x(), d.y()) + 2.0 * self.max_range * abs(np.sin(d.theta() / 2.0))
        if dev > self.min_deviation:
            self.sse += dev * dev
            self.n += 1


# ---------------------------------------------------------------------------
# SLAM core (single-threaded; orchestrator serializes access)
# ---------------------------------------------------------------------------
@dataclass
class SLAMConfig:
    voxel_size:    float = 0.07

    prior_sigmas:  Tuple[float, float, float] = (1e-3, 1e-3, 1e-4)

    # Wheel-odometry factor, added between every pair of consecutive
    # keyframes. σ follows the producer's noise model (see ProducerSim):
    # along-track k_d·√d, heading σ_θ = √(k_θ²·|Δθ| + ARW²·Δt), lateral
    # ≈ d·σ_θ/2 (heading error integrated over the segment), each + a floor.
    wheel_k_d:     float = 0.15
    wheel_k_th:    float = 0.10
    wheel_arw:     float = 0.005
    wheel_floor_sigmas: Tuple[float, float, float] = (0.01, 0.01, 0.005)

    # Scan-matching factor, added only when ICP is accepted: its Gauss-Newton
    # covariance (icp_covariance) × icp_cov_scale, plus a floor. The raw
    # covariance is far too confident (it ignores wrong correspondences).
    icp_cov_scale: float = 30.0
    icp_floor_sigmas: Tuple[float, float, float] = (0.005, 0.005, 0.002)

    kf_trans:      float = 0.30
    kf_rot:        float = 0.175
    submap_size:   int   = 6
    submap_cache_tol: float = 1e-4   # m / rad change that invalidates the cache

    # KISS-ICP adaptive threshold (AdaptiveThreshold)
    icp_initial_sigma:  float = 0.5
    icp_min_deviation:  float = 0.01
    lidar_max_range:    float = 10.0

    icp_max_trans_dev: float = 0.4    # reject ICP if it moves farther than this from
    icp_max_rot_dev:   float = 0.3    # odometry AND beyond icp_guard_nsigma·σ_wheel
    icp_guard_nsigma:  float = 5.0
    icp_max_rmse:      float = 0.3

    loop_search_radius:    float = 2.5
    loop_min_kf_gap:       int   = 15     # candidate j must satisfy i - j ≥ gap
    loop_max_heading_diff: float = np.deg2rad(75.0)
    loop_max_candidates:   int   = 4
    loop_every_n_kf:       int   = 1
    loop_cooldown_kf:      int   = 3      # after a loop at i, skip i+1 .. i+cooldown-1
    loop_rmse_thresh:      float = 0.08
    loop_inlier_thresh:    float = 0.55   # fraction of scan points within the gate
    loop_min_inliers:      int   = 40
    loop_min_degeneracy:   float = 0.10   # λ_min / trace of the translation block
    loop_max_trans_dev:    float = 1.0    # ICP result vs. estimate-based guess
    loop_max_rot_dev:      float = 0.35
    loop_sigmas:   Tuple[float, float, float] = (0.05, 0.05, 0.02)  # added to ICP cov
    loop_cauchy_k: float = 1.0            # in σ units (whitened residual)
    isam_extra_iters_after_loop: int = 3

    enable_undistort: bool = True
    lidar_angle_min: float = -LIDAR_FOV / 2   # angle of the first beam in time
    lidar_angle_max: float = +LIDAR_FOV / 2   # angle of the last beam in time


def wheel_odometry_sigmas(delta: gtsam.Pose2, dt: float, cfg: SLAMConfig) -> np.ndarray:
    d = np.hypot(delta.x(), delta.y())
    s_th = np.sqrt(cfg.wheel_k_th ** 2 * abs(delta.theta()) + cfg.wheel_arw ** 2 * max(dt, 0.0))
    f = cfg.wheel_floor_sigmas
    return np.array([f[0] + cfg.wheel_k_d * np.sqrt(d), f[1] + d * s_th / 2.0, f[2] + s_th])


class LidarSLAM2D:
    def __init__(self, cfg: Optional[SLAMConfig] = None):
        self.cfg = cfg or SLAMConfig()
        params = gtsam.ISAM2Params()
        params.setRelinearizeThreshold(0.01)
        params.relinearizeSkip = 1
        self.isam = gtsam.ISAM2(params)

        self._pending_factors = gtsam.NonlinearFactorGraph()
        self._pending_values  = gtsam.Values()

        self.kf_scans:   List[np.ndarray]  = []
        self.kf_normals: List[np.ndarray]  = []
        self.kf_poses:   List[gtsam.Pose2] = []
        self.loop_closures: List[Tuple[int, int, float]] = []
        self.n_kf = 0
        self.current_pose = gtsam.Pose2(0, 0, 0)
        self.threshold = AdaptiveThreshold(self.cfg.icp_initial_sigma,
                                           self.cfg.lidar_max_range,
                                           self.cfg.icp_min_deviation)

        self._submap = None             # (points, tree, normals)
        self._submap_anchor: int = -1
        self._submap_rels: Optional[np.ndarray] = None
        self.submap_builds = 0
        self.submap_hits = 0

        self._prior_noise = gtsam.noiseModel.Diagonal.Sigmas(np.asarray(self.cfg.prior_sigmas))
        self.timings = {"isam": []}

    # ---- API used by orchestrator (under slam_lock) -----------------------
    def _store_scan(self, scan_ds: np.ndarray):
        self.kf_scans.append(scan_ds)
        self.kf_normals.append(estimate_normals(scan_ds, cKDTree(scan_ds)))

    def add_first_scan(self, scan: np.ndarray, pose: gtsam.Pose2):
        scan_ds = voxel_downsample(scan, self.cfg.voxel_size)
        self._pending_factors.add(gtsam.PriorFactorPose2(X(0), pose, self._prior_noise))
        self._pending_values.insert(X(0), pose)
        self._store_scan(scan_ds)
        self.kf_poses.append(pose)
        self.n_kf = 1
        self.current_pose = pose
        self._flush_isam()

    def match_keyframe(self, scan_ds: np.ndarray, odom_delta: gtsam.Pose2, submap,
                       dt: float) -> Optional[ICPResult]:
        """Scan-to-submap ICP from the odometry guess. Returns the ICP result if
        it passes the guards (and feeds it to the adaptive threshold), else None.
        Main-thread only; needs no lock (reads nothing the loop worker writes)."""
        pts, tree, normals = submap
        if len(pts) <= 10:
            return None
        sigma = self.threshold.sigma
        res = pl_icp_2d(scan_ds, pts, odom_delta, max_corr_dist=3.0 * sigma,
                        kernel=sigma / 3.0, target_tree=tree, target_normals=normals)
        # Guard: the correction must be plausible — within the fixed limits
        # or within icp_guard_nsigma σ of the wheel-odometry noise model.
        diff = odom_delta.between(res.pose)
        ws = self.cfg.icp_guard_nsigma * wheel_odometry_sigmas(odom_delta, dt, self.cfg)
        max_t = max(self.cfg.icp_max_trans_dev, np.hypot(ws[0], ws[1]))
        max_r = max(self.cfg.icp_max_rot_dev, ws[2])
        if (np.hypot(diff.x(), diff.y()) > max_t or abs(diff.theta()) > max_r
                or res.rmse > self.cfg.icp_max_rmse):
            return None
        self.threshold.update(odom_delta, res.pose)
        return res

    def add_keyframe(self, scan_ds: np.ndarray, odom_delta: gtsam.Pose2,
                     icp: Optional[ICPResult], dt: float) -> int:
        """Adds X(j) with a wheel-odometry factor and, if ICP was accepted, a
        scan-matching factor. `scan_ds` must already be voxel-downsampled."""
        j = self.n_kf
        wheel_noise = gtsam.noiseModel.Diagonal.Sigmas(
            wheel_odometry_sigmas(odom_delta, dt, self.cfg))
        self._pending_factors.add(gtsam.BetweenFactorPose2(
            X(j-1), X(j), odom_delta, wheel_noise))
        delta = odom_delta
        if icp is not None:
            cov = (self.cfg.icp_cov_scale * icp_covariance(icp)
                   + np.diag(np.square(self.cfg.icp_floor_sigmas)))
            self._pending_factors.add(gtsam.BetweenFactorPose2(
                X(j-1), X(j), icp.pose, gtsam.noiseModel.Gaussian.Covariance(cov)))
            delta = icp.pose
        new_pose = self.kf_poses[-1].compose(delta)
        self._pending_values.insert(X(j), new_pose)
        self._store_scan(scan_ds)
        self.kf_poses.append(new_pose)
        self.n_kf += 1
        self.current_pose = new_pose
        return j

    def get_submap(self, base_idx: int) -> Tuple[np.ndarray, cKDTree, np.ndarray]:
        """Last `submap_size` keyframe scans in keyframe `base_idx`'s frame:
        (points, KD-tree, per-point line normals)."""
        start = max(0, base_idx - self.cfg.submap_size + 1)
        base_pose = self.kf_poses[base_idx]
        rels = [base_pose.between(self.kf_poses[k]) for k in range(start, base_idx + 1)]
        rel_arr = np.array([[r.x(), r.y(), r.theta()] for r in rels])
        if (base_idx == self._submap_anchor and self._submap is not None
                and self._submap_rels is not None
                and self._submap_rels.shape == rel_arr.shape
                and np.max(np.abs(self._submap_rels - rel_arr)) < self.cfg.submap_cache_tol):
            self.submap_hits += 1
            return self._submap
        parts = []
        for k, rel in zip(range(start, base_idx + 1), rels):
            cc, ss = np.cos(rel.theta()), np.sin(rel.theta())
            R = np.array([[cc, -ss], [ss, cc]], dtype=np.float32)
            t = np.array([rel.x(), rel.y()], dtype=np.float32)
            parts.append(self.kf_scans[k] @ R.T + t)
        pts = voxel_downsample(np.vstack(parts), self.cfg.voxel_size)
        tree = cKDTree(pts)
        self._submap = (pts, tree, estimate_normals(pts, tree))
        self._submap_anchor = base_idx
        self._submap_rels = rel_arr
        self.submap_builds += 1
        return self._submap

    def inject_loop_factor(self, j: int, i: int, rel: gtsam.Pose2, rmse: float,
                           cov: np.ndarray):
        """Add X(j) → X(i) with measurement rel = X(j)⁻¹ ⊕ X(i). Noise: the loop
        ICP covariance + diag(loop_sigmas²), wrapped in a Cauchy kernel on the
        whitened residual so one wrong loop cannot drag the whole graph (cf.
        Dynamic Covariance Scaling, Agarwal et al., ICRA 2013)."""
        if j >= self.n_kf or i >= self.n_kf:
            return
        base = gtsam.noiseModel.Gaussian.Covariance(
            cov + np.diag(np.square(self.cfg.loop_sigmas)))
        noise = gtsam.noiseModel.Robust.Create(
            gtsam.noiseModel.mEstimator.Cauchy.Create(self.cfg.loop_cauchy_k), base)
        self._pending_factors.add(gtsam.BetweenFactorPose2(X(j), X(i), rel, noise))
        self.loop_closures.append((j, i, rmse))

    def flush(self, extra_iters: int = 0):
        self._flush_isam(extra_iters)

    def _flush_isam(self, extra_iters: int = 0):
        if self._pending_factors.size() == 0 and self._pending_values.size() == 0:
            return
        t0 = time.perf_counter()
        self.isam.update(self._pending_factors, self._pending_values)
        # A loop closure moves many poses at once; one iSAM2 step is a single
        # Gauss-Newton iteration, so relinearize a few more times.
        for _ in range(extra_iters):
            self.isam.update()
        self._pending_factors = gtsam.NonlinearFactorGraph()
        self._pending_values  = gtsam.Values()
        result = self.isam.calculateEstimate()
        for k in range(self.n_kf):
            self.kf_poses[k] = result.atPose2(X(k))
        self.current_pose = self.kf_poses[-1]
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
# Loop-closure search + validation (used by the worker thread)
# ---------------------------------------------------------------------------
def _wrap(a: float) -> float:
    return float(np.arctan2(np.sin(a), np.cos(a)))


class LoopMatch(NamedTuple):
    j: int                  # older keyframe
    i: int                  # query (newest) keyframe
    rel: gtsam.Pose2        # X(j)⁻¹ ⊕ X(i) measured by ICP
    rmse: float
    cov: np.ndarray         # ICP covariance of rel (GTSAM tangent)


def search_loop_closure(poses: np.ndarray, scans: List[np.ndarray],
                        normals: List[np.ndarray], i: int, cfg: SLAMConfig,
                        sigma: float) -> Tuple[Optional[LoopMatch], List[int]]:
    """Find a loop closure for keyframe i using the *current SLAM estimates*
    `poses` (n×3 snapshot) and the ICP threshold σ. Returns (best match or
    None, candidates tried)."""
    last = i - cfg.loop_min_kf_gap        # newest admissible old keyframe
    if last < 0:
        return None, []
    xy  = poses[:last + 1, :2]
    ths = poses[:last + 1, 2]
    cx, cy, cth = poses[i]
    cand = cKDTree(xy).query_ball_point([cx, cy], cfg.loop_search_radius)
    if not cand:
        return None, []
    cand.sort(key=lambda j: (cx - xy[j, 0])**2 + (cy - xy[j, 1])**2)
    cand = cand[: cfg.loop_max_candidates * 3]

    current = gtsam.Pose2(float(cx), float(cy), float(cth))
    best: Optional[LoopMatch] = None
    tried: List[int] = []
    for j in cand:
        if len(tried) >= cfg.loop_max_candidates:
            break
        if abs(_wrap(cth - float(ths[j]))) > cfg.loop_max_heading_diff:
            continue
        tried.append(j)
        old_pose = gtsam.Pose2(float(xy[j, 0]), float(xy[j, 1]), float(ths[j]))
        guess = old_pose.between(current)            # X(j)⁻¹ ⊕ X(i)
        res = pl_icp_2d(scans[i], scans[j], guess, max_corr_dist=3.0 * sigma,
                        kernel=sigma / 3.0, target_normals=normals[j])
        dev = guess.between(res.pose)
        if (res.degeneracy < cfg.loop_min_degeneracy        # cf. Zhang et al., ICRA 2016
                or np.hypot(dev.x(), dev.y()) > cfg.loop_max_trans_dev
                or abs(dev.theta()) > cfg.loop_max_rot_dev):
            continue
        if (res.rmse < cfg.loop_rmse_thresh
                and res.inlier_ratio > cfg.loop_inlier_thresh
                and res.n_inliers > cfg.loop_min_inliers
                and (best is None or res.rmse < best.rmse)):
            best = LoopMatch(j, i, res.pose, res.rmse, icp_covariance(res))
    return best, tried


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
        self._stop_evt = threading.Event()
        self.timings: List[float] = []
        self.last_loop_i = -10**9

    def stop(self): self._stop_evt.set()

    def run(self):
        while not self._stop_evt.is_set():
            try:
                i = self.in_q.get(timeout=0.2)
            except queue.Empty:
                continue
            # Rate limit: consecutive keyframes would close nearly the same
            # loop again, adding correlated factors that iSAM2 treats as
            # independent (overconfident).
            if i - self.last_loop_i < self.cfg.loop_cooldown_kf:
                continue
            t0 = time.perf_counter()

            # Snapshot the current estimates under the lock; scans are
            # append-only, so the lists can be read without the lock.
            with self.slam_lock:
                if i >= self.slam.n_kf:
                    continue
                poses = self.slam.trajectory()
                scans = list(self.slam.kf_scans[: i + 1])
                normals = list(self.slam.kf_normals[: i + 1])
                sigma = self.slam.threshold.sigma

            best, _ = search_loop_closure(poses, scans, normals, i, self.cfg, sigma)
            if best is not None:
                self.last_loop_i = i
                try: self.out_q.put_nowait(best)
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

        self._stop_evt = threading.Event()
        self._main_thread = threading.Thread(
            target=self._main_loop, daemon=True, name="SLAM")

        self.timings = {"frame": [], "kf": [], "icp": [], "undistort": []}

    def threads(self) -> List[threading.Thread]:
        return [self._main_thread, self.lidar_reader, self.odom_reader, self.loop_worker]

    def start(self):
        self.odom_reader.start()
        self.lidar_reader.start()
        self.loop_worker.start()
        self._main_thread.start()

    def stop(self) -> List[str]:
        """Stops all threads; returns the names of any that failed to join."""
        self._stop_evt.set()
        self.lidar_reader.stop()
        self.odom_reader.stop()
        self.loop_worker.stop()
        # nudge readers blocked on semaphores
        try: self.lidar_sem.release()
        except Exception: pass
        try: self.odom_sem.release()
        except Exception: pass
        for t in self.threads():
            t.join(timeout=2.0)
        alive = [t.name for t in self.threads() if t.is_alive()]
        self.lidar_shm.close()
        self.odom_shm.close()
        self.lidar_sem.close()
        self.odom_sem.close()
        return alive

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
        last_odom_pose: Optional[gtsam.Pose2] = None
        delta_since_kf = gtsam.Pose2(0, 0, 0)
        t_last_kf = 0.0

        while not self._stop_evt.is_set():
            try:
                seq, t_lidar, sweep, scan = self.lidar_q.get(timeout=0.2)
            except queue.Empty:
                continue
            t_frame = time.perf_counter()

            # Odometry (wheel + gyro) pose at the end of the sweep
            odom_xyt = self.odom_reader.pose_at(t_lidar)
            if odom_xyt is None:
                continue
            odom_pose = gtsam.Pose2(*odom_xyt)

            # Scan motion-compensation: every beam → end-of-sweep frame
            if self.cfg.enable_undistort:
                t_un = time.perf_counter()
                with self.odom_reader.lock:
                    buf = np.asarray(self.odom_reader.buffer, dtype=np.float64)
                scan = undistort_scan(scan, t_lidar - sweep, sweep, odom_xyt, buf, self.cfg)
                self.timings["undistort"].append((time.perf_counter() - t_un) * 1e3)

            if last_odom_pose is None:
                with self.slam_lock:
                    self.slam.add_first_scan(scan, odom_pose)
                last_odom_pose = odom_pose
                t_last_kf = t_lidar
                continue

            odom_delta = last_odom_pose.between(odom_pose)
            delta_since_kf = delta_since_kf.compose(odom_delta)

            # Inject loop closures discovered by the worker
            self._drain_loop_results()

            # Spawn a keyframe?
            d = delta_since_kf
            if (np.hypot(d.x(), d.y()) > self.cfg.kf_trans
                    or abs(d.theta()) > self.cfg.kf_rot):
                self._handle_keyframe(scan, delta_since_kf, t_lidar - t_last_kf)
                delta_since_kf = gtsam.Pose2(0, 0, 0)
                t_last_kf = t_lidar

            last_odom_pose = odom_pose
            self.timings["frame"].append((time.perf_counter() - t_frame) * 1e3)

    def _handle_keyframe(self, scan: np.ndarray, odom_delta: gtsam.Pose2, dt: float):
        t0 = time.perf_counter()
        scan_ds = voxel_downsample(scan, self.cfg.voxel_size)

        with self.slam_lock:
            submap = self.slam.get_submap(self.slam.n_kf - 1)

        t_icp = time.perf_counter()
        icp = self.slam.match_keyframe(scan_ds, odom_delta, submap, dt)   # None = rejected
        self.timings["icp"].append((time.perf_counter() - t_icp) * 1e3)

        with self.slam_lock:
            j_new = self.slam.add_keyframe(scan_ds, odom_delta, icp, dt)
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
                m: LoopMatch = self.loop_out_q.get_nowait()
            except queue.Empty:
                break
            with self.slam_lock:
                self.slam.inject_loop_factor(m.j, m.i, m.rel, m.rmse, m.cov)
                injected = True
        if injected:
            with self.slam_lock:
                self.slam.flush(self.cfg.isam_extra_iters_after_loop)


def undistort_scan(pts: np.ndarray, t_start: float, sweep: float,
                   ref_xyth: Tuple[float, float, float], odom_buf: np.ndarray,
                   cfg: SLAMConfig) -> np.ndarray:
    """Re-express every point in the end-of-sweep frame `ref_xyth`.
    `odom_buf` is an (n, 4) array of (t, x, y, θ) odometry samples."""
    n = len(pts)
    if n == 0 or len(odom_buf) < 2:
        return pts
    # Beam time from its bearing: points are in the sensor frame at the
    # instant their beam fired, so atan2 recovers the beam angle (even when
    # invalid beams were dropped from the array).
    a0, a1 = cfg.lidar_angle_min, cfg.lidar_angle_max
    ang = np.arctan2(pts[:, 1].astype(np.float64), pts[:, 0].astype(np.float64))
    frac = np.clip(np.mod(ang - a0, 2 * np.pi) / (a1 - a0), 0.0, 1.0)
    ts = t_start + frac * sweep
    bts, bxs, bys, bths = odom_buf[:, 0], odom_buf[:, 1], odom_buf[:, 2], odom_buf[:, 3]

    idx = np.searchsorted(bts, ts, side='right') - 1
    idx = np.clip(idx, 0, len(bts) - 2)
    t0 = bts[idx]; t1 = bts[idx + 1]
    u  = np.clip((ts - t0) / np.maximum(t1 - t0, 1e-9), 0.0, 1.0)
    x_i, y_i, th_i = se2_interp(bxs[idx], bys[idx], bths[idx],
                                bxs[idx + 1], bys[idx + 1], bths[idx + 1], u)

    # T_ref⁻¹ ⊕ T_beam ⊕ p
    rx, ry, rth = ref_xyth
    dxw = x_i - rx; dyw = y_i - ry
    cc, ss = np.cos(-rth), np.sin(-rth)
    dx = cc * dxw - ss * dyw
    dy = ss * dxw + cc * dyw
    dth = th_i - rth
    cc2 = np.cos(dth); ss2 = np.sin(dth)

    px = pts[:, 0].astype(np.float64); py = pts[:, 1].astype(np.float64)
    out = np.empty_like(pts)
    out[:, 0] = dx + cc2 * px - ss2 * py
    out[:, 1] = dy + ss2 * px + cc2 * py
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


def _simulate_scan(pose, walls, n_beams=N_BEAMS, fov=LIDAR_FOV,
                   max_range=10.0, noise_std=0.015, beam_poses=None):
    """Simulated sweep. Beams fire in angle order from -fov/2 to +fov/2.
    If `beam_poses` (n_beams×3) is given, beam k is cast from its own pose
    and reported in that instantaneous sensor frame — i.e. with the motion
    distortion a real spinning LiDAR produces. Otherwise all beams use `pose`."""
    angles = np.linspace(-fov / 2, fov / 2, n_beams)
    pts = np.empty((n_beams, 2), dtype=np.float32)
    valid = 0
    for k, a in enumerate(angles):
        x, y, th = pose if beam_poses is None else beam_poses[k]
        r = _raycast(np.array([x, y]), th + a, walls, max_range)
        if r < max_range - 1e-3:
            r += np.random.randn() * noise_std
            pts[valid, 0] = r * np.cos(a)
            pts[valid, 1] = r * np.sin(a)
            valid += 1
    return pts[:valid]


def _sweep_beam_poses(traj, i_end: int, samples_per_sweep: int,
                      n_beams: int = N_BEAMS) -> np.ndarray:
    """Ground-truth pose of every beam of the sweep that ends at traj[i_end],
    SE(2)-interpolated between the 50 Hz trajectory samples."""
    f = i_end - samples_per_sweep + samples_per_sweep * np.linspace(0.0, 1.0, n_beams)
    f = np.clip(f, 0.0, len(traj) - 1)
    lo = np.minimum(np.floor(f).astype(int), len(traj) - 2)
    u = f - lo
    arr = np.asarray(traj, dtype=np.float64)
    a, b = arr[lo], arr[lo + 1]
    x, y, th = se2_interp(a[:, 0], a[:, 1], a[:, 2], b[:, 0], b[:, 1], b[:, 2], u)
    return np.stack([x, y, th], axis=1)


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
    requested rates. A `sim_speed` of 1 means real time. Odom sample i and
    the sweep ending at trajectory sample i share one clock, t0 + i·dt."""
    def __init__(self,
                 lidar_shm: ShmRegion, lidar_sem: NamedSemaphore,
                 odom_shm:  ShmRegion, odom_sem:  NamedSemaphore,
                 trajectory_50hz, walls,
                 sim_speed: float = 1.0,
                 odom_k_d: float = 0.05,   # encoder distance noise: σ_d = k_d·√d      (m/√m)
                 odom_k_th: float = 0.02,  # heading random walk:   σ_θ = k_θ·√|dθ|  (rad/√rad)
                 gyro_arw: float = 0.005,  # gyro angle random walk: σ = ARW·√dt     (rad/√s)
                 max_samples: Optional[int] = None):
        self.lidar_shm = lidar_shm; self.lidar_sem = lidar_sem
        self.odom_shm  = odom_shm;  self.odom_sem  = odom_sem
        self.traj = trajectory_50hz if max_samples is None else trajectory_50hz[:max_samples]
        self.walls = walls
        self.sim_speed = sim_speed
        self.odom_dt  = 0.020 / sim_speed
        self.samples_per_sweep = 5                       # 50 Hz / 5 = 10 Hz
        self.lidar_dt = self.samples_per_sweep * self.odom_dt
        self.lidar_sweep = self.lidar_dt                 # continuously spinning

        # Noise parameters
        self.odom_k_d = odom_k_d
        self.odom_k_th = odom_k_th
        self.gyro_arw = gyro_arw

        self._stop_evt = threading.Event()
        self._done = threading.Event()
        self.odom_seq = 0
        self.lidar_seq = 0

        self.noisy_pose = np.zeros(3, dtype=float)
        self.odom_history = []
        self.rng = np.random.default_rng(0)
        self._t0_wall = 0.0
        self._t0_mono = 0.0
        self._odom_t  = threading.Thread(target=self._odom_loop,  daemon=True, name="ProdOdom")
        self._lidar_t = threading.Thread(target=self._lidar_loop, daemon=True, name="ProdLidar")

    def start(self):
        self._t0_wall = time.time()
        self._t0_mono = time.monotonic()
        self._odom_t.start()
        self._lidar_t.start()

    def stop(self):
        self._stop_evt.set()
        for t in (self._odom_t, self._lidar_t):
            if t.is_alive():
                t.join(timeout=2.0)

    def is_done(self) -> bool:
        return self._done.is_set()

    def _sleep_until(self, i: int):
        target = self._t0_mono + i * self.odom_dt
        now = time.monotonic()
        if now < target:
            time.sleep(target - now)

    def _stamp(self, i: int) -> float:
        return self._t0_wall + i * self.odom_dt

    def _odom_loop(self):
        i = 0
        n = len(self.traj)

        while not self._stop_evt.is_set() and i < n:
            self._sleep_until(i)
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

                # 1. Encoder distance: variance grows with distance travelled
                var_d = (self.odom_k_d ** 2) * true_d
                noisy_d = true_d + self.rng.normal(0.0, np.sqrt(var_d))

                # 2. Heading: random-walk noise ∝ √|dθ| turned, plus gyro ARW
                # per dt. dt is the virtual 20 ms step (odom_dt · sim_speed),
                # so the variance accumulates the same at any sim speed.
                var_th = (self.odom_k_th ** 2) * abs(true_dth) + (self.gyro_arw ** 2) * (self.odom_dt * self.sim_speed)
                noisy_dth = true_dth + self.rng.normal(0.0, np.sqrt(var_th))

                # 3. Mid-point (RK2) integration
                mid_th = self.noisy_pose[2] + noisy_dth / 2.0

                self.noisy_pose[0] += noisy_d * np.cos(mid_th)
                self.noisy_pose[1] += noisy_d * np.sin(mid_th)
                self.noisy_pose[2] = (self.noisy_pose[2] + noisy_dth + np.pi) % (2 * np.pi) - np.pi

                noisy_x, noisy_y, noisy_th = self.noisy_pose

            self.odom_history.append((noisy_x, noisy_y, noisy_th))

            stamp = self._stamp(i)
            def payload(v, stamp=stamp, x=noisy_x, y=noisy_y, th=noisy_th):
                v['timestamp'][0] = stamp
                v['x'][0] = x
                v['y'][0] = y
                v['theta'][0] = th
            self.odom_seq = seqlock_write(self.odom_shm.array, payload)
            self.odom_sem.release()
            i += 1

        self._done.set()

    def _lidar_loop(self):
        i = self.samples_per_sweep          # first sweep ends at sample 5
        n = len(self.traj)
        while not self._stop_evt.is_set() and i < n:
            self._sleep_until(i)
            # Each beam is cast from the ground-truth pose at its own firing
            # time, so the scan carries real motion distortion.
            beam_poses = _sweep_beam_poses(self.traj, i, self.samples_per_sweep)
            scan = _simulate_scan(self.traj[i], self.walls, beam_poses=beam_poses)
            k = len(scan)
            stamp = self._stamp(i)
            def payload(v, stamp=stamp, scan=scan, k=k):
                v['timestamp'][0]      = stamp
                v['sweep_duration'][0] = self.lidar_sweep
                v['n_points'][0]       = k
                v['capacity'][0]       = N_BEAMS
                v['points'][0, :k]     = scan
            self.lidar_seq = seqlock_write(self.lidar_shm.array, payload)
            self.lidar_sem.release()
            i += self.samples_per_sweep
        # (odom loop sets _done)


class _DemoIPC:
    """Creates (and later removes) the producer-side shm regions + semaphores."""
    def __init__(self):
        pid = os.getpid()
        self.lidar_shm_name = f"/lslam_lidar_{pid}"
        self.odom_shm_name  = f"/lslam_odom_{pid}"
        self.lidar_sem_name = f"/lslam_lsem_{pid}"
        self.odom_sem_name  = f"/lslam_osem_{pid}"
        self.lidar_shm = ShmRegion(self.lidar_shm_name, LIDAR_DTYPE, create=True)
        self.odom_shm  = ShmRegion(self.odom_shm_name,  ODOM_DTYPE,  create=True)
        self.lidar_sem = NamedSemaphore(self.lidar_sem_name, create=True, initial=0)
        self.odom_sem  = NamedSemaphore(self.odom_sem_name,  create=True, initial=0)

    def consumer(self, cfg: Optional[SLAMConfig] = None) -> RealtimeLidarSLAM:
        return RealtimeLidarSLAM(
            lidar_shm_name=self.lidar_shm_name, lidar_sem_name=self.lidar_sem_name,
            odom_shm_name=self.odom_shm_name,  odom_sem_name=self.odom_sem_name,
            cfg=cfg)

    def cleanup(self):
        for r in (self.lidar_shm, self.odom_shm):
            r.close(); r.unlink()
        for s in (self.lidar_sem, self.odom_sem):
            s.close(); s.unlink()


def run_smoke_test(sim_speed: float = 8.0, samples: int = 1500) -> bool:
    """Short headless run: start producer + consumer, stop, check every
    thread joined and data flowed. Returns True on success."""
    ipc = _DemoIPC()
    slam = prod = None
    ok = False
    try:
        np.random.seed(0)
        traj = _make_diff_drive_trajectory(hz=50, side=8.0, laps=2)
        prod = ProducerSim(ipc.lidar_shm, ipc.lidar_sem, ipc.odom_shm, ipc.odom_sem,
                           traj, _build_world(), sim_speed=sim_speed, max_samples=samples)
        slam = ipc.consumer()
        slam.start(); prod.start()
        while not prod.is_done():
            time.sleep(0.05)
        time.sleep(0.5)
        prod.stop()
        alive = slam.stop()
        n_kf = slam.slam.n_kf
        print(f"smoke: odom={slam.odom_reader.received} lidar={slam.lidar_reader.received} "
              f"kf={n_kf} threads-still-alive={alive}")
        ok = (not alive and slam.odom_reader.received > 0
              and slam.lidar_reader.received > 0 and n_kf > 1)
        slam = None
    finally:
        if prod is not None: prod.stop()
        if slam is not None: slam.stop()
        ipc.cleanup()
    print("smoke test", "PASSED" if ok else "FAILED")
    return ok


def run_demo():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ipc = _DemoIPC()
    slam = None
    prod = None
    try:
        np.random.seed(0)
        walls = _build_world()
        traj = _make_diff_drive_trajectory(hz=50, side=8.0, laps=2)

        # sim_speed=1.0 means real-time. Larger values stress-test the pipeline.
        SIM_SPEED = 4.0

        prod = ProducerSim(ipc.lidar_shm, ipc.lidar_sem, ipc.odom_shm, ipc.odom_sem,
                           traj, walls, sim_speed=SIM_SPEED,
                           odom_k_d=0.15, odom_k_th=0.1, gyro_arw=0.005)

        slam = ipc.consumer()
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
            if slam is not None:
                alive = slam.stop()
                if alive:
                    print(f"warning: threads did not stop: {alive}")
        except Exception: pass
        ipc.cleanup()


if __name__ == "__main__":
    if "--smoke" in sys.argv[1:]:
        sys.exit(0 if run_smoke_test() else 1)
    run_demo()
