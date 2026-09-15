from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

# Roles ranked for "at least this seniority" checks (spec §21 / docs/SECURITY.md).
# Higher number = broader edit rights. Administrator/Executive/BD sit above
# PM/Proposal Manager/Viewer for the purposes of the "BD+" role gate used across
# most mutating endpoints; PM/Proposal Manager get their own narrower checks where
# the route only allows editing an opportunity's own/assigned fields.
_ROLE_RANK = {
    UserRole.VIEWER: 0,
    UserRole.PROJECT_MANAGER: 1,
    UserRole.PROPOSAL_MANAGER: 1,
    UserRole.BUSINESS_DEVELOPMENT: 2,
    UserRole.EXECUTIVE: 3,
    UserRole.ADMINISTRATOR: 4,
}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_role(*allowed: UserRole) -> Callable[[User], User]:
    """Exact-role allowlist, for actions restricted to specific roles (e.g. only
    Administrator can manage users)."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action")
        return user

    return checker


def require_min_rank(minimum: UserRole) -> Callable[[User], User]:
    """'At least as senior as' check using _ROLE_RANK, for the common 'BD and above'
    gate on mutating opportunity/pipeline endpoints."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if _ROLE_RANK[user.role] < _ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action")
        return user

    return checker


require_admin = require_role(UserRole.ADMINISTRATOR)
require_decision_maker = require_role(UserRole.ADMINISTRATOR, UserRole.EXECUTIVE)
require_bd_or_above = require_min_rank(UserRole.BUSINESS_DEVELOPMENT)
