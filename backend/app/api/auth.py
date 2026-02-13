"""Authentication API routes: WebAuthn register, login, logout, and current user."""

import base64
import json
import logging
import secrets

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
from app.core.rate_limit import check_rate_limit
from app.database import get_db
from app.models.user import User
from app.models.user_credential import UserCredential
from app.schemas.auth import (
    EmailRequest,
    LoginCompleteRequest,
    RegisterCompleteRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register/begin")
async def register_begin(
    body: EmailRequest,
    _rate_limit: None = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Begin passkey registration: generate WebAuthn options."""
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
        await db.commit()
        await db.refresh(user, attribute_names=["id", "credentials"])

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
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )

    store_challenge(body.email, options.challenge)

    return {"options": json.loads(options_to_json(options))}


@router.post("/register/complete", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_complete(
    body: RegisterCompleteRequest,
    response: Response,
    _rate_limit: None = Depends(check_rate_limit),
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
        logger.warning("Registration verification failed for %s: %s", body.email, e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration verification failed. Please try again.",
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found. Please start registration again.",
        )

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
    await db.commit()

    token = create_session(user.id)
    set_session_cookie(response, token)

    return UserResponse.model_validate(user)


@router.post("/login/begin")
async def login_begin(
    _rate_limit: None = Depends(check_rate_limit),
) -> dict:
    """Begin passkey authentication with discoverable credentials (no email needed)."""
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    challenge_id = secrets.token_urlsafe(32)
    store_challenge(challenge_id, options.challenge)

    return {
        "challenge_id": challenge_id,
        "options": json.loads(options_to_json(options)),
    }


@router.post("/login/complete", response_model=UserResponse)
async def login_complete(
    body: LoginCompleteRequest,
    response: Response,
    _rate_limit: None = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Complete passkey authentication: verify assertion using discoverable credential."""
    challenge = get_challenge(body.challenge_id)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Challenge expired or not found. Please try again.",
        )

    # Find the credential by credential ID from the client response
    credential_id_b64 = body.credential.get("rawId") or body.credential.get("id")
    if not credential_id_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing credential ID.",
        )

    # Decode the base64url credential ID to bytes for DB lookup
    padded = credential_id_b64 + "=" * (-len(credential_id_b64) % 4)
    credential_id_bytes = base64.urlsafe_b64decode(padded)

    result = await db.execute(
        select(UserCredential).where(UserCredential.credential_id == credential_id_bytes)
    )
    stored_cred = result.scalar_one_or_none()
    if stored_cred is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credential not recognized.",
        )

    # Load the user
    user_result = await db.execute(select(User).where(User.id == stored_cred.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    try:
        verification = verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=stored_cred.public_key,
            credential_current_sign_count=stored_cred.sign_count,
        )
    except Exception as e:
        logger.warning("Authentication verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )

    # Validate sign count to detect cloned authenticators
    # Skip check when both are 0 (some authenticators don't track sign count)
    if not (verification.new_sign_count == 0 and stored_cred.sign_count == 0):
        if verification.new_sign_count <= stored_cred.sign_count:
            logger.warning(
                "Sign count regression for credential %s: got %d, expected > %d",
                stored_cred.id, verification.new_sign_count, stored_cred.sign_count,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed.",
            )
    stored_cred.sign_count = verification.new_sign_count
    await db.flush()
    await db.commit()

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


@router.post("/test-login", response_model=UserResponse)
async def test_login(
    body: EmailRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Login as any user without WebAuthn. Only available when TEST_MODE=true."""
    if not settings.TEST_MODE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=body.email)
        db.add(user)
        await db.flush()
        await db.commit()
        await db.refresh(user, attribute_names=["id"])

    token = create_session(user.id)
    set_session_cookie(response, token)

    return UserResponse.model_validate(user)
