from __future__ import annotations

from collections.abc import Iterable

from app.models import Employee, PayrollPayment, Shift


def calculate_shift_payment(hours: float, hourly_rate: float) -> float:
    total_hours = max(hours, 0.0)
    return round(total_hours * float(hourly_rate), 2)


def get_total_shift_hours(shifts: Iterable[Shift]) -> float:
    total_hours = 0.0
    for shift in shifts:
        if shift.started_at and shift.ended_at:
            duration = shift.ended_at - shift.started_at
            total_hours += max(duration.total_seconds() / 3600.0, 0.0)
    return round(total_hours, 2)


def build_employee_report(employee: Employee, shifts: list[Shift], payments: list[PayrollPayment] | None = None) -> dict:
    total_hours = get_total_shift_hours(shifts)
    total_payment = 0.0
    for shift in shifts:
        if shift.started_at and shift.ended_at:
            hours = (shift.ended_at - shift.started_at).total_seconds() / 3600.0
            total_payment += calculate_shift_payment(hours, employee.hourly_rate)

    total_payouts = round(sum(payment.amount for payment in (payments or [])), 2)
    remaining_due = max(total_payment - total_payouts, 0.0)
    active_shift = next((shift for shift in shifts if shift.ended_at is None), None)
    return {
        'id': employee.id,
        'employee_id': employee.id,
        'full_name': employee.full_name,
        'role': employee.role,
        'hourly_rate': employee.hourly_rate,
        'total_hours': round(total_hours, 2),
        'total_payment': round(total_payment, 2),
        'total_paid': total_payouts,
        'amount_due': round(remaining_due, 2),
        'active_shift': active_shift is not None,
        'shift_count': len(shifts),
    }


def payroll_summary(
    employees: list[Employee],
    employee_shifts: dict[int, list[Shift]],
    employee_payments: dict[int, list[PayrollPayment]] | None = None,
) -> dict:
    itemized = []
    total_payment = 0.0
    total_payouts = 0.0
    active_staff = 0
    for employee in employees:
        if employee.role and employee.role.lower() == 'manager':
            continue
        payments = employee_payments.get(employee.id, []) if employee_payments else []
        report = build_employee_report(employee, employee_shifts.get(employee.id, []), payments)
        total_payment += report['total_payment']
        total_payouts += report['total_paid']
        if report['active_shift']:
            active_staff += 1
        itemized.append(report)
    total_due = max(total_payment - total_payouts, 0.0)
    return {
        'total_paid': round(total_payment, 2),
        'total_payouts': round(total_payouts, 2),
        'total_due': round(total_due, 2),
        'active_staff': active_staff,
        'employees': itemized,
    }
