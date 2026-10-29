"""Random Forest fraud model: synthetic training data, training, persistence and inference.

There is no labelled real-world data in a student project, so the model is trained on a
synthetic population whose fraud patterns (account takeover, mule accounts, balance draining,
odd-hour bursts) are documented below. The same generator powers the Fraud Lab evaluation.

    python -m app.ml.model            # (re)train and save the model
"""
from __future__ import annotations

import math
import threading
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score

MODEL_VERSION = "rf-v1.0.0"
ARTIFACT = Path(__file__).parent / "artifacts" / f"{MODEL_VERSION}.joblib"

# Order matters: this is the column order of the model's input matrix.
FEATURES = [
    "amount",
    "amount_to_avg_ratio",
    "hour_of_day",
    "is_new_payee",
    "sender_account_age_days",
    "transfers_last_hour",
    "balance_drain_ratio",
    "dest_distinct_senders_24h",
]

_lock = threading.Lock()
_model: RandomForestClassifier | None = None


def vectorize(features: dict) -> list[float]:
    """Turn a feature snapshot into the model's numeric row (amount on a log scale)."""
    row = []
    for name in FEATURES:
        value = float(features[name])
        if name == "amount":
            value = math.log1p(value)
        row.append(value)
    return row


def generate_synthetic(n: int, fraud_rate: float = 0.08, seed: int | None = 42) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic transfers. Legitimate traffic is daytime, small, to known payees; fraud is the opposite."""
    rng = np.random.default_rng(seed)
    n_fraud = max(1, int(round(n * fraud_rate)))
    n_legit = n - n_fraud

    def population(size: int, fraud: bool) -> np.ndarray:
        if fraud:
            amount = np.clip(rng.lognormal(math.log(40000), 1.0, size), 500, 2_000_000)
            ratio = rng.lognormal(math.log(6), 0.7, size)
            hour = np.where(rng.random(size) < 0.4, rng.integers(0, 5, size), rng.integers(0, 24, size))
            new_payee = (rng.random(size) < 0.85).astype(float)
            age = np.where(rng.random(size) < 0.5, rng.uniform(0, 30, size), rng.uniform(30, 2000, size))
            velocity = rng.poisson(2.5, size) + 1
            drain = rng.beta(8, 2, size)
            fan_in = rng.poisson(3, size)
        else:
            amount = np.clip(rng.lognormal(math.log(3000), 1.1, size), 10, 1_000_000)
            ratio = rng.lognormal(0, 0.5, size)
            hour = np.where(rng.random(size) < 0.92, rng.integers(7, 24, size), rng.integers(0, 7, size))
            new_payee = (rng.random(size) < 0.25).astype(float)
            age = rng.uniform(5, 2500, size)
            velocity = rng.poisson(0.4, size) + 1
            drain = rng.beta(2, 8, size)
            fan_in = rng.poisson(0.6, size)
        return np.column_stack([np.log1p(amount), ratio, hour, new_payee, age, velocity, drain, fan_in])

    X = np.vstack([population(n_legit, False), population(n_fraud, True)])
    y = np.concatenate([np.zeros(n_legit, dtype=int), np.ones(n_fraud, dtype=int)])
    # 3% label noise: real labels are never perfect.
    flip = rng.random(n) < 0.03
    y = np.where(flip, 1 - y, y)
    order = rng.permutation(n)
    return X[order], y[order]


def train(n: int = 20000, seed: int = 42) -> RandomForestClassifier:
    X, y = generate_synthetic(n, seed=seed)
    model = RandomForestClassifier(
        n_estimators=150, max_depth=8, min_samples_leaf=5, class_weight="balanced", random_state=seed, n_jobs=1
    )
    model.fit(X, y)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACT)
    return model


def get_model() -> RandomForestClassifier:
    """Load the saved model, training it once on first use if the artifact is missing."""
    global _model
    with _lock:
        if _model is None:
            _model = joblib.load(ARTIFACT) if ARTIFACT.exists() else train()
        return _model


def predict_proba(features: dict) -> float:
    return float(get_model().predict_proba([vectorize(features)])[0][1])


def evaluate(n_samples: int, fraud_rate: float, seed: int | None) -> dict:
    """Score a fresh synthetic population (different seed from training) and report metrics."""
    X, y = generate_synthetic(n_samples, fraud_rate, seed)
    predicted = (get_model().predict_proba(X)[:, 1] >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
    return {
        "accuracy": accuracy_score(y, predicted),
        "precision": precision_score(y, predicted, zero_division=0),
        "recall": recall_score(y, predicted, zero_division=0),
        "f1": f1_score(y, predicted, zero_division=0),
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


if __name__ == "__main__":
    train()
    print(f"Saved {MODEL_VERSION} to {ARTIFACT}")
    print(evaluate(5000, 0.08, seed=7))
