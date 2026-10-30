"""Tests for GoogleAdsSdkClient configuration resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.sdk_client import GoogleAdsSdkClient, use_login_customer_id


@pytest.fixture
def mock_google_ads_client() -> MagicMock:
    return MagicMock()


def test_uses_load_from_storage_when_yaml_exists(
    tmp_path: Path, mock_google_ads_client: MagicMock
) -> None:
    cfg = tmp_path / "google-ads.yaml"
    cfg.write_text(
        "developer_token: t\n"
        "use_proto_plus: true\n"
        "client_id: x\n"
        "client_secret: y\n"
        "refresh_token: z\n",
        encoding="utf-8",
    )
    with patch(
        "src.sdk_client.GoogleAdsClient.load_from_storage",
        return_value=mock_google_ads_client,
    ) as load_storage:
        with patch("src.sdk_client.GoogleAdsClient.load_from_env") as load_env:
            client = GoogleAdsSdkClient(config_path=str(cfg))
            assert client.client is mock_google_ads_client
            load_storage.assert_called_once()
            load_env.assert_not_called()


def test_uses_load_from_env_when_yaml_missing(
    mock_google_ads_client: MagicMock,
) -> None:
    with patch("src.sdk_client.GoogleAdsClient.load_from_storage") as load_storage:
        with patch(
            "src.sdk_client.GoogleAdsClient.load_from_env",
            return_value=mock_google_ads_client,
        ) as load_env:
            client = GoogleAdsSdkClient(config_path="/nonexistent/google-ads.yaml")
            assert client.client is mock_google_ads_client
            load_storage.assert_not_called()
            load_env.assert_called_once()


def test_close_clears_client(mock_google_ads_client: MagicMock) -> None:
    with patch(
        "src.sdk_client.GoogleAdsClient.load_from_env",
        return_value=mock_google_ads_client,
    ) as load_env:
        client = GoogleAdsSdkClient(config_path="/nonexistent/google-ads.yaml")
        _ = client.client
        client.close()
        _ = client.client
        assert load_env.call_count == 2


def _user_token(token: str) -> MagicMock:
    access_token = MagicMock()
    access_token.token = token
    return access_token


def test_per_user_builds_client_from_user_token() -> None:
    with (
        patch.dict("os.environ", {"GOOGLE_ADS_DEVELOPER_TOKEN": "dev"}),
        patch("src.sdk_client.get_access_token", return_value=_user_token("user-a")),
        patch("src.sdk_client.GoogleAdsClient") as ads_client,
    ):
        GoogleAdsSdkClient(per_user=True).client

    kwargs = ads_client.call_args.kwargs
    assert kwargs["credentials"].token == "user-a"
    assert kwargs["developer_token"] == "dev"
    assert kwargs["login_customer_id"] is None
    ads_client.load_from_env.assert_not_called()


def test_per_user_uses_each_callers_token() -> None:
    sdk_client = GoogleAdsSdkClient(per_user=True)
    with (
        patch.dict("os.environ", {"GOOGLE_ADS_DEVELOPER_TOKEN": "dev"}),
        patch("src.sdk_client.get_access_token") as get_access_token,
        patch("src.sdk_client.GoogleAdsClient") as ads_client,
    ):
        get_access_token.return_value = _user_token("user-a")
        sdk_client.client
        get_access_token.return_value = _user_token("user-b")
        sdk_client.client

    tokens = [c.kwargs["credentials"].token for c in ads_client.call_args_list]
    assert tokens == ["user-a", "user-b"]


def test_per_user_without_login_never_uses_shared_credentials() -> None:
    with (
        patch("src.sdk_client.get_access_token", return_value=None),
        patch("src.sdk_client.GoogleAdsClient") as ads_client,
    ):
        with pytest.raises(RuntimeError):
            GoogleAdsSdkClient(per_user=True).client
    ads_client.assert_not_called()
    ads_client.load_from_env.assert_not_called()


def test_per_user_sends_login_customer_id_only_inside_block() -> None:
    sdk_client = GoogleAdsSdkClient(per_user=True)
    with (
        patch.dict("os.environ", {"GOOGLE_ADS_DEVELOPER_TOKEN": "dev"}),
        patch("src.sdk_client.get_access_token", return_value=_user_token("user-a")),
        patch("src.sdk_client.GoogleAdsClient") as ads_client,
    ):
        with use_login_customer_id("574-925-4657"):
            sdk_client.client
        sdk_client.client

    ids = [c.kwargs["login_customer_id"] for c in ads_client.call_args_list]
    assert ids == ["5749254657", None]


def test_shared_login_customer_id_override_is_per_call(
    mock_google_ads_client: MagicMock,
) -> None:
    mock_google_ads_client.login_customer_id = "1111111111"
    with patch(
        "src.sdk_client.GoogleAdsClient.load_from_env",
        return_value=mock_google_ads_client,
    ):
        sdk_client = GoogleAdsSdkClient(config_path="/nonexistent/google-ads.yaml")
        with use_login_customer_id("2222222222"):
            assert sdk_client.client.login_customer_id == "2222222222"
        assert sdk_client.client.login_customer_id == "1111111111"


def test_per_user_validate_checks_developer_token_only() -> None:
    with (
        patch.dict("os.environ", {"GOOGLE_ADS_DEVELOPER_TOKEN": ""}),
        patch("src.sdk_client.GoogleAdsClient") as ads_client,
    ):
        with pytest.raises(RuntimeError):
            GoogleAdsSdkClient(per_user=True).validate()
    with (
        patch.dict("os.environ", {"GOOGLE_ADS_DEVELOPER_TOKEN": "dev"}),
        patch("src.sdk_client.GoogleAdsClient") as ads_client,
    ):
        GoogleAdsSdkClient(per_user=True).validate()
    ads_client.assert_not_called()
