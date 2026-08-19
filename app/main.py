from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.logic import build_employee_report, calculate_shift_payment, payroll_summary
from app.models import Employee, Message, PayrollPayment, Shift

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))
app = FastAPI(title='Club Shift Manager', version='0.1.0')

Base.metadata.create_all(bind=engine)


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200000).hex()
    return f'pbkdf2_sha256${salt}${digest}'


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not password or not stored_hash:
        return False
    try:
        _, salt, digest = stored_hash.split('$', 2)
    except ValueError:
        return False
    computed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200000).hex()
    return hmac.compare_digest(computed, digest)


def normalize_username(value: str) -> str:
    return (value or '').strip().lower()


def get_manager_credentials() -> tuple[str, str, str]:
    username = (os.getenv('MANAGER_USERNAME', '').strip() or 'manager').lower()
    password = (os.getenv('MANAGER_PASSWORD', '').strip() or 'manager123')
    telegram_id = (os.getenv('MANAGER_TELEGRAM_ID', '').strip() or '')
    return username, password, telegram_id


def derive_demo_username(full_name: str | None, role: str | None = None) -> str:
    normalized_name = (full_name or '').strip().lower()
    if role and role.lower() == 'manager':
        return 'manager'
    mapping = {
        'manager': 'manager',
        'иван': 'ivan',
        'иван петров': 'ivan',
        'мария': 'maria',
        'мария сидорова': 'maria',
        'алексей': 'alex',
        'алексей кузнецов': 'alex',
    }
    for key, value in mapping.items():
        if normalized_name == key or normalized_name.startswith(key):
            return value
    cleaned = re.sub(r'[^a-z0-9]+', '', normalized_name, flags=re.IGNORECASE)
    if cleaned:
        return cleaned
    return 'employee'


def ensure_employee_auth_columns(db: Session):
    bind = db.get_bind()
    if bind is None:
        return
    inspector = inspect(bind)
    if not inspector.has_table('employees'):
        return
    names = {column['name'] for column in inspector.get_columns('employees')}
    if 'username' not in names:
        db.execute(text('ALTER TABLE employees ADD COLUMN username VARCHAR(80)'))
    if 'password_hash' not in names:
        db.execute(text('ALTER TABLE employees ADD COLUMN password_hash VARCHAR(255) DEFAULT "" NOT NULL'))
    db.commit()


def ensure_demo_credentials(db: Session):
    manager_username, manager_password, manager_telegram_id = get_manager_credentials()
    users = {
        manager_username: manager_password,
        'ivan': 'ivan123',
        'maria': 'maria123',
        'alex': 'alex123',
    }
    for employee in db.query(Employee).all():
        if employee.role and employee.role.lower() == 'manager':
            employee.username = manager_username
            employee.password_hash = hash_password(manager_password)
            if manager_telegram_id:
                employee.telegram_id = manager_telegram_id
            continue

        candidate = normalize_username(employee.username) or derive_demo_username(employee.full_name, employee.role)
        if not candidate:
            continue
        if any(ch.isalpha() and ord(ch) > 127 for ch in candidate):
            candidate = derive_demo_username(employee.full_name, employee.role)
        if not candidate:
            continue
        base_username = candidate
        counter = 1
        while db.query(Employee).filter(Employee.username == base_username, Employee.id != employee.id).first():
            base_username = f'{candidate}{counter}'
            counter += 1
        employee.username = base_username

        if employee.username in users:
            employee.password_hash = hash_password(users[employee.username])
        elif not employee.password_hash:
            employee.password_hash = hash_password(f'{employee.username}123')
    db.commit()


def get_configured_telegram_username() -> str:
    username = os.getenv('TELEGRAM_BOT_USERNAME', '').strip().lstrip('@')
    if not username or 'your_' in username.lower() or 'bot_username_here' in username.lower() or username.lower() == 'your_bot_username_here':
        return ''
    return username


