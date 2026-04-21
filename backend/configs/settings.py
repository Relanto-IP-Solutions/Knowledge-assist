"""Centralized settings for application and logging."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_FILES = [
    f
    for f in (
        ROOT_DIR / "configs" / ".env",
        ROOT_DIR / "configs" / "secrets" / ".env",
    )
    if f.exists()
]


class _BaseEnvSettings(BaseSettings):
    """Base settings class that reads from centralized env files."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class AppSettings(_BaseEnvSettings):
    env: Literal["development", "staging", "production", "test"] = Field(
        default="development", alias="APP_ENV"
    )
    host: str = "0.0.0.0"
    port: int = 8000
    # Comma-separated origins for browser CORS, or * for any origin (cookies/credentials
    # are then disabled per CORS spec). Example: http://localhost:5173,https://app.example.com
    cors_allow_origins: str = Field(default="*", alias="CORS_ALLOW_ORIGINS")
    # Parallel /sync/trigger workers (one DB session per source; cap to avoid pool exhaustion).
    sync_max_workers: int = Field(default=8, ge=1, le=32, alias="SYNC_MAX_WORKERS")
    # Default URL for dashboard redirects if return_url is missing.
    dashboard_url: str = Field(
        default="http://localhost:3000/dashboard", alias="FRONTEND_DASHBOARD_URL"
    )
    # SPA origin for OAuth success redirects (e.g. /projects/{oid}?provider=drive).
    frontend_app_url: str = Field(
        default="http://localhost:5173",
        alias="FRONTEND_APP_URL",
    )


class LoggingSettings(_BaseEnvSettings):
    directory: str = Field(default="logs", alias="LOG_DIRECTORY")
    name: str = Field(default="app.log", alias="LOG_NAME")
    max_bytes: int = Field(default=10**9, alias="LOG_MAX_BYTES")
    level: str = Field(default="INFO", alias="LOG_LEVEL")
    backup_count: int = Field(default=5, alias="LOG_BACKUP_COUNT")


class LLMSettings(_BaseEnvSettings):
    """Vertex AI / Gemini settings used by the generic LLM service."""

    vertex_ai_location: str = Field(default="us-central1", alias="VERTEX_AI_LOCATION")
    llm_model_name: str = Field(default="gemini-2.5-flash", alias="LLM_MODEL_NAME")


class IngestionSettings(_BaseEnvSettings):
    """GCP settings for ingestion (bucket, project). Files are uploaded directly to GCS raw/."""

    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    gcs_bucket_ingestion: str = Field(default="", alias="GCS_BUCKET_INGESTION")
    google_application_credentials: str = Field(
        default="", alias="GOOGLE_APPLICATION_CREDENTIALS"
    )
    document_ai_processor_name: str = Field(
        default="", alias="DOCUMENT_AI_PROCESSOR_NAME"
    )
    document_ai_credentials_path: str = Field(
        default="", alias="DOCUMENT_AI_CREDENTIALS_PATH"
    )
    pubsub_topic_rag_ingestion: str = Field(
        default="rag-ingestion-queue", alias="PUBSUB_TOPIC_RAG_INGESTION"
    )
    pubsub_dispatch_url: str = Field(
        default="",
        alias="PUBSUB_DISPATCH_URL",
        description="Cloud Run URL of pubsub-dispatch for document_deleted notify after orphan GCS deletes.",
    )
    gemini_extraction_batch_size: int = Field(
        default=15, alias="GEMINI_EXTRACTION_BATCH_SIZE"
    )
    gemini_extraction_max_workers: int = Field(
        default=10, alias="GEMINI_EXTRACTION_MAX_WORKERS"
    )

    @field_validator("gcp_project_id", mode="before")
    @classmethod
    def _sanitize_gcp_project_id(cls, v: object) -> str:
        """Strip accidental shell-style '$' prefix and whitespace."""
        s = "" if v is None else str(v)
        s = s.strip()
        if s.startswith("$"):
            s = s[1:].strip()
        return s


