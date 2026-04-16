from sqlalchemy import Boolean, JSON, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from src.services.database_manager.orm import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="true")
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

    opportunities = relationship("Opportunity", back_populates="team")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Firebase Auth user id (stable across logins). Used for ACL lookup.
    firebase_uid = Column(String, nullable=True, index=True)

    # Multi-role RBAC (nullable).
    roles_assigned = Column(ARRAY(String), nullable=True)

    # Firebase Auth user id (stable across logins). Used for ACL lookup.
    firebase_uid = Column(String, nullable=True, index=True)

    # Multi-role RBAC (nullable).
    roles_assigned = Column(ARRAY(String), nullable=True)

    # Deprecated: Google OAuth tokens live in ``user_connections`` (provider ``google``).
    google_refresh_token = Column(Text, nullable=True)

    # Store Slack OAuth tokens
    slack_access_token = Column(Text, nullable=True)

    # Store Zoom App credentials if users bring their own app (generalized)
    # If using a single global app, these can remain null and fall back to env vars.
    zoom_account_id = Column(String, nullable=True)
    zoom_client_id = Column(String, nullable=True)
    zoom_client_secret = Column(Text, nullable=True)

    opportunities = relationship("Opportunity", back_populates="owner")
    connections = relationship("UserConnection", back_populates="user")


class UserConnection(Base):
    __tablename__ = "user_connections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    granted_scopes = Column(JSON, nullable=True)
    status = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="connections")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(
        String, unique=True, index=True, nullable=False
    )  # Example: oid1023
    name = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Pipeline / UI state (updated by discover, sync, ingestion, answer-generation)
    status = Column(String(64), nullable=True)
    total_documents = Column(Integer, nullable=False, server_default="0")
    processed_documents = Column(Integer, nullable=False, server_default="0")
    last_extraction_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="opportunities")
    team = relationship("Team", back_populates="opportunities")
    sources = relationship(
        "OpportunitySource", back_populates="opportunity", cascade="all, delete-orphan"
    )


class OpportunitySource(Base):
    __tablename__ = "opportunity_sources"

    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    source_type = Column(
        String, nullable=False
    )  # e.g., "slack", "gmail", "zoom", "drive"

    # Last synced tracker for generic plugins
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    # Checkpoints for incremental fetch (e.g. slack cursor timestamp, max email date, etc.)
    sync_checkpoint = Column(Text, nullable=True)
    status = Column(
        String(64), nullable=False, server_default="PENDING_AUTHORIZATION"
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    opportunity = relationship("Opportunity", back_populates="sources")
