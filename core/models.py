from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_type: Mapped[str] = mapped_column(String(20), nullable=False, default='anonymous')
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    groups: Mapped[List['FundGroup']] = relationship('FundGroup', back_populates='user', cascade='all, delete-orphan')
    funds: Mapped[List['UserFund']] = relationship('UserFund', back_populates='user', cascade='all, delete-orphan')


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
