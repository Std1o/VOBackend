from datetime import datetime, timedelta
from typing import List

from dateutil.relativedelta import relativedelta
from fastapi import Depends
from sqlalchemy import select

from vo import tables
from vo.database import Session, get_session
from vo.model.tickets import Ticket


class TicketService:
    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    async def get_tickets(self) -> List[Ticket]:
        statement = select(tables.Tickets)
        return self.session.execute(statement).scalars().all()

    async def get_my_tickets(self, user_id: int) -> List[Ticket]:
        statement = select(tables.Tickets).filter_by(user_id = user_id)
        return self.session.execute(statement).scalars().all()

    async def create_ticket(self, ticket: Ticket) -> Ticket:
        new_ticket = tables.Tickets(
            user_id=ticket.user_id,
            username=ticket.username,
            phone=ticket.phone,
            image_url=ticket.image_url
        )
        self.session.add(new_ticket)
        self.session.commit()

        return ticket

    async def get_user_by_phone(self, phone: str) -> tables.User:
        statement = select(tables.User).filter_by(phone=phone)
        return self.session.execute(statement).scalars().first()

    async def get_ticket_by_phone(self, phone: str) -> tables.Tickets:
        statement = select(tables.Tickets).filter_by(phone=phone)
        return self.session.execute(statement).scalars().first()

    async def give_premium(self, phone: str):
        user = await self.get_user_by_phone(phone)
        user.premium = datetime.now() + relativedelta(months=1)
        self.session.commit()
        ticket = await self.get_ticket_by_phone(phone)
        self.session.delete(ticket)
        self.session.commit()
        return await self.get_tickets()

    async def reject_premium(self, phone: str):
        ticket = await self.get_ticket_by_phone(phone)
        self.session.delete(ticket)
        self.session.commit()
        return await self.get_tickets()