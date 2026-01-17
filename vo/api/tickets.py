from typing import List

from fastapi import APIRouter, Depends

from vo.model.auth import User
from vo.model.tickets import Ticket
from vo.service.auth import get_current_user
from vo.service.ticket import TicketService

router = APIRouter(prefix='/tickets')


@router.post("/")
async def create_ticket(
        ticket: Ticket,
        user: User = Depends(get_current_user),
        service: TicketService = Depends()
):
     return await service.create_ticket(ticket)

@router.get('/', response_model=List[Ticket])
async def get_tickets(service: TicketService = Depends()):
    return await service.get_tickets()

@router.get('/my', response_model=List[Ticket])
async def get_my_tickets(user: User = Depends(get_current_user), service: TicketService = Depends()):
    return await service.get_my_tickets(user.id)

@router.post("/give_premium")
async def give_premium(
        phone: str,
        service: TicketService = Depends()
):
     return await service.give_premium(phone)

@router.post("/reject_premium")
async def reject_premium(
        phone: str,
        service: TicketService = Depends()
):
     return await service.reject_premium(phone)