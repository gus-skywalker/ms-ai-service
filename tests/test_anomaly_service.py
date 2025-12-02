from app.features.anomaly.service import detect_anomalies
from app.features.anomaly.types import AnomalyDetectionRequest
from app.models.transactions import AiTransaction

import pytest

def make_transactions(outlier=False, categoryId=None):
    txs = []
    # Normal values
    for i in range(10):
        txs.append(AiTransaction(
            transactionId=f"tx-{i}",
            userId="user1",
            type="EXPENSE",
            date=f"2025-11-{i+1:02d}",
            amount=100.0 + i,
            currency="BRL",
            categoryId=categoryId,
        ))
    if outlier:
        txs.append(AiTransaction(
            transactionId="tx-outlier",
            userId="user1",
            type="EXPENSE",
            date="2025-11-20",
            amount=1000.0,
            currency="BRL",
            categoryId=categoryId,
        ))
    return txs

def test_mad_detects_outlier():
    txs = make_transactions(outlier=True)
    req = AnomalyDetectionRequest(transactions=txs)
    resp = detect_anomalies("user1", req)
    assert any(a.expense.id == "tx-outlier" and a.severity in ("high", "medium") for a in resp.anomalies)
    assert resp.summary.anomaliesCount == 1
    assert resp.summary.totalTransactionsAnalyzed == 11

def test_no_anomaly():
    txs = make_transactions(outlier=False)
    req = AnomalyDetectionRequest(transactions=txs)
    resp = detect_anomalies("user1", req)
    assert resp.summary.anomaliesCount == 0
    assert resp.summary.totalTransactionsAnalyzed == 10

def test_zscore_fallback():
    # All values identical, MAD=0, so fallback to z-score
    txs = [AiTransaction(
        transactionId=f"tx-{i}",
        userId="user1",
        type="EXPENSE",
        date=f"2025-11-{i+1:02d}",
        amount=100.0,
        currency="BRL",
    ) for i in range(10)]
    # Add one outlier
    txs.append(AiTransaction(
        transactionId="tx-outlier",
        userId="user1",
        type="EXPENSE",
        date="2025-11-20",
        amount=200.0,
        currency="BRL",
    ))
    req = AnomalyDetectionRequest(transactions=txs)
    resp = detect_anomalies("user1", req)
    assert any(a.expense.id == "tx-outlier" for a in resp.anomalies)
    assert resp.summary.anomaliesCount == 1

def test_category_filter():
    txs = make_transactions(outlier=True, categoryId=1) + make_transactions(outlier=False, categoryId=2)
    req = AnomalyDetectionRequest(transactions=txs)
    # Only analyze categoryId=1
    req.transactions = [t for t in txs if t.categoryId == 1]
    resp = detect_anomalies("user1", req)
    assert all(a.expense.categoryId == 1 for a in resp.anomalies)
    assert resp.summary.totalTransactionsAnalyzed == 11

