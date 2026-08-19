from app.logic import calculate_shift_payment, payroll_summary
from app.models import Employee


def test_calculate_shift_payment():
    assert calculate_shift_payment(3, 250) == 750.0


def test_payroll_summary():
    employee = Employee(id=1, full_name='Test', username='test', password_hash='x', role='staff', hourly_rate=200.0)
    shifts = []
    payments = []
    summary = payroll_summary([employee], {1: shifts}, {1: payments})
    assert summary['total_paid'] == 0.0
    assert summary['employees'][0]['amount_due'] == 0.0
