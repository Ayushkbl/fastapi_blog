from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import CurrentUser
from config import settings
import models
from auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from database import get_db
from schemas import (
    PostResponse,
    UserCreate,
    UserPublic,
    UserPrivate,
    UserUpdate,
    Token
)

router = APIRouter()

@router.post(
        "",
        response_model=UserPrivate,
        status_code=status.HTTP_201_CREATED,
)
async def create_user(user: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User)
        .where(func.lower(models.User.username) == user.username.lower())
    )
    existing_user = result.scalar()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )
    
    result = await db.execute(
        select(models.User)
        .where(func.lower(models.User.email) == user.email.lower())
    )
    existing_email = result.scalar()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists",
        )
    
    new_user = models.User(
        username=user.username,
        email=user.email,
        password_hash=hash_password(user.password),
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return new_user


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    user = await db.scalar(
        select(models.User)
        .where(func.lower(models.User.email) == form_data.username.lower())
    )

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or Pasword",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token with user id as subject
    access_token_expire_minutes = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expire_minutes,
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserPrivate)
async def get_current_user(
    current_user: CurrentUser
):
    """ Gets the current authenticated user """
    return current_user


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalar()
    if user:
        return user
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="User Not Found",
    )

@router.get("/{user_id}/posts", response_model=list[PostResponse])
async def get_user_posts(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalar()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User Not Found",
        )

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.user_id == user_id)
        .order_by(models.Post.date_posted.desc())
    )
    posts = result.scalars().all()
    return posts

@router.patch('/{user_id}', response_model=UserPrivate)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorised to update this user"
        )

    user = await db.scalar(
        select(models.User).where(models.User.id == user_id)
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User Not Found",
        )
    
    if user_update.username is not None and user_update.username.lower() != user.username.lower():
        existing_user = await db.scalar(
            select(models.User)
            .where(func.lower(models.User.username) == user_update.username.lower())
        )
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )
    
    if user_update.email is not None and user_update.emai.lower() != user.email.lower():
        existing_email = await db.scalar(
            select(models.User)
            .where(func.lower(models.User.email) == user_update.email.lower())
        )
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists",
            )
    
    update_data = user_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(user, field, value)
    
    await db.commit()
    await db.refresh(user)
    return user

@router.delete('/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
        user_id: int,
        current_user: CurrentUser,
        db: Annotated[AsyncSession, Depends(get_db)]
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorised to delete this user"
        )

    user = await db.scalar(
        select(models.User).where(models.User.id == user_id)
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User Not Found",
        )

    await db.delete(user)
    await db.commit()