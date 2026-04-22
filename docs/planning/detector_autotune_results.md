# Detector Auto-Tuning: Experiment Results

## Question
Can the detector's hardcoded thresholds be automatically tuned — without AI or
human intervention — to improve feature-recognition accuracy, and does the
improvement generalise beyond the fixtures used to tune it?

## Method
- 25 detector thresholds exposed via `DetectorConfig`.
- Continuous per-fixture score (count F1 + dimension agreement, 0.6/0.4 weighted).
- Optuna TPE sampler, 300 trials, stratified 75/25 train/holdout split.
- Leave-one-out cross-validation, 10 trials per fold, for overfit measurement.

## Results — single split
- Baseline train: 0.9966, Tuned train: 0.9966, Delta: +0.0000
- Baseline holdout: 1.0000, Tuned holdout: 1.0000, Delta: +0.0000
- Overfit gap: +0.0000

## Results — leave-one-out
- Mean holdout score: 0.9948 (baseline: 0.9966)
- Std dev across folds: 0.0184
- Parameters with stable winners across folds: None (all parameter spans covered a large portion of their search space).
- Parameters with unstable winners: All 25 thresholds swung wildly across folds.

## Interpretation
- Saturated: tuning does not help; the bottleneck is algorithmic, not
  parametric. The original, hard-coded baseline defaults already perfectly capture
  the features in the 26-fixture manifest. When forced to search, Optuna just found 
  randomized configurations that happen to also score ~0.99, rather than finding 
  a meaningful generalized improvement.

## What this does NOT tell us
- Performance on real-world STLs outside the fixture corpus. The manifest is
  small and curated; success here does not prove field accuracy.
- Whether any of the unchanged 5+ thresholds matter. Expanding the search
  space is a cheap follow-up if the current results are promising.
- Anything about detector logic gaps. If a fixture requires a feature the
  detector cannot represent (e.g. a non-axis-aligned hole), no threshold
  tuning will help.
