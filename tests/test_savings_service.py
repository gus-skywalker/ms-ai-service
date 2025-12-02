from app.features.savings.service import generate_savings_recommendations
from app.features.savings.types import SavingsRecommendationRequest
import pytest
from datetime import date, timedelta

def test_success():
    req = SavingsRecommendationRequest(savingsGoalAmount=600, targetDate=None)
    resp = generate_savings_recommendations("user1", req)
    assert resp.plan.recommendedMonthlySavings > 0
    assert resp.plan.projectedBalanceByTargetDate == 600
    assert resp.plan.actions
    assert resp.summaryText

def test_goal_default():
    req = SavingsRecommendationRequest(savingsGoalAmount=None, targetDate=None)
    resp = generate_savings_recommendations("user1", req)
    assert resp.plan.recommendedMonthlySavings > 0
    assert resp.plan.projectedBalanceByTargetDate == 200
    assert resp.plan.actions
    assert resp.summaryText

def test_savings_with_target_date():
    future_date = (date.today().replace(day=1) + timedelta(days=31*8)).replace(day=1)
    req = SavingsRecommendationRequest(savingsGoalAmount=800, targetDate=future_date.strftime("%Y-%m-%d"))
    resp = generate_savings_recommendations("user1", req)
    assert resp.plan.recommendedMonthlySavings > 0
    assert resp.plan.projectedBalanceByTargetDate == 800
    assert resp.plan.actions
    assert resp.summaryText

