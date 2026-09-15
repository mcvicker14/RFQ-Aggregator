from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.contact import Contact, OpportunityContact
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate, OpportunityContactCreate, OpportunityContactRead

router = APIRouter(tags=["contacts"])


@router.get("/api/contacts", response_model=list[ContactRead])
def list_contacts(db: Session = Depends(get_db), _current: User = Depends(get_current_user), q: str | None = Query(None)):
    stmt = select(Contact)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Contact.full_name.ilike(like), Contact.organization.ilike(like), Contact.email.ilike(like)))
    return db.execute(stmt.order_by(Contact.full_name)).scalars().all()


@router.post("/api/contacts", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    contact = Contact(**payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/api/contacts/{contact_id}", response_model=ContactRead)
def get_contact(contact_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return contact


@router.patch("/api/contacts/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: UUID, payload: ContactUpdate, db: Session = Depends(get_db), _current: User = Depends(get_current_user)
):
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field_name, value)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/api/opportunities/{opportunity_id}/contacts", response_model=list[OpportunityContactRead])
def list_opportunity_contacts(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(
        select(OpportunityContact).where(OpportunityContact.opportunity_id == opportunity_id)
    ).scalars().all()


@router.post(
    "/api/opportunities/{opportunity_id}/contacts",
    response_model=OpportunityContactRead,
    status_code=status.HTTP_201_CREATED,
)
def link_contact_to_opportunity(
    opportunity_id: UUID, payload: OpportunityContactCreate, db: Session = Depends(get_db), _current: User = Depends(get_current_user)
):
    if db.get(Contact, payload.contact_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    link = OpportunityContact(opportunity_id=opportunity_id, **payload.model_dump())
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.delete("/api/opportunity-contacts/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_contact(link_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    link = db.get(OpportunityContact, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    db.delete(link)
    db.commit()
