# NVIDIA Kumo Tabular: Download and Setup (Chaos Point)

Checked against `structured-data-models` **0.3.0**, from the package source.

## What gets downloaded

- **The Python library.** `structured-data-models` from PyPI (`import sdm`). Code licence Apache-2.0.
- **The weights.** Hugging Face repo **`nvidia/Kumo-Tabular`**, revision **`v1.0.1`**. Weights licence OpenMDW-1.1.
  - Files: `config.json` and `{small,medium,large}/classifier.pt` and `{small,medium,large}/regressor.pt`.
  - The library downloads them on first use through `huggingface_hub`.
  - Kumo Tabular has **no interactive licence prompt** and is not gated, so no token is needed. Some other models in the same library do prompt, which would hang a Celery worker.

Chaos Point needs `small/classifier.pt` to start. Add `regressor.pt` for the slow-stop durations (quantiles), and `medium` or `large` later if the VM handles them.

## Option A: on your Windows PC (to experiment)

Needs Python 3.11 or newer and PyTorch 2.7 or newer.

```powershell
python -m venv .venv-kumo
.venv-kumo\Scripts\activate
pip install torch                       # CPU build is fine; for an NVIDIA GPU use the CUDA index from pytorch.org
pip install structured-data-models scikit-learn pandas pyarrow "huggingface_hub[cli]"

# Pre-download the weights into the Hugging Face cache (one time)
hf download nvidia/Kumo-Tabular --revision v1.0.1 --include "config.json" "small/*"
# older huggingface_hub: huggingface-cli download nvidia/Kumo-Tabular --revision v1.0.1 --include "config.json" "small/*"
```

## Option B: inside Docker (the `worker-ml` service)

The weights live on the `ml_models` volume. `Dockerfile.ml` sets `HF_HOME=/models/hf`, so download once into that volume, then run the worker offline:

```bash
make build-ml
docker compose --profile ml run --rm worker-ml \
  hf download nvidia/Kumo-Tabular --revision v1.0.1 --include "config.json" "small/*" "medium/*"
# Afterwards set HF_HUB_OFFLINE=1 on worker-ml so it never reaches out to the Hub at task time.
```

On the Oracle VM (aarch64), PyPI's default `torch` wheel is CPU-only, so it works as-is.

## Smoke test (run this first on the VM and record the timing)

```python
import time, torch
from sklearn.datasets import make_classification
from sklearn.metrics import roc_auc_score
from sdm.models import KumoTabular

X, y = make_classification(n_samples=3000, n_features=30, weights=[0.85], random_state=0)
X = torch.tensor(X, dtype=torch.float32)
y = torch.tensor(y, dtype=torch.long).unsqueeze(-1)          # shape [R, 1]

t = time.time()
model = KumoTabular(task="classification", size="small", device="cpu").eval()
print("load", round(time.time() - t, 1), "s")

t = time.time()
model.fit(X[:2500], y[:2500], num_estimators=4)              # in-context: caches the labelled rows, no training
out = model.predict(X[2500:])                                # class probabilities (TableTensor)
print("predict 500 rows", round(time.time() - t, 1), "s")
model.clear()
```

Before wiring it into the pipeline:
- **Output format.** Print `type(out)` and its shape, to see how the class-1 probability is laid out (the output follows the model's default recipe).
- **The API.** `fit(x, y, num_estimators=…)`, then `.eval()`, then `predict(x)`, then `clear()`. There is no `predict_proba`. Plan 01 has been updated to match.

## Fit for Chaos Point

- **Features must be numeric.** Encode categoricals (circuit type, team, compound) before passing them in.
- **Missing values are handled natively.**
- **Stay within the pretraining scope** (up to 60,000 rows and 100 columns). Use driver-race rows (about 4,000) and 5-lap windows. Never use raw laps.
- **Uncertainty bands.** Regression returns 999 quantiles (`q001` to `q999`), which gives the p10 and p90 directly.
- **Multi-table later.** `sdm.models.KumoRelational` in the same package takes linked tables (races, drivers, circuits) without flattening. Try it after the tabular version works.
