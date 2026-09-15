"""
Detector de anomalia de cartões (Isolation Forest).

Empacota pré-processamento + modelo + distribuição de referência dos scores num
único artefato, para que treino, relatório e API usem exatamente a mesma
transformação.

Por que Isolation Forest:
  - não supervisionado: em operação real quase não há fraude confirmada;
  - isola outliers com poucos cortes, sem supor distribuição nem distância
    (LOF depende de distância e sofre com escalas e dimensões — ver benchmark);
  - rápido de treinar e de pontuar, e o SHAP tem explicador exato para árvores.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler


@dataclass
class FraudDetector:
    features: list[str]
    params: dict
    scaler: RobustScaler = field(default_factory=RobustScaler)
    model: IsolationForest | None = None
    reference_scores: np.ndarray | None = None   # scores do treino, p/ percentil
    threshold: float | None = None               # score mínimo de alerta
    metadata: dict = field(default_factory=dict)

    def _matrix(self, df: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.features if c not in df.columns]
        if missing:
            raise KeyError(f"features ausentes: {missing}")
        return self.scaler.transform(df[self.features].astype(float).fillna(0.0).to_numpy())

    def fit(self, df: pd.DataFrame, audit_fraction: float) -> "FraudDetector":
        X = df[self.features].astype(float).fillna(0.0).to_numpy()
        self.scaler.fit(X)
        # RobustScaler divide pelo IQR; feature com IQR 0 (quase sempre zero) fica
        # com escala 1 para não explodir — o IF continua vendo os raros não-zeros.
        self.scaler.scale_ = np.where(self.scaler.scale_ == 0, 1.0, self.scaler.scale_)
        self.model = IsolationForest(**self.params, n_jobs=-1).fit(self.scaler.transform(X))
        self.reference_scores = np.sort(self.score(df))
        self.threshold = float(np.quantile(self.reference_scores, 1 - audit_fraction))
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        """Score de anomalia: maior = mais suspeito."""
        return -self.model.score_samples(self._matrix(df))

    def percentile(self, scores: np.ndarray) -> np.ndarray:
        return np.searchsorted(self.reference_scores, scores, side="right") / len(self.reference_scores)

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        s = self.score(df)
        return pd.DataFrame({"anomaly_score": s, "percentil": self.percentile(s),
                             "alerta": (s >= self.threshold).astype(int)}, index=df.index)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "FraudDetector":
        return joblib.load(path)
