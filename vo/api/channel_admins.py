from typing import List

from fastapi import APIRouter, Depends

from vo.model.auth import User
from vo.model.channel import ChannelUsers
from vo.service.auth import get_current_user
from vo.service.channel_admins import ChannelAdminsService

router = APIRouter(prefix='/channel/admins')


@router.post('/', response_model=List[ChannelUsers])
async def add_admin(channel_id: int, admin_id: int,
              user: User = Depends(get_current_user), service: ChannelAdminsService = Depends()):
    return await service.add_admin(user.id, admin_id, channel_id)


@router.delete('/', response_model=List[ChannelUsers])
async def delete_admin(channel_id: int, admin_id: int,
                 user: User = Depends(get_current_user), service: ChannelAdminsService = Depends()):
    return await service.delete_admin(user.id, admin_id, channel_id)
