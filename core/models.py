from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_type: Mapped[str] = mapped_column(String(20), nullable=False, default='anonymous')
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    groups: Mapped[List['FundGroup']] = relationship('FundGroup', back_populates='user', cascade='all, delete-orphan')
    funds: Mapped[List['UserFund']] = relationship('UserFund', back_populates='user', cascade='all, delete-orphan')
    transactions: Mapped[List['FundTransaction']] = relationship(
        'FundTransaction',
        back_populates='user',
        cascade='all, delete-orphan',
    )
    conversions: Mapped[List['FundConversion']] = relationship(
        'FundConversion',
        back_populates='user',
        cascade='all, delete-orphan',
    )
    dca_plans: Mapped[List['FundDcaPlan']] = relationship(
        'FundDcaPlan',
        back_populates='user',
        cascade='all, delete-orphan',
    )


class FundGroup(Base):
    __tablename__ = 'fund_groups'
    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uq_fund_groups_user_name'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped['User'] = relationship('User', back_populates='groups')
    funds: Mapped[List['UserFund']] = relationship('UserFund', back_populates='group')


class UserFund(Base):
    __tablename__ = 'user_funds'
    __table_args__ = (
        UniqueConstraint('user_id', 'fund_code', name='uq_user_funds_user_code'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey('fund_groups.id', ondelete='SET NULL'), nullable=True, index=True)
    fund_code: Mapped[str] = mapped_column(String(6), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    holding_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    holding_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    holding_shares: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_cost_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    snapshot_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    snapshot_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    position_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped['User'] = relationship('User', back_populates='funds')
    group: Mapped[Optional[FundGroup]] = relationship('FundGroup', back_populates='funds')


class FundTransaction(Base):
    __tablename__ = 'fund_transactions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    fund_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='CONFIRMED')
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    conversion_id: Mapped[Optional[int]] = mapped_column(ForeignKey('fund_conversions.id', ondelete='SET NULL'), nullable=True, index=True)
    related_fund_code: Mapped[Optional[str]] = mapped_column(String(6), nullable=True)
    submitted_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    time_slot: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    nav_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    confirm_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    fee_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shares: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_dca: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped['User'] = relationship('User', back_populates='transactions')
    conversion: Mapped[Optional['FundConversion']] = relationship('FundConversion', back_populates='transactions')


class FundConversion(Base):
    __tablename__ = 'fund_conversions'
    __table_args__ = (
        UniqueConstraint('batch_id', name='uq_fund_conversions_batch_id'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_fund_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    to_fund_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDING')
    submitted_date: Mapped[str] = mapped_column(String(10), nullable=False)
    time_slot: Mapped[str] = mapped_column(String(20), nullable=False)
    from_shares: Mapped[float] = mapped_column(Float, nullable=False)
    from_nav_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    from_confirm_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    from_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    from_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    from_fee_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    from_fee: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    to_nav_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    to_confirm_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    to_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    to_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    to_fee_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    to_fee: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    to_shares: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    supplement_fee_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    supplement_fee: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped['User'] = relationship('User', back_populates='conversions')
    transactions: Mapped[List['FundTransaction']] = relationship('FundTransaction', back_populates='conversion')


class FundDcaPlan(Base):
    __tablename__ = 'fund_dca_plans'
    __table_args__ = (
        UniqueConstraint('user_id', 'fund_code', name='uq_fund_dca_plans_user_code'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    fund_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    fee_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    cycle: Mapped[str] = mapped_column(String(20), nullable=False, default='monthly')
    first_date: Mapped[str] = mapped_column(String(10), nullable=False)
    last_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    weekly_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    monthly_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped['User'] = relationship('User', back_populates='dca_plans')
