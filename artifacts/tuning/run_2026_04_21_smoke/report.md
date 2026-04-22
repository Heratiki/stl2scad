# Detector Auto-Tuning Report

- Trials: 8
- Seed: 42
- Train: 20 fixtures — Holdout: 6 fixtures

## Aggregate scores

| Split | Baseline | Tuned | Delta |
|---|---|---|---|
| Train | 0.9966 | 0.9932 | -0.0033 |
| Holdout | 1.0000 | 1.0000 | +0.0000 |

## Overfit indicator

- Train gain: -0.0033
- Holdout gain: +0.0000
- Overfit gap (train gain − holdout gain): -0.0033

A gap close to 0 means the tuned config generalises. A gap ≥ train gain
means the gain was entirely fixture-specific.
