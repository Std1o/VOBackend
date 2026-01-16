from typing import List
from fastapi import APIRouter, Depends

from vo.model.auth import User
from vo.model.black_list import BlackList
from vo.model.channel import ChannelUsers
from vo.service.auth import get_current_user
from vo.service.channels import ChannelsService

router = APIRouter(prefix='/channel/management')


@router.delete('/participants', response_model=List[ChannelUsers])
async def delete_participant(channel_id: int, participant_id: int,
                       user: User = Depends(get_current_user), service: ChannelsService = Depends()):
    return await service.delete_participant(user.id, participant_id, channel_id)

@router.post('/black_list', response_model=List[BlackList])
async def add_to_black_list(channel_id: int, participant_id: int,
                       user: User = Depends(get_current_user), service: ChannelsService = Depends()):
    return await service.add_to_black_list(participant_id, channel_id)