class RetrievalSettings(_BaseEnvSettings):
    """RAG retrieval: Vector Search sources, reranking, opportunity questions DB path."""

    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    vertex_ai_location: str = Field(default="us-central1", alias="VERTEX_AI_LOCATION")
    k_per_source: int = Field(default=5, alias="K_PER_SOURCE")
    k_final: int = Field(default=3, alias="K_FINAL")
    rank_location: str = Field(default="global", alias="RANK_LOCATION")
    ranking_config_id: str = Field(
        default="default_ranking_config", alias="RANKING_CONFIG_ID"
    )
    rank_model: str = Field(default="semantic-ranker-512@latest", alias="RANK_MODEL")
    vector_sources: str = Field(default="", alias="VECTOR_SOURCES")
    vector_source_drive_public_domain: str = Field(
        default="", alias="VECTOR_SOURCE_DRIVE_PUBLIC_DOMAIN"
    )
    vector_source_drive_index_endpoint: str = Field(
        default="", alias="VECTOR_SOURCE_DRIVE_INDEX_ENDPOINT"
    )
    vector_source_drive_deployed_index_id: str = Field(
        default="", alias="VECTOR_SOURCE_DRIVE_DEPLOYED_INDEX_ID"
    )
    vector_source_zoom_public_domain: str = Field(
        default="", alias="VECTOR_SOURCE_ZOOM_PUBLIC_DOMAIN"
    )
    vector_source_zoom_index_endpoint: str = Field(
        default="", alias="VECTOR_SOURCE_ZOOM_INDEX_ENDPOINT"
    )
    vector_source_zoom_deployed_index_id: str = Field(
        default="", alias="VECTOR_SOURCE_ZOOM_DEPLOYED_INDEX_ID"
    )
    vector_source_slack_public_domain: str = Field(
        default="", alias="VECTOR_SOURCE_SLACK_PUBLIC_DOMAIN"
    )
    vector_source_slack_index_endpoint: str = Field(
        default="", alias="VECTOR_SOURCE_SLACK_INDEX_ENDPOINT"
    )
    vector_source_combined_public_domain: str = Field(
        default="", alias="VECTOR_SOURCE_COMBINED_PUBLIC_DOMAIN"
    )
    vector_source_combined_index_endpoint: str = Field(
        default="", alias="VECTOR_SOURCE_COMBINED_INDEX_ENDPOINT"
    )
    vector_source_combined_deployed_index_id: str = Field(
        default="", alias="VECTOR_SOURCE_COMBINED_DEPLOYED_INDEX_ID"
    )
    vector_source_slack_deployed_index_id: str = Field(
        default="", alias="VECTOR_SOURCE_SLACK_DEPLOYED_INDEX_ID"
    )
    pubsub_subscription_retrieval_initiation: str = Field(
        default="", alias="PUBSUB_SUBSCRIPTION_RETRIEVAL_INITIATION"
    )
    retrieval_batch_size: int = Field(default=5, alias="RETRIEVAL_BATCH_SIZE")
    similarity_min_threshold: float = Field(
        default=0.0, alias="SIMILARITY_MIN_THRESHOLD"
    )
    answer_generation_url: str = Field(default="", alias="ANSWER_GENERATION_URL")

    @field_validator("gcp_project_id", mode="before")
    @classmethod
    def _sanitize_gcp_project_id(cls, v: object) -> str:
        """Strip accidental shell-style '$' prefix and whitespace."""
        s = "" if v is None else str(v)
        s = s.strip()
        if s.startswith("$"):
            s = s[1:].strip()
        return s


