import warnings
from unittest.mock import AsyncMock, Mock

import pytest

import chainlit.data
from chainlit.data import get_data_layer


async def test_get_data_layer(
    mock_data_layer: AsyncMock,
    mock_get_data_layer: Mock,
):
    # Check whether the data layer is properly set
    assert mock_data_layer == get_data_layer()

    mock_get_data_layer.assert_called_once()

    # Getting the data layer again, should not result in additional call
    assert mock_data_layer == get_data_layer()

    mock_get_data_layer.assert_called_once()


@pytest.fixture
def fresh_data_layer_state(monkeypatch: pytest.MonkeyPatch, test_config):
    monkeypatch.setattr(chainlit.data, "_data_layer", None)
    monkeypatch.setattr(chainlit.data, "_data_layer_initialized", False)
    monkeypatch.setattr(test_config.code, "data_layer", None)
    monkeypatch.setattr("chainlit.config.config", test_config)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LITERAL_API_KEY", raising=False)


def test_get_data_layer_literal_api_key_only_warns(
    monkeypatch: pytest.MonkeyPatch, fresh_data_layer_state
):
    monkeypatch.setenv("LITERAL_API_KEY", "lit-key")

    with pytest.warns(UserWarning, match="LiteralAI data layer has been removed"):
        assert get_data_layer() is None


def test_get_data_layer_no_env_returns_none_without_warning(
    fresh_data_layer_state,
):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert get_data_layer() is None
