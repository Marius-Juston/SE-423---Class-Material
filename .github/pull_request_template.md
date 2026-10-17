<!-- What changed and why. Reference the affected material (e.g. "Lecture 5, slide 12"). -->

### Accessibility checklist

- [ ] New pictures have alt text: `\AltImg` / `\AltStart` in LaTeX, Alt Text in PowerPoint (or marked decorative), a `% alt:` line in new TikZ figures
- [ ] New slides have a real title (the layout's title placeholder)
- [ ] Meaning is never carried by colour alone; plots use `course_style.apply()`
- [ ] LaTeX follows the conventions in CONTRIBUTING.md (`[H]` figures, `\caption`, `minted`, palette colours)
- [ ] `uv run tools/a11y/run_all.py` reports no new problems (the pre-commit hook does this; `sh tools/install-hooks.sh`)
- [ ] If this fixed problems: `uv run tools/a11y/run_all.py --update-baseline` and the updated `a11y-baseline.json` is committed
