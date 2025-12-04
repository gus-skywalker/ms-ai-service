import pandas as pd
from app.core import trainers


def test_is_eligible_false_when_missing_data(monkeypatch):
    empty_df = pd.DataFrame()
    monkeypatch.setattr(trainers, "_load_monthly_series", lambda uid: empty_df)
    assert trainers.is_eligible_for_training("user") is False

