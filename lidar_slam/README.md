# LiDAR SLAM walkthrough

Interactive walkthrough of `lidar_slam_2d.py` (threads, shared-memory IPC,
PL-ICP, iSAM2, loop closure), served as `lidar_slam/slam.html` on the course
site.

- `src/*.jsx` — React components (compiled by `build.sh`; `dist/` is not committed)
- `lidar_slam_2d.py` — the SLAM code shown in the code panel. Line ranges in
  `src/data.jsx` (`STAGES[].lines` / `focus`) point into this file, so update
  them whenever the file changes.
- `data/index.json`, `data/level_XX.json` — per-noise-level SLAM replay
  produced by `generate_cache.py` (in the `se423animations` repo,
  `src/slam/`). Regenerate with
  `uv run python src/slam/generate_cache.py --out <this folder>/data`.

## Local preview

Node.js (for `npx`) and Python 3 are required.

```bash
cd site/lidar_slam
./build.sh .                 # src/*.jsx -> dist/*.js
cd ..
python3 -m http.server       # then open http://localhost:8000/lidar_slam/slam.html
```

The page fetches `lidar_slam_2d.py` and `data/*.json`, so it must be served
over HTTP; opening the file directly will show a load error.

CI (`.github/workflows/build-latex.yml`) runs the same `build.sh` before
deploying, so only the sources need to be committed.
