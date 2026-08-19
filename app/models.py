from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Employee(Base):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    username = Column(String(80), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False, default='')
    role = Column(String(120), default='staff')
    phone = Column(String(50), nullable=True)
    telegram_id = Column(String(50), unique=True, nullable=True)
    hourly_rate = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    shifts = relationship('Shift', back_populates='employee')
    messages = relationship('Message', back_populates='employee')
    payments = relationship('PayrollPayment', back_populates='employee')


class Shift(Base):
    __tablename__ = 'shifts'

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(30), default='active')
    notes = Column(String(255), nullable=True)
    pay_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship('Employee', back_populates='shifts')


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)

    employee = relationship('Employee', back_populates='messages')


class PayrollPayment(Base):
    __tablename__ = 'payroll_payments'

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=False)
    amount = Column(Float, nullable=False, default=0.0)
    period_start = Column(DateTime, nullable=False, default=datetime.utcnow)
    period_end = Column(DateTime, nullable=False, default=datetime.utcnow)
    paid_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(255), nullable=True)

    employee = relationship('Employee', back_populates='payments')
