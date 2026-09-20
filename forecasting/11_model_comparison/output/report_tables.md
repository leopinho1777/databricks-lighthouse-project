### SKU x location portfolio WAPE (%), main table
| Model | 2024-12-31 (peak) | 2025-04-01 | 2025-07-01 | 2025-09-30 (peak) | Mean | Peak | Off-peak | Wins vs champion |
|---|---|---|---|---|---|---|---|---|
| seasonal_naive (champion) | 78.8 | 84.4 | 88.1 | 79.9 | 82.8 | 79.3 | 86.0 | - |
| Panel regression (uncorrected) | 87.1 | 100.5 | 107.0 | 89.0 | 95.9 | 88.0 | 103.3 | 0/4 |
| Prophet changepoint rigid | 87.4 | 102.2 | 104.7 | 89.5 | 96.0 | 88.4 | 103.4 | 0/4 |
| XGBoost v1 | 77.1 | 104.8 | 124.6 | 81.5 | 97.0 | 79.2 | 113.3 | 1/4 |
| RF depth10 | 88.0 | 107.0 | 104.0 | 89.7 | 97.2 | 88.8 | 105.6 | 0/4 |
| SARIMA d=0 + trend | 93.4 | 105.1 | 109.3 | 92.6 | 100.1 | 93.0 | 107.0 | 0/4 |
| Panel regression + Duan smearing | 78.1 | 109.5 | 131.7 | 81.3 | 100.1 | 79.6 | 119.0 | 1/4 |

### Bias and per-series error, main table (bias = actual - forecast, positive = under-forecast)
| Model | Mean portfolio bias (% of actual) | Per-series RMSE mean | Per-series RMSE median | Per-series bias mean |
|---|---|---|---|---|
| seasonal_naive (champion) | 49.4 | n/a | n/a | n/a |
| Panel regression (uncorrected) | 66.8 | 6.38 | 5.79 | 3.63 |
| Prophet changepoint rigid | 68.4 | 6.43 | 5.87 | 3.67 |
| XGBoost v1 | 20.2 | 5.69 | 4.92 | 1.24 |
| RF depth10 | 61.3 | 6.39 | 5.84 | 3.45 |
| SARIMA d=0 + trend | 67.0 | 6.80 | 6.29 | 3.67 |
| Panel regression + Duan smearing | 12.6 | 5.74 | 4.79 | 1.16 |

### Category x location portfolio WAPE (%), same predictions summed up
| Model | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Mean |
|---|---|---|---|---|---|
| Panel regression (uncorrected) | 71.4 | 64.0 | 60.9 | 70.9 | 66.8 |
| Prophet changepoint rigid | 70.5 | 65.1 | 66.1 | 72.0 | 68.4 |
| XGBoost v1 | 24.2 | 27.6 | 15.5 | 31.2 | 24.6 |
| RF depth10 | 73.1 | 29.1 | 69.3 | 73.9 | 61.4 |
| SARIMA d=0 + trend | 78.8 | 63.2 | 58.1 | 67.9 | 67.0 |
| Panel regression + Duan smearing | 39.1 | 11.4 | 26.2 | 33.9 | 27.7 |

