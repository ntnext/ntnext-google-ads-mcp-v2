"""Google Ads SDK client for MCP server."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Generator, Optional

from fastmcp.server.dependencies import get_access_token
from google.ads.googleads.client import GoogleAdsClient
from google.oauth2.credentials import Credentials

from src.utils import get_logger

logger = get_logger(__name__)

# If this path exists, it is loaded via the SDK's YAML loader (same format as
# ~/google-ads.yaml). Otherwise configuration is read from environment
# variables GOOGLE_ADS_* (see google.ads.googleads.config.load_from_env).
_DEFAULT_CONFIG_PATH = "./env/google-ads.yaml"

# Manager account to send as the login-customer-id header for the current tool
# call. Set by tools that accept a ``login_customer_id`` argument.
_login_customer_id: ContextVar[Optional[str]] = ContextVar(
    "login_customer_id", default=None
)


@contextmanager
def use_login_customer_id(
    login_customer_id: Optional[str],
) -> Generator[None, None, None]:
    """Send ``login_customer_id`` as the login-customer-id header inside the block."""
    value = login_customer_id.replace("-", "") if login_customer_id else None
    token = _login_customer_id.set(value)
    try:
        yield
    finally:
        _login_customer_id.reset(token)


class GoogleAdsSdkClient:
    """SDK client for Google Ads.

    Two modes:

    * Shared credentials (stdio / local use). Configuration resolution order:
      1. If ``config_path`` points to an existing file, that YAML is loaded
         (``GoogleAdsClient.load_from_storage``).
      2. Otherwise ``GoogleAdsClient.load_from_env()`` is used. After
         ``load_dotenv()`` in ``main.py``, variables from ``.env`` are visible
         here. You may also set ``GOOGLE_ADS_CONFIGURATION_FILE_PATH`` to a YAML
         file path; the SDK then loads that file instead of inline env keys.
    * Per-user credentials (``per_user=True``, hosted HTTP deploys). Every call
      builds a client from the logged-in user's Google OAuth token, so users
      only see the accounts their own Google Ads access allows. Only the
      developer token (``GOOGLE_ADS_DEVELOPER_TOKEN``) is shared.
    """

    def __init__(
        self,
        config_path: Optional[str] = _DEFAULT_CONFIG_PATH,
        per_user: bool = False,
    ):
        self.config_path = config_path
        self.per_user = per_user
        self._client: Optional[GoogleAdsClient] = None
        self._default_login_customer_id: Optional[str] = None

    def _build_client(self) -> GoogleAdsClient:
        if self.config_path:
            path = Path(self.config_path)
            if path.is_file():
                resolved = str(path.resolve())
                logger.info("Google Ads config: YAML file %s", resolved)
                client = GoogleAdsClient.load_from_storage(resolved)
                logger.info("login_customer_id=%s", client.login_customer_id)
                return client

        logger.info("Google Ads config: environment (GOOGLE_ADS_*)")
        client = GoogleAdsClient.load_from_env()
        logger.info("login_customer_id=%s", client.login_customer_id)
        return client

    def _build_user_client(self) -> GoogleAdsClient:
        access_token = get_access_token()
        if access_token is None or not access_token.token:
            # Never fall back to shared credentials in per-user mode
            raise RuntimeError("No logged-in user: Google Ads calls need a login")

        return GoogleAdsClient(
            # The SDK annotates this as a dict, but it expects a Credentials object
            credentials=Credentials(token=access_token.token),  # pyright: ignore[reportArgumentType]
            developer_token=os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            login_customer_id=_login_customer_id.get(),
            use_proto_plus=True,
        )

    @property
    def client(self) -> GoogleAdsClient:
        """Get the Google Ads client for the current call."""
        if self.per_user:
            return self._build_user_client()

        if self._client is None:
            self._client = self._build_client()
            self._default_login_customer_id = self._client.login_customer_id
            logger.info("Google Ads SDK client initialized successfully")

        # A tool's login_customer_id overrides the configured one for that call only
        self._client.login_customer_id = (
            _login_customer_id.get() or self._default_login_customer_id
        )
        return self._client

    def validate(self) -> None:
        """Verify the configuration at startup.

        With shared credentials, calls ``list_accessible_customers`` which is
        lightweight, free, and proves that the OAuth / service-account token is
        valid. In per-user mode there is no user yet, so only the developer
        token is checked.
        """
        if self.per_user:
            if not os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN"):
                logger.error("GOOGLE_ADS_DEVELOPER_TOKEN is not set")
                raise RuntimeError("GOOGLE_ADS_DEVELOPER_TOKEN is not set")
            logger.info("Per-user Google Ads credentials enabled")
            return

        try:
            customer_service = self.client.get_service("CustomerService", version="v23")
            customer_service.list_accessible_customers()
            logger.info("Credential validation passed")
        except Exception:
            logger.error("Credential validation FAILED – check your config")
            raise

    def close(self) -> None:
        """Close the client and clean up resources."""
        if self._client:
            self._client = None
            logger.info("Google Ads SDK client closed")


# Global client instance
_sdk_client: Optional[GoogleAdsSdkClient] = None


def get_sdk_client() -> GoogleAdsSdkClient:
    """Get the global SDK client instance."""
    global _sdk_client
    if _sdk_client is None:
        raise RuntimeError("SDK client not initialized. Call set_sdk_client first.")
    return _sdk_client


def set_sdk_client(client: GoogleAdsSdkClient) -> None:
    """Set the global SDK client instance."""
    global _sdk_client
    _sdk_client = client