class DatabaseSettings(_BaseEnvSettings):
    """PostgreSQL / Cloud SQL settings for application tables (sase_batches, sase_questions, etc.)."""

    cloudsql_instance_connection_name: str = Field(
        default="", alias="CLOUDSQL_INSTANCE_CONNECTION_NAME"
    )
    cloudsql_use_iam_auth: str = Field(default="true", alias="CLOUDSQL_USE_IAM_AUTH")
    pg_host: str = Field(default="", alias="PG_HOST")
    pg_port: int = Field(default=5432, alias="PG_PORT")
    pg_database: str = Field(default="postgres", alias="PG_DATABASE")
    pg_user: str = Field(default="", alias="PG_USER")
    pg_password: str = Field(default="", alias="PG_PASSWORD")
    pg_sslmode: str = Field(default="require", alias="PG_SSLMODE")
    pg_sslrootcert: str = Field(default="", alias="PG_SSLROOTCERT")
    pool_min_size: int = Field(default=1, alias="DB_POOL_MIN_SIZE")
    pool_max_size: int = Field(default=10, alias="DB_POOL_MAX_SIZE")


class OAuthPluginSettings(_BaseEnvSettings):
    """Google / Slack OAuth client credentials (usually in configs/secrets/.env)."""

    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_oauth_state_secret: str = Field(
        default="", alias="GOOGLE_OAUTH_STATE_SECRET"
    )
    google_oauth_state_ttl_seconds: int = Field(
        default=600, alias="GOOGLE_OAUTH_STATE_TTL_SECONDS"
    )
    slack_client_id: str = Field(default="", alias="SLACK_CLIENT_ID")
    slack_client_secret: str = Field(default="", alias="SLACK_CLIENT_SECRET")
    slack_oauth_state_secret: str = Field(default="", alias="SLACK_OAUTH_STATE_SECRET")
    slack_oauth_state_ttl_seconds: int = Field(
        default=600, alias="SLACK_OAUTH_STATE_TTL_SECONDS"
    )


class FirebaseAuthSettings(_BaseEnvSettings):
    """Firebase ID token verification (``Authorization: Bearer <Firebase ID token>``)."""

    service_account_path: str = Field(
        default="",
        alias="FIREBASE_SERVICE_ACCOUNT_PATH",
        description="Path to the Firebase service account JSON key file.",
    )
    project_id: str = Field(
        default="",
        alias="FIREBASE_PROJECT_ID",
        description=(
            "Firebase / GCP project ID (e.g. eighth-bivouac-490806-s2). If set without a "
            "service account key, ID tokens are verified using Google's public x509 keys."
        ),
    )
    email_allowlist: str = Field(
        default="",
        alias="AUTH_EMAIL_ALLOWLIST",
        description=(
            "Comma-separated allowed sign-in emails (lowercased when matched). "
            "Empty = no extra email gate (still requires a matching users row)."
        ),
    )


class AgentSettings(_BaseEnvSettings):
    """Opportunities agent: recall rounds, confidence threshold, form ID prefix."""

    max_recall_rounds: int = Field(default=2, alias="AGENT_MAX_RECALL_ROUNDS")
    low_confidence_threshold: float = Field(
        default=0.5, alias="AGENT_LOW_CONFIDENCE_THRESHOLD"
    )
    form_id_prefix: str = Field(default="SASE_FORM", alias="AGENT_FORM_ID_PREFIX")
    use_cache: bool = Field(default=True, alias="AGENT_USE_CACHE")


class ZoomSettings(_BaseEnvSettings):
    """Zoom integration settings for OAuth and webhooks."""

    account_id: str = Field(default="", alias="ZOOM_ACCOUNT_ID")
    client_id: str = Field(default="", alias="ZOOM_CLIENT_ID")
    client_secret: str = Field(default="", alias="ZOOM_CLIENT_SECRET")
    webhook_secret_token: str = Field(default="", alias="ZOOM_WEBHOOK_SECRET_TOKEN")
    zoom_connector_user_email: str = Field(
        default="", alias="ZOOM_CONNECTOR_USER_EMAIL"
    )


