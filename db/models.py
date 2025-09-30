from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, Numeric, Index, Boolean, Enum, func, Text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()

class TradeType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    instrument = Column(String(64), nullable=False, index=True)
    amount = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    trade_type = Column(Enum(TradeType), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    audit_events = relationship("AuditEvent", back_populates="trade", cascade="all, delete-orphan")

Index("ix_trades_user_instrument", Trade.user_id, Trade.instrument)

class Portfolio(Base):
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    positions = relationship("PortfolioPosition", back_populates="portfolio", cascade="all, delete-orphan")

class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"
    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    instrument = Column(String(64), nullable=False, index=True)
    quantity = Column(Numeric(20, 8), nullable=False)
    avg_price = Column(Numeric(20, 8), nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    portfolio = relationship("Portfolio", back_populates="positions")

Index("ix_positions_portfolio_instrument", PortfolioPosition.portfolio_id, PortfolioPosition.instrument, unique=True)

class AuditEventType(str, enum.Enum):
    TRADE_EXECUTED = "TRADE_EXECUTED"
    PORTFOLIO_UPDATED = "PORTFOLIO_UPDATED"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    # etc

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(Enum(AuditEventType), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id", ondelete="SET NULL"), nullable=True, index=True)
    description = Column(Text, nullable=False)
    compliance_flag = Column(Boolean, nullable=False, default=False)

    trade = relationship("Trade", back_populates="audit_events")

Index("ix_audit_events_user_type_time", AuditEvent.user_id, AuditEvent.event_type, AuditEvent.occurred_at)

