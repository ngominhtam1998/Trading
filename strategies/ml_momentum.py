import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from .base import Strategy
from features import compute_features


class MLMomentumStrategy(Strategy):
    """
    Walk-forward ML momentum strategy.
    Trains a Random Forest on technical features to predict next-candle direction.
    No future data is used: model is retrained on a rolling window and predicts one step ahead.
    """

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.train_window = self.params.get("train_window", 300)
        self.min_train = self.params.get("min_train", 150)
        self.threshold = self.params.get("threshold", 0.55)
        self.n_estimators = self.params.get("n_estimators", 30)
        self.max_depth = self.params.get("max_depth", 4)
        self.retrain_every = self.params.get("retrain_every", 50)

    @property
    def name(self):
        return f"ml_momentum_{self.train_window}_{self.threshold}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = compute_features(df)
        df["target"] = np.where(df["close"].shift(-1) > df["close"], 1,
                                np.where(df["close"].shift(-1) < df["close"], -1, 0))

        feature_cols = [c for c in df.columns if c not in [
            "timestamp", "open", "high", "low", "close", "volume", "turnover", "target"
        ]]
        df = df.dropna()
        if len(df) < self.min_train + 10:
            return pd.Series(0, index=df.index)

        X = df[feature_cols].values
        y = df["target"].values
        signal = pd.Series(0, index=df.index)

        model = None
        for i in range(self.train_window, len(df)):
            if (i - self.train_window) % self.retrain_every == 0:
                start = max(0, i - self.train_window)
                X_train = X[start:i]
                y_train = y[start:i]
                if len(set(y_train)) < 2:
                    continue
                model = RandomForestClassifier(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    random_state=42,
                    n_jobs=1,
                )
                model.fit(X_train, y_train)
            if model is None:
                continue
            proba = model.predict_proba(X[i].reshape(1, -1))[0]
            classes = model.classes_
            if len(classes) < 3:
                continue
            prob_up = proba[classes == 1][0] if 1 in classes else 0
            prob_down = proba[classes == -1][0] if -1 in classes else 0
            if prob_up > self.threshold:
                signal.iloc[i] = 1
            elif prob_down > self.threshold:
                signal.iloc[i] = -1

        return signal