class SlackSettings(_BaseEnvSettings):
    """Slack connector settings (service-account bot token + optional owner mapping)."""

    # Preferred universal Slack bot token (xoxb-...) used for discovery/sync.
    bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")

    # Optional: email of the connector user for /slack/discover (lists channels with that token).
    # If empty, a first user fallback is used only for opportunity ownership assignment.
    slack_connector_user_email: str = Field(
        default="", alias="SLACK_CONNECTOR_USER_EMAIL"
    )


class DriveSettings(_BaseEnvSettings):
    """Google Drive connector settings (user OAuth)."""

    # Optional: if set, Drive sync will only search within this parent folder.
    # Example: DRIVE_ROOT_FOLDER_NAME=Requirements
    drive_root_folder_name: str = Field(default="", alias="DRIVE_ROOT_FOLDER_NAME")

    # Optional: email of the single 'connector user' to use for /drive/discover.
    # If empty, the first user with a google_refresh_token is used.
    drive_connector_user_email: str = Field(
        default="", alias="DRIVE_CONNECTOR_USER_EMAIL"
    )

    # Optional: set to 1/true if your org uses Shared Drives and the OAuth user has access.
    # Enables supportsAllDrives/includeItemsFromAllDrives for Drive API queries.
    drive_supports_all_drives: bool = Field(
        default=True, alias="DRIVE_SUPPORTS_ALL_DRIVES"
    )
    # Optional: a direct link to the Google Drive root folder used for the dashboard.
    # Example: https://drive.google.com/drive/folders/<id>
    drive_master_folder_url: str = Field(
        default="", alias="DRIVE_MASTER_FOLDER_URL"
    )


class GmailSettings(_BaseEnvSettings):
    """Gmail connector discovery (user OAuth; same google_refresh_token as Drive/Gmail sync)."""

    # Optional: mailbox to scan for /gmail/discover. If empty, falls back to DRIVE_CONNECTOR_USER_EMAIL
    # then first user with google_refresh_token.
    gmail_connector_user_email: str = Field(
        default="", alias="GMAIL_CONNECTOR_USER_EMAIL"
    )

    # Gmail search query for users.threads.list. Avoid ``subject:oid`` alone: Gmail may not
    # match subjects like "Progress Update - oid1111" (tokenization). ``oid`` matches oid1111.
    gmail_discover_query: str = Field(
        default="oid",
        alias="GMAIL_DISCOVER_QUERY",
    )

    # Cap threads scanned per discover call (pagination stops here).
    gmail_discover_max_threads: int = Field(
        default=200, alias="GMAIL_DISCOVER_MAX_THREADS"
    )


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    logging: LoggingSettings
    ingestion: IngestionSettings
    llm: LLMSettings
    retrieval: RetrievalSettings
    database: DatabaseSettings
    oauth_plugin: OAuthPluginSettings
    firebase_auth: FirebaseAuthSettings
    agent: AgentSettings
    zoom: ZoomSettings
    slack: SlackSettings
    drive: DriveSettings
    gmail: GmailSettings


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app=AppSettings(),
        logging=LoggingSettings(),
        ingestion=IngestionSettings(),
        llm=LLMSettings(),
        retrieval=RetrievalSettings(),
        database=DatabaseSettings(),
        oauth_plugin=OAuthPluginSettings(),
        firebase_auth=FirebaseAuthSettings(),
        agent=AgentSettings(),
        zoom=ZoomSettings(),
        slack=SlackSettings(),
        drive=DriveSettings(),
        gmail=GmailSettings(),
    )


# Populate ``os.environ`` from Secret Manager before first ``get_settings()`` call (so Zoom
# credentials and Cloud Run ``--set-secrets`` both work the same).
from .bootstrap_secrets import load_zoom_secrets_from_secret_manager  # noqa: E402


load_zoom_secrets_from_secret_manager()