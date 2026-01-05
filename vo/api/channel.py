from typing import List

from fastapi import APIRouter, Depends, Response, status, HTTPException

from vo.model.auth import User
from vo.model.channel import Channel
from vo.service.auth import get_current_user
from vo.service.channels import ChannelsService

router = APIRouter(prefix='/channels')


@router.get('/', response_model=List[Channel])
def get_channels(user: User = Depends(get_current_user), service: ChannelsService = Depends()):
    return service.get_channels(user.id)

@router.post('/{channel_code}', response_model=Channel)
def join_the_course(channel_code: str, user: User = Depends(get_current_user), service: ChannelsService = Depends()):
    return service.join(user.id, channel_code)