### Appendix: every committed configuration (SKU x location WAPE %)
| Model | Target | Windows | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Mean | Wins | Bias % | RMSE mean |
|---|---|---|---|---|---|---|---|---|---|---|
| Panel regression (uncorrected) | log1p | exact | 87.1 | 100.5 | 107.0 | 89.0 | 95.9 | 0/4 | 66.8 | 6.38 |
| Panel regression + Duan smearing | log1p | exact | 78.1 | 109.5 | 131.7 | 81.3 | 100.1 | 1/4 | 12.6 | 5.74 |
| Prophet changepoint rigid | log1p | weekly-straddle | 87.4 | 102.2 | 104.7 | 89.5 | 96.0 | 0/4 | 68.4 | 6.43 |
| Prophet no holidays | log1p | weekly-straddle | 87.0 | 102.6 | 106.1 | 88.6 | 96.1 | 0/4 | 64.5 | 6.37 |
| Prophet default | log1p | weekly-straddle | 87.0 | 102.8 | 106.3 | 88.8 | 96.2 | 0/4 | 64.0 | 6.37 |
| Prophet changepoint flexible | log1p | weekly-straddle | 87.2 | 105.6 | 108.2 | 88.8 | 97.4 | 0/4 | 58.6 | 6.40 |
| Prophet multiplicative seasonality | log1p | weekly-straddle | 93.1 | 105.6 | 111.1 | 91.7 | 100.4 | 0/4 | 53.6 | 6.66 |
| RF depth10 | log1p | weekly-straddle | 88.0 | 107.0 | 104.0 | 89.7 | 97.2 | 0/4 | 61.3 | 6.39 |
| RF leaf20 | log1p | weekly-straddle | 87.0 | 108.6 | 104.3 | 91.1 | 97.7 | 0/4 | 60.2 | 6.43 |
| RF sqrtfeatures | log1p | weekly-straddle | 91.0 | 116.2 | 108.6 | 92.2 | 102.0 | 0/4 | 56.5 | 6.74 |
| RF depth20 | log1p | weekly-straddle | 87.3 | 125.4 | 105.9 | 91.5 | 102.5 | 0/4 | 55.7 | 6.68 |
| RF unbounded | log1p | weekly-straddle | 99.4 | 165.2 | 110.5 | 97.7 | 118.2 | 0/4 | 42.7 | 7.81 |
| SARIMA d=0 + trend | log1p | weekly-straddle | 93.4 | 105.1 | 109.3 | 92.6 | 100.1 | 0/4 | 67.0 | 6.80 |
| SARIMA d=1 | log1p | weekly-straddle | 94.0 | 110.6 | 115.0 | 96.8 | 104.1 | 0/4 | 58.9 | 7.01 |
| XGBoost v1 | raw counts | exact | 77.1 | 104.8 | 124.6 | 81.5 | 97.0 | 1/4 | 20.2 | 5.69 |

### Data behaviour per window
| Window (cutoff) | Peak? | Actual units | Units / series | Series with zero sales (%) | Poisson-expected zeros (%) | Poisson noise-floor WAPE (%) |
|---|---|---|---|---|---|---|
| 2024-12-31 | yes | 46,163 | 7.63 | 24.9 | 4.9 | 27.4 |
| 2025-04-01 | no | 23,216 | 3.83 | 49.5 | 10.6 | 38.7 |
| 2025-07-01 | no | 17,354 | 2.87 | 58.8 | 15.1 | 44.7 |
| 2025-09-30 | yes | 41,435 | 6.84 | 29.0 | 5.4 | 29.0 |

### Forecast units placed on series that sold nothing in the window
| Model | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 |
|---|---|---|---|---|
| Panel regression (uncorrected) | 3,287 | 4,133 | 3,960 | 3,485 |
| Prophet changepoint rigid | 3,389 | 3,956 | 3,562 | 3,345 |
| XGBoost v1 | 8,684 | 8,391 | 10,335 | 8,264 |
| RF depth10 | 3,077 | 7,989 | 3,220 | 3,108 |
| SARIMA d=0 + trend | 2,446 | 4,133 | 4,443 | 3,845 |
| Panel regression + Duan smearing | 7,003 | 11,460 | 12,526 | 7,929 |

### Sensitivity: WAPE (%) if models are scored on series with actual > 0 only (the baseline's convention)
| Model | 2024-12-31 | 2025-04-01 | 2025-07-01 | 2025-09-30 | Champion (committed) |
|---|---|---|---|---|---|
| Panel regression (uncorrected) | 80.0 | 82.7 | 84.2 | 80.6 |  |
| Prophet changepoint rigid | 80.0 | 84.2 | 85.7 | 81.5 |  |
| XGBoost v1 | 58.3 | 68.7 | 65.0 | 61.5 |  |
| RF depth10 | 81.2 | 70.6 | 86.7 | 82.3 |  |
| SARIMA d=0 + trend | 88.0 | 86.3 | 85.5 | 83.5 |  |
| Panel regression + Duan smearing | 62.9 | 60.1 | 59.5 | 62.1 |  |
| seasonal_naive (champion) | 78.8 | 84.4 | 88.1 | 79.9 | as committed |
