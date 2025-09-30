from sqlalchemy.future import select
from sqlalchemy import update, func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db import models
from typing import List, Optional
from contextlib import asynccontextmanager

# Audit logging utility
async def log_audit_event(session: AsyncSession, event_type: models.AuditEventType, user_id: Optional[int], 
                         trade_id: Optional[int], description: str, compliance_flag: bool = False):
    audit = models.AuditEvent(
        event_type=event_type,
        user_id=user_id,
        trade_id=trade_id,
        description=description,
        compliance_flag=compliance_flag
    )
    session.add(audit)

# Transactionally safe trade execution and audit logging
async def execute_trade(session: AsyncSession, user_id: int, instrument: str, amount, price, trade_type: models.TradeType):
    from sqlalchemy import select
    async with session.begin():
        # Insert new trade
        trade = models.Trade(
            user_id=user_id,
            instrument=instrument,
            amount=amount,
            price=price,
            trade_type=trade_type
        )
        session.add(trade)
        await session.flush()  # get trade.id

        # Portfolio logic (idempotent update or insert)
        # Make sure portfolio exists
        result = await session.execute(select(models.Portfolio).where(models.Portfolio.user_id==user_id))
        portfolio = result.scalars().first()
        if not portfolio:
            portfolio = models.Portfolio(user_id=user_id)
            session.add(portfolio)
            await session.flush()

        # Find or create position
        pos_result = await session.execute(
            select(models.PortfolioPosition).where(
                models.PortfolioPosition.portfolio_id==portfolio.id,
                models.PortfolioPosition.instrument==instrument
            ).with_for_update()
        )
        pos = pos_result.scalars().first()
        if pos:
            if trade_type == models.TradeType.BUY:
                new_qty = pos.quantity + amount
            else:
                new_qty = pos.quantity - amount
            new_total = (pos.quantity * pos.avg_price + amount * price) if trade_type == models.TradeType.BUY else (pos.quantity * pos.avg_price - amount * pos.avg_price)
            new_avg = new_total / new_qty if new_qty > 0 else 0.0
            pos.quantity = new_qty
            pos.avg_price = new_avg
        else:
            pos = models.PortfolioPosition(
                portfolio_id=portfolio.id,
                instrument=instrument,
                quantity=amount if trade_type == models.TradeType.BUY else -amount,
                avg_price=price,
            )
            session.add(pos)
        # Audit event
        await log_audit_event(session, models.AuditEventType.TRADE_EXECUTED, user_id=user_id, trade_id=trade.id,
                             description=f"Executed {trade_type} {amount} {instrument} @ {price}")
    return trade

# Efficient portfolio summary async query
async def get_portfolio_summary(session: AsyncSession, user_id: int):
    from sqlalchemy import select
    q = (
        select(models.PortfolioPosition.instrument,
               models.PortfolioPosition.quantity,
               models.PortfolioPosition.avg_price)
        .join(models.Portfolio, models.PortfolioPosition.portfolio_id==models.Portfolio.id)
        .where(models.Portfolio.user_id == user_id)
        .order_by(models.PortfolioPosition.instrument)
    )
    result = await session.execute(q)
    return [dict(zip(r.keys(), r)) for r in result]

# Efficient, indexed audit log queries (for compliance reporting)
async def get_audit_events(session: AsyncSession, *, user_id: Optional[int]=None,
                         event_type: Optional[models.AuditEventType]=None,
                         since: Optional[str]=None, until: Optional[str]=None, limit: int=100):
    from sqlalchemy import select, and_
    q = select(models.AuditEvent)
    conds = []
    if user_id:
        conds.append(models.AuditEvent.user_id==user_id)
    if event_type:
        conds.append(models.AuditEvent.event_type==event_type)
    if since:
        conds.append(models.AuditEvent.occurred_at>=since)
    if until:
        conds.append(models.AuditEvent.occurred_at<=until)
    if conds:
        q = q.where(and_(*conds))
    q = q.order_by(models.AuditEvent.occurred_at.desc()).limit(limit)
    result = await session.execute(q)
    return result.scalars().all()

# End-of-day data process: aggregate fast with async
async def end_of_day_process(session: AsyncSession):
    # Example: Summarize all trades for the day by user/instrument, write to audit log
    from sqlalchemy import select, func
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    midnight = datetime(now.year, now.month, now.day)
    q = (
        select(
            models.Trade.user_id,
            models.Trade.instrument,
            func.sum(models.Trade.amount).label('net_amount'),
            func.avg(models.Trade.price).label('avg_price'),
        )
        .where(models.Trade.timestamp >= midnight)
        .group_by(models.Trade.user_id, models.Trade.instrument)
    )
    result = await session.execute(q)
    rows = result.fetchall()
    # Write as events to AuditEvent
    async with session.begin():
        for row in rows:
            await log_audit_event(
                session,
                event_type=models.AuditEventType.SYSTEM_EVENT,
                user_id=row.user_id,
                trade_id=None,
                description=f"EOD Summary: {row.net_amount} {row.instrument} @ avg {row.avg_price}",
                compliance_flag=True
            )
    await session.commit()
    return len(rows)

# Utility: efficiently paged trades (for history endpoints)
async def get_user_trades(session: AsyncSession, user_id: int, limit: int=100, offset: int=0):
    from sqlalchemy import select
    q = select(models.Trade).where(models.Trade.user_id==user_id).order_by(models.Trade.timestamp.desc()).offset(offset).limit(limit)
    result = await session.execute(q)
    return result.scalars().all()
