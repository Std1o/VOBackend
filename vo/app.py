from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from vo.api import router

app = FastAPI(
    max_request_size=None
)
app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене заменить на конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)