def verify_telegram_auth(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token or 'your_telegram_bot_token_here' in token.lower() or 'token_here' in token.lower():
        return False
    received_hash = data.get('hash')
    if not received_hash:
        return False

    payload = {key: value for key, value in data.items() if key != 'hash'}
    secret_key = hashlib.sha256(token.encode()).digest()
    computed_hash = hmac.new(
        secret_key,
        '\n'.join(f'{key}={payload[key]}' for key in sorted(payload)).encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed_hash, received_hash)


def get_db():
    db = SessionLocal()
    try:
        ensure_employee_auth_columns(db)
        yield db
    finally:
        db.close()


def parse_date_filter(value: str | None, *, end_of_day: bool = False):
    if not value:
        return None
    date_value = datetime.strptime(value, '%Y-%m-%d')
    if end_of_day:
        return date_value.replace(hour=23, minute=59, second=59, microsecond=0)
    return date_value.replace(hour=0, minute=0, second=0, microsecond=0)


def filter_shifts(shifts, start_date=None, end_date=None):
    result = list(shifts)
    if start_date:
        result = [shift for shift in result if shift.started_at >= start_date]
    if end_date:
        result = [shift for shift in result if shift.started_at <= end_date]
    return sorted(result, key=lambda shift: shift.started_at, reverse=True)


def seed_demo_data(db: Session):
    if db.query(Employee).count() > 0:
        ensure_demo_credentials(db)
        return

    manager_username, manager_password, manager_telegram_id = get_manager_credentials()
    employees = [
        Employee(
            full_name='Руководитель',
            username=manager_username,
            password_hash=hash_password(manager_password),
            role='manager',
            phone='+79990000001',
            telegram_id=manager_telegram_id or '1001',
            hourly_rate=350.0,
            is_active=True,
        ),
        Employee(
            full_name='Иван Петров',
            username='ivan',
            password_hash=hash_password('ivan123'),
            role='staff',
            phone='+79990000002',
            telegram_id='1002',
            hourly_rate=250.0,
            is_active=True,
        ),
        Employee(
            full_name='Мария Сидорова',
            username='maria',
            password_hash=hash_password('maria123'),
            role='staff',
            phone='+79990000003',
            telegram_id='1003',
            hourly_rate=260.0,
            is_active=True,
        ),
        Employee(
            full_name='Алексей Кузнецов',
            username='alex',
            password_hash=hash_password('alex123'),
            role='staff',
            phone='+79990000004',
            telegram_id='1004',
            hourly_rate=270.0,
            is_active=True,
        ),
    ]
    db.add_all(employees)
    db.commit()

    now = datetime.utcnow()
    shifts = [
        Shift(employee_id=employees[0].id, started_at=now - timedelta(hours=5), ended_at=now - timedelta(hours=1), status='completed', pay_amount=1400.0),
        Shift(employee_id=employees[1].id, started_at=now - timedelta(hours=3), status='active', notes='Начал смену'),
        Shift(employee_id=employees[2].id, started_at=now - timedelta(hours=7), ended_at=now - timedelta(hours=2), status='completed', pay_amount=1300.0),
    ]
    db.add_all(shifts)
    db.commit()


@app.on_event('startup')
def startup_event():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        ensure_employee_auth_columns(session)
        seed_demo_data(session)
    finally:
        session.close()


@app.get('/api/health')
def health_check():
    return {'status': 'ok', 'service': 'club-shift-manager'}


def get_current_employee(request: Request, db: Session) -> Employee:
    employee_id = request.cookies.get('club_employee_id')
    if not employee_id:
        raise HTTPException(status_code=401, detail='Authentication required')
    employee = db.query(Employee).filter(Employee.id == int(employee_id)).first()
    if employee is None:
        raise HTTPException(status_code=401, detail='Authentication required')
    return employee


@app.get('/', response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    telegram_username = get_configured_telegram_username()
    telegram_widget_enabled = bool(telegram_username) and request.url.hostname not in {'127.0.0.1', 'localhost', '0.0.0.0'}
    return templates.TemplateResponse('login.html', {
        'request': request,
        'employees': [],
        'telegram_bot_username': telegram_username,
        'telegram_widget_enabled': telegram_widget_enabled,
        'error': None,
    })


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    telegram_username = get_configured_telegram_username()
    telegram_widget_enabled = bool(telegram_username) and request.url.hostname not in {'127.0.0.1', 'localhost', '0.0.0.0'}
    return templates.TemplateResponse('login.html', {
        'request': request,
        'employees': [],
        'telegram_bot_username': telegram_username,
        'telegram_widget_enabled': telegram_widget_enabled,
        'error': None,
    })


@app.post('/login')
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = normalize_username(username)
    employee = db.query(Employee).filter(Employee.username == username).first()
    if employee is None or not verify_password(password, employee.password_hash):
        telegram_username = get_configured_telegram_username()
        telegram_widget_enabled = bool(telegram_username) and request.url.hostname not in {'127.0.0.1', 'localhost', '0.0.0.0'}
        return templates.TemplateResponse('login.html', {
            'request': request,
            'employees': [],
            'telegram_bot_username': telegram_username,
            'telegram_widget_enabled': telegram_widget_enabled,
            'error': 'Неверный логин или пароль',
        }, status_code=401)

    redirect = RedirectResponse(url='/manager' if employee.role and employee.role.lower() == 'manager' else f'/employee/{employee.id}', status_code=303)
    redirect.set_cookie(key='club_employee_id', value=str(employee.id), httponly=True, samesite='lax')
    return redirect


@app.post('/logout')
def logout_user():
    response = RedirectResponse(url='/login', status_code=303)
    response.delete_cookie(key='club_employee_id')
    return response


@app.post('/auth/telegram/widget')
async def telegram_widget_login(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    if not verify_telegram_auth(payload):
        raise HTTPException(status_code=401, detail='Telegram verification failed')

    telegram_id = str(payload.get('id'))
    if not telegram_id:
        raise HTTPException(status_code=400, detail='Telegram user id is missing')

    employee = db.query(Employee).filter(Employee.telegram_id == telegram_id).first()
    if employee is None:
        raise HTTPException(status_code=403, detail='This Telegram account is not linked to an employee')

    redirect = RedirectResponse(url=f'/employee/{employee.id}', status_code=303)
    redirect.set_cookie(key='club_employee_id', value=str(employee.id), httponly=True, samesite='lax')
    return redirect


@app.get('/manager', response_class=HTMLResponse)
def manager_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    start_date: str | None = None,
    end_date: str | None = None,
):
    current_user = get_current_employee(request, db)
    if not current_user.role or current_user.role.lower() != 'manager':
        raise HTTPException(status_code=403, detail='Access denied')

    employees = db.query(Employee).order_by(Employee.full_name).all()
    all_shifts = db.query(Shift).order_by(Shift.started_at.desc()).all()
    messages = db.query(Message).order_by(Message.created_at.desc()).all()
    payments = db.query(PayrollPayment).order_by(PayrollPayment.paid_at.desc()).all()

    start_dt = parse_date_filter(start_date)
    end_dt = parse_date_filter(end_date, end_of_day=True)
    filtered_shifts = filter_shifts(all_shifts, start_dt, end_dt)

    employee_shifts = {
        employee.id: [shift for shift in filtered_shifts if shift.employee_id == employee.id]
        for employee in employees
    }
    employee_payments = {
        employee.id: [payment for payment in payments if payment.employee_id == employee.id]
        for employee in employees
    }
    summary = payroll_summary(employees, employee_shifts, employee_payments)
    active_shifts = [shift for shift in filtered_shifts if shift.ended_at is None]
    recent_shifts = [shift for shift in filtered_shifts if shift.ended_at is not None][:10]
    completed_count = sum(1 for shift in filtered_shifts if shift.ended_at is not None)
    total_payouts = round(sum(payment.amount for payment in payments), 2)

    return templates.TemplateResponse('manager_dashboard.html', {
        'request': request,
        'employees': employees,
        'active_shifts': active_shifts,
        'recent_shifts': recent_shifts,
        'messages': messages,
        'payments': payments,
        'summary': summary,
        'filter_start': start_date,
        'filter_end': end_date,
        'completed_shifts': completed_count,
        'total_payouts': total_payouts,
        'total_due': round(max(summary['total_paid'] - total_payouts, 0.0), 2),
    })


@app.post('/manager/add_employee')
def add_employee(
    full_name: str = Form(...),
    username: str = Form(''),
    password: str = Form(''),
    role: str = Form('staff'),
    phone: str = Form(''),
    telegram_id: str = Form(''),
    hourly_rate: float = Form(0.0),
    db: Session = Depends(get_db),
):
    clean_name = full_name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail='Имя сотрудника обязательно')

    clean_username = normalize_username(username)
    if not clean_username:
        raise HTTPException(status_code=400, detail='Логин сотрудника обязателен')
    if db.query(Employee).filter(Employee.username == clean_username).first():
        raise HTTPException(status_code=400, detail='Такой логин уже занят')
    if not password or len(password.strip()) < 4:
        raise HTTPException(status_code=400, detail='Пароль должен содержать минимум 4 символа')

    employee = Employee(
        full_name=clean_name,
        username=clean_username,
        password_hash=hash_password(password.strip()),
        role=(role or 'staff').strip() or 'staff',
        phone=phone.strip() or None,
        telegram_id=telegram_id.strip() or None,
        hourly_rate=float(hourly_rate),
        is_active=True,
    )
    db.add(employee)
    db.commit()
    return RedirectResponse(url='/manager', status_code=303)


@app.post('/manager/delete_employee/{employee_id}')
def delete_employee(employee_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_employee(request, db)
    if not current_user.role or current_user.role.lower() != 'manager':
        raise HTTPException(status_code=403, detail='Access denied')

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')
    if employee.role and employee.role.lower() == 'manager':
        raise HTTPException(status_code=400, detail='Нельзя удалить руководителя')

    db.query(Message).filter(Message.employee_id == employee.id).delete()
    db.query(PayrollPayment).filter(PayrollPayment.employee_id == employee.id).delete()
    db.query(Shift).filter(Shift.employee_id == employee.id).delete()
    db.delete(employee)
    db.commit()
    return RedirectResponse(url='/manager', status_code=303)


@app.post('/manager/mark_message_read/{message_id}')
def mark_message_read(message_id: int, db: Session = Depends(get_db)):
    message = db.query(Message).filter(Message.id == message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail='Message not found')
    message.is_read = True
    db.commit()
    return RedirectResponse(url='/manager', status_code=303)


@app.post('/manager/checkin')
def manager_checkin(employee_id: int = Form(...), notes: str = Form(''), db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    active_shift = db.query(Shift).filter(Shift.employee_id == employee_id, Shift.ended_at.is_(None)).first()
    if active_shift:
        raise HTTPException(status_code=400, detail='У сотрудника уже есть активная смена')

    shift = Shift(employee_id=employee.id, started_at=datetime.utcnow(), status='active', notes=notes or 'Начал смену')
    db.add(shift)
    db.commit()
    return RedirectResponse(url='/manager', status_code=303)


@app.post('/manager/add_payment')
def add_payment(
    employee_id: int = Form(...),
    amount: float = Form(...),
    period_start: str = Form(''),
    period_end: str = Form(''),
    note: str = Form(''),
    db: Session = Depends(get_db),
):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    clean_amount = float(amount)
    if clean_amount < 0:
        raise HTTPException(status_code=400, detail='Сумма выплаты не может быть отрицательной')

    start_dt = parse_date_filter(period_start) or datetime.utcnow()
    end_dt = parse_date_filter(period_end, end_of_day=True) or datetime.utcnow()

    payment = PayrollPayment(
        employee_id=employee.id,
        amount=clean_amount,
        period_start=start_dt,
        period_end=end_dt,
        paid_at=datetime.utcnow(),
        note=(note or '').strip() or None,
    )
    db.add(payment)
    db.commit()
    return RedirectResponse(url='/manager', status_code=303)


@app.post('/manager/checkout')
def manager_checkout(shift_id: int = Form(...), db: Session = Depends(get_db)):
    shift = db.query(Shift).filter(Shift.id == shift_id).first()
    if shift is None:
        raise HTTPException(status_code=404, detail='Shift not found')
    if shift.ended_at is not None:
        raise HTTPException(status_code=400, detail='Смена уже завершена')

    employee = db.query(Employee).filter(Employee.id == shift.employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    ended_at = datetime.utcnow()
    shift.ended_at = ended_at
    shift.status = 'completed'
    if shift.started_at:
        hours = (ended_at - shift.started_at).total_seconds() / 3600.0
        shift.pay_amount = calculate_shift_payment(hours, employee.hourly_rate)
    db.commit()
    return RedirectResponse(url='/manager', status_code=303)


@app.get('/employee/{employee_id}', response_class=HTMLResponse)
def employee_dashboard(employee_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_employee(request, db)
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')
    if current_user.id != employee.id and (not current_user.role or current_user.role.lower() != 'manager'):
        raise HTTPException(status_code=403, detail='Access denied')

    shifts = db.query(Shift).filter(Shift.employee_id == employee_id).order_by(Shift.started_at.desc()).all()
    active_shift = db.query(Shift).filter(Shift.employee_id == employee_id, Shift.ended_at.is_(None)).first()
    payments = db.query(PayrollPayment).filter(PayrollPayment.employee_id == employee_id).order_by(PayrollPayment.paid_at.desc()).all()
    report = build_employee_report(employee, shifts, payments)
    total_paid = round(sum(payment.amount for payment in payments), 2)
    last_payment = payments[0] if payments else None
    return templates.TemplateResponse('employee_dashboard.html', {
        'request': request,
        'employee': employee,
        'shifts': shifts,
        'report': report,
        'active_shift': active_shift,
        'payments': payments,
        'total_paid': total_paid,
        'last_payment': last_payment,
        'current_user': current_user,
    })


@app.post('/employee/{employee_id}/checkin')
def employee_checkin(employee_id: int, notes: str = Form(''), db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    active_shift = db.query(Shift).filter(Shift.employee_id == employee_id, Shift.ended_at.is_(None)).first()
    if active_shift:
        raise HTTPException(status_code=400, detail='У вас уже есть активная смена')

    shift = Shift(employee_id=employee.id, started_at=datetime.utcnow(), status='active', notes=notes or 'Смена открыта через панель')
    db.add(shift)
    db.commit()
    return RedirectResponse(url=f'/employee/{employee_id}', status_code=303)


@app.post('/employee/{employee_id}/checkout')
def employee_checkout(employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    shift = db.query(Shift).filter(Shift.employee_id == employee_id, Shift.ended_at.is_(None)).first()
    if shift is None:
        raise HTTPException(status_code=400, detail='Активной смены нет')

    ended_at = datetime.utcnow()
    shift.ended_at = ended_at
    shift.status = 'completed'
    if shift.started_at:
        hours = (ended_at - shift.started_at).total_seconds() / 3600.0
        shift.pay_amount = calculate_shift_payment(hours, employee.hourly_rate)
    db.commit()
    return RedirectResponse(url=f'/employee/{employee_id}', status_code=303)


@app.post('/employee/{employee_id}/message')
def employee_message(employee_id: int, text: str = Form(...), db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    cleaned = (text or '').strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail='Текст сообщения обязателен')

    message = Message(employee_id=employee.id, text=cleaned)
    db.add(message)
    db.commit()
    return RedirectResponse(url=f'/employee/{employee_id}', status_code=303)


@app.get('/api/employees')
def list_employees(db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.full_name).all()
    return [
        {'id': employee.id, 'full_name': employee.full_name, 'role': employee.role, 'hourly_rate': employee.hourly_rate}
        for employee in employees
    ]


@app.get('/api/manager/summary')
def manager_summary(db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.full_name).all()
    all_shifts = db.query(Shift).order_by(Shift.started_at.desc()).all()
    employee_shifts = {
        employee.id: [shift for shift in all_shifts if shift.employee_id == employee.id]
        for employee in employees
    }
    return payroll_summary(employees, employee_shifts)


@app.post('/api/shifts/checkin')
def check_in(employee_id: int = Form(...), notes: str = Form(''), db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    active_shift = db.query(Shift).filter(Shift.employee_id == employee_id, Shift.ended_at.is_(None)).first()
    if active_shift:
        raise HTTPException(status_code=400, detail='Employee already has an active shift')

    shift = Shift(employee_id=employee.id, started_at=datetime.utcnow(), status='active', notes=notes)
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return {'status': 'ok', 'shift_id': shift.id, 'started_at': shift.started_at.isoformat()}


@app.post('/api/shifts/checkout')
def check_out(shift_id: int = Form(...), db: Session = Depends(get_db)):
    shift = db.query(Shift).filter(Shift.id == shift_id).first()
    if shift is None:
        raise HTTPException(status_code=404, detail='Shift not found')
    if shift.ended_at is not None:
        raise HTTPException(status_code=400, detail='Shift already closed')

    employee = db.query(Employee).filter(Employee.id == shift.employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')

    ended_at = datetime.utcnow()
    shift.ended_at = ended_at
    shift.status = 'completed'
    if shift.started_at:
        hours = (ended_at - shift.started_at).total_seconds() / 3600.0
        shift.pay_amount = calculate_shift_payment(hours, employee.hourly_rate)
    db.commit()
    return {
        'status': 'ok',
        'shift_id': shift.id,
        'ended_at': ended_at.isoformat(),
        'pay_amount': shift.pay_amount,
    }
