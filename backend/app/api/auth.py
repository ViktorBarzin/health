"""Authentication API routes: WebAuthn register, login, logout, and current user."""

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import settings
from app.core.auth import (
    create_session,
    delete_session,
    get_challenge,
    set_session_cookie,
    store_challenge,
)
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.user_credential import UserCredential
from app.schemas.auth import (
    EmailRequest,
    LoginCompleteRequest,
    RegisterCompleteRequest,
    UserResponse,
)

router = APIRouter()


@router.post("/register/begin")
async def register_begin(
    body: EmailRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Begin passkey registration: generate WebAuthn options."""
    # Find or create user
    result = await db.execute(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.email == body.email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=body.email)
        db.add(user)
        await db.flush()
        await db.refresh(user, attribute_names=["id", "credentials"])

    # Build exclude list from existing credentials
    exclude_credentials = [
        PublicKeyCredentialDescriptor(
            id=cred.credential_id,
            transports=json.loads(cred.transports) if cred.transports else [],
        )
        for cred in user.credentials
    ]

    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.email,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    store_challenge(body.email, options.challenge)

    return {"options": json.loads(options_to_json(options))}


@router.post("/register/complete", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_complete(
    body: RegisterCompleteRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Complete passkey registration: verify and store credential."""
    challenge = get_challenge(body.email)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Challenge expired or not found. Please start registration again.",
        )

    try:
        verification = verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration verification failed: {e}",
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found. Please start registration again.",
        )

    # Store transports from the client credential response
    transports = body.credential.get("response", {}).get("transports")
    transports_json = json.dumps(transports) if transports else None

    credential = UserCredential(
        user_id=user.id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        transports=transports_json,
    )
    db.add(credential)
    await db.flush()

    token = create_session(user.id)
    set_session_cookie(response, token)

    return UserResponse.model_validate(user)


@router.post("/login/begin")
async def login_begin(
    body: EmailRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Begin passkey authentication: generate WebAuthn options."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.email == body.email)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.credentials:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account or passkey found for this email.",
        )

    allow_credentials = [
        PublicKeyCredentialDescriptor(
            id=cred.credential_id,
            transports=json.loads(cred.transports) if cred.transports else [],
        )
        for cred in user.credentials
    ]

    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    store_challenge(body.email, options.challenge)

    return {"options": json.loads(options_to_json(options))}


@router.post("/login/complete", response_model=UserResponse)
async def login_complete(
    body: LoginCompleteRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Complete passkey authentication: verify assertion."""
    challenge = get_challenge(body.email)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Challenge expired or not found. Please start login again.",
        )

    result = await db.execute(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.email == body.email)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    # Find the matching credential
    credential_id_from_client = body.credential.get("rawId") or body.credential.get("id")
    matching_cred = None
    for cred in user.credentials:
        stored_id_b64 = base64.urlsafe_b64encode(cred.credential_id).rstrip(b"=").decode()
        if stored_id_b64 == credential_id_from_client:
            matching_cred = cred
            break

    if matching_cred is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credential not recognized.",
        )

    try:
        verification = verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=matching_cred.public_key,
            credential_current_sign_count=matching_cred.sign_count,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication verification failed: {e}",
        )

    # Update sign count to prevent replay attacks
    matching_cred.sign_count = verification.new_sign_count
    await db.flush()

    token = create_session(user.id)
    set_session_cookie(response, token)

    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
) -> None:
    """Destroy the current session."""
    token = request.cookies.get("session")
    if token:
        delete_session(token)
    response.delete_cookie(key="session")


@router.get("/me", response_model=UserResponse)
async def me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated user."""
    return UserResponse.model_validate(user)
