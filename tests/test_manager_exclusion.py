from app.logic import payroll_summary
from app.models import Employee


def test_payroll_summary_excludes_manager_from_staff_list():
    manager = Employee(id=1, full_name='Руководитель', username='manager', password_hash='x', role='manager', hourly_rate=300.0)
    staff = Employee(id=2, full_name='Иван', username='ivan', password_hash='x', role='staff', hourly_rate=250.0)

    summary = payroll_summary([manager, staff], {2: []}, {2: []})

    assert summary['employees'] == [
        {
            'id': 2,
            'employee_id': 2,
            'full_name': 'Иван',
            'role': 'staff',
            'hourly_rate': 250.0,
            'total_hours': 0.0,
            'total_payment': 0.0,
            'total_paid': 0.0,
            'amount_due': 0.0,
            'active_shift': False,
            'shift_count': 0,
        }
    ]
