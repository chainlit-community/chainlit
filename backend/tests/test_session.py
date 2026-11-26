import builtins
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from chainlit.session import (
    BaseSession,
    HTTPSession,
    JSONEncoderIgnoreNonSerializable,
    McpSession,
    WebsocketSession,
    clean_metadata,
    is_valid_session_id,
    parse_accept_language,
    resolve_session_config,
    select_chat_profile,
)


def make_exception_group(message: str, exceptions: list[BaseException]):
    base_exception_group = getattr(builtins, "BaseExceptionGroup", None)
    if base_exception_group is None:
        pytest.skip("BaseExceptionGroup is unavailable on this Python version")
    return base_exception_group(message, exceptions)  # type: ignore[misc]


class TestJSONEncoderIgnoreNonSerializable:
    """Test suite for JSONEncoderIgnoreNonSerializable."""

    def test_encoder_handles_serializable_objects(self):
        """Test that encoder handles normal serializable objects."""
        data = {
            "string": "value",
            "number": 42,
            "list": [1, 2, 3],
            "dict": {"key": "value"},
        }
        result = json.dumps(data, cls=JSONEncoderIgnoreNonSerializable)
        assert json.loads(result) == data

    def test_encoder_ignores_non_serializable_objects(self):
        """Test that encoder returns None for non-serializable objects."""

        class NonSerializable:
            pass

        data = {"normal": "value", "non_serializable": NonSerializable()}
        result = json.dumps(data, cls=JSONEncoderIgnoreNonSerializable)
        parsed = json.loads(result)

        assert parsed["normal"] == "value"
        assert parsed["non_serializable"] is None

    def test_encoder_with_nested_non_serializable(self):
        """Test encoder with nested non-serializable objects."""

        class NonSerializable:
            pass

        data = {
            "level1": {
                "level2": {
                    "serializable": "value",
                    "non_serializable": NonSerializable(),
                }
            }
        }
        result = json.dumps(data, cls=JSONEncoderIgnoreNonSerializable)
        parsed = json.loads(result)

        assert parsed["level1"]["level2"]["serializable"] == "value"
        assert parsed["level1"]["level2"]["non_serializable"] is None


class TestCleanMetadata:
    """Test suite for clean_metadata function."""

    def test_clean_metadata_with_normal_data(self):
        """Test clean_metadata with normal serializable data."""
        metadata = {"key": "value", "number": 42, "list": [1, 2, 3]}
        result = clean_metadata(metadata)
        assert result == metadata

    def test_clean_metadata_removes_non_serializable(self):
        """Test that clean_metadata removes non-serializable objects."""

        class NonSerializable:
            pass

        metadata = {"normal": "value", "non_serializable": NonSerializable()}
        result = clean_metadata(metadata)

        assert result["normal"] == "value"
        assert result["non_serializable"] is None

    def test_clean_metadata_redacts_large_data(self):
        """Test that clean_metadata redacts data exceeding max size."""
        # Create large metadata
        large_data = {"data": "x" * 2000000}  # > 1MB
        result = clean_metadata(large_data, max_size=1048576)

        assert "message" in result
        assert "exceeds the limit" in result["message"]

    def test_clean_metadata_with_custom_max_size(self):
        """Test clean_metadata with custom max size."""
        small_data = {"data": "x" * 100}
        result = clean_metadata(small_data, max_size=50)

        # Should be redacted because it exceeds 50 bytes
        assert "message" in result
        assert "exceeds the limit" in result["message"]

    def test_clean_metadata_preserves_unicode(self):
        """Test that clean_metadata preserves Unicode characters."""
        metadata = {"chinese": "你好", "emoji": "🎉", "japanese": "こんにちは"}
        result = clean_metadata(metadata)

        assert result["chinese"] == "你好"
        assert result["emoji"] == "🎉"
        assert result["japanese"] == "こんにちは"


class TestBaseSession:
    """Test suite for BaseSession class."""

    def test_base_session_initialization(self):
        """Test BaseSession initialization with required parameters."""
        session = BaseSession(
            id="test_id",
            client_type="webapp",
            thread_id=None,
            user=None,
            token=None,
            user_env=None,
        )

        assert session.id == "test_id"
        assert session.client_type == "webapp"
        assert session.thread_id is not None  # Auto-generated UUID
        assert session.user is None
        assert session.token is None
        assert session.user_env == {}
        assert session.chat_settings == {}

    def test_base_session_with_thread_id(self):
        """Test BaseSession with provided thread_id."""
        thread_id = str(uuid.uuid4())
        session = BaseSession(
            id="test_id",
            client_type="webapp",
            thread_id=thread_id,
            user=None,
            token=None,
            user_env=None,
        )

        assert session.thread_id == thread_id
        assert session.thread_id_to_resume == thread_id

    def test_base_session_with_user_env(self):
        """Test BaseSession with user environment variables."""
        user_env = {"API_KEY": "secret", "ENV_VAR": "value"}
        session = BaseSession(
            id="test_id",
            client_type="webapp",
            thread_id=None,
            user=None,
            token=None,
            user_env=user_env,
        )

        assert session.user_env == user_env

    def test_base_session_with_chat_profile(self):
        """Test BaseSession with chat profile."""
        session = BaseSession(
            id="test_id",
            client_type="webapp",
            thread_id=None,
            user=None,
            token=None,
            user_env=None,
            chat_profile="gpt-4",
        )

        assert session.chat_profile == "gpt-4"

    @pytest.mark.parametrize(
        "session_id",
        ["../outside", "..", "/etc", "a/b", "a\\b", "", ".", "x" * 129, "abc\n"],
    )
    def test_base_session_files_dir_rejects_unsafe_id(
        self, session_id, monkeypatch, tmp_path
    ):
        """A session id must not be able to escape FILES_DIRECTORY."""
        monkeypatch.setattr("chainlit.config.FILES_DIRECTORY", tmp_path)
        session = BaseSession(
            id=session_id,
            client_type="webapp",
            thread_id=None,
            user=None,
            token=None,
            user_env=None,
        )

        with pytest.raises(ValueError, match="Invalid session id"):
            _ = session.files_dir

    @pytest.mark.parametrize(
        ("session_id", "expected"),
        [
            (str(uuid.uuid4()), True),
            ("a_b-C9", True),
            ("x" * 128, True),
            (None, False),
            (123, False),
            (b"abc", False),
        ],
    )
    def test_is_valid_session_id(self, session_id, expected):
        """The allowlist accepts UUID-like ids and rejects non-strings."""
        assert is_valid_session_id(session_id) is expected

    def test_base_session_files_dir(self):
        """Test BaseSession files_dir property."""
        with patch("chainlit.config.FILES_DIRECTORY", Path("/tmp/files")):
            session = BaseSession(
                id="test_id",
                client_type="webapp",
                thread_id=None,
                user=None,
                token=None,
                user_env=None,
            )

            assert session.files_dir == Path("/tmp/files/test_id")

    @pytest.mark.asyncio
    async def test_base_session_persist_file_with_content(self):
        """Test persisting a file with content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chainlit.config.FILES_DIRECTORY", Path(tmpdir)):
                session = BaseSession(
                    id="test_id",
                    client_type="webapp",
                    thread_id=None,
                    user=None,
                    token=None,
                    user_env=None,
                )

                content = b"test file content"
                result = await session.persist_file(
                    name="test.txt",
                    mime="text/plain",
                    content=content,
                )

                assert "id" in result
                assert result["id"] in session.files
                assert session.files[result["id"]]["name"] == "test.txt"
                assert session.files[result["id"]]["type"] == "text/plain"

    @pytest.mark.asyncio
    async def test_base_session_persist_file_with_string_content(self):
        """Test persisting a file with string content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chainlit.config.FILES_DIRECTORY", Path(tmpdir)):
                session = BaseSession(
                    id="test_id",
                    client_type="webapp",
                    thread_id=None,
                    user=None,
                    token=None,
                    user_env=None,
                )

                content = "test string content"
                result = await session.persist_file(
                    name="test.txt",
                    mime="text/plain",
                    content=content,
                )

                assert "id" in result
                file_id = result["id"]
                assert session.files[file_id]["size"] > 0

    @pytest.mark.asyncio
    async def test_base_session_persist_file_without_path_or_content(self):
        """Test that persist_file raises error without path or content."""
        session = BaseSession(
            id="test_id",
            client_type="webapp",
            thread_id=None,
            user=None,
            token=None,
            user_env=None,
        )

        with pytest.raises(ValueError, match="Either path or content must be provided"):
            await session.persist_file(name="test.txt", mime="text/plain")

    def test_base_session_to_persistable(self):
        """Test BaseSession to_persistable method."""
        from chainlit.user_session import user_sessions

        original_sessions = user_sessions.copy()
        user_sessions.update({"test_id": {"key": "value"}})

        try:
            with patch("chainlit.config.config") as mock_config:
                mock_config.project.persist_user_env = True

                session = BaseSession(
                    id="test_id",
                    client_type="webapp",
                    thread_id=None,
                    user=None,
                    token=None,
                    user_env={"API_KEY": "secret"},
                    chat_profile="gpt-4",
                )
                session.chat_settings = {"temperature": 0.7}

                result = session.to_persistable()

                assert result["chat_settings"] == {"temperature": 0.7}
                assert result["chat_profile"] == "gpt-4"
                assert result["client_type"] == "webapp"
        finally:
            user_sessions.clear()
            user_sessions.update(original_sessions)

    def test_base_session_to_persistable_without_persist_user_env(self):
        """Test to_persistable removes user_env when persist_user_env is False."""
        from chainlit.user_session import user_sessions

        original_sessions = user_sessions.copy()
        user_sessions.update({"test_id": {"env": {"KEY": "value"}}})

        try:
            with patch("chainlit.config.config") as mock_config:
                mock_config.project.persist_user_env = False

                session = BaseSession(
                    id="test_id",
                    client_type="webapp",
                    thread_id=None,
                    user=None,
                    token=None,
                    user_env={"API_KEY": "secret"},
                )

                result = session.to_persistable()

                assert result["env"] == {}
        finally:
            user_sessions.clear()
            user_sessions.update(original_sessions)


class TestHTTPSession:
    """Test suite for HTTPSession class."""

    def test_http_session_initialization(self):
        """Test HTTPSession initialization."""
        session = HTTPSession(
            id="http_id",
            client_type="copilot",
            thread_id=None,
            user=None,
            token=None,
            user_env=None,
        )

        assert session.id == "http_id"
        assert session.client_type == "copilot"
        assert isinstance(session, BaseSession)

    @pytest.mark.asyncio
    async def test_http_session_delete(self):
        """Test HTTPSession delete method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chainlit.config.FILES_DIRECTORY", Path(tmpdir)):
                session = HTTPSession(
                    id="http_id",
                    client_type="copilot",
                )

                # Create files directory
                session.files_dir.mkdir(exist_ok=True)
                test_file = session.files_dir / "test.txt"
                test_file.write_text("test")

                assert session.files_dir.exists()

                await session.delete()

                assert not session.files_dir.exists()


class TestWebsocketSession:
    """Test suite for WebsocketSession class."""

    def test_websocket_session_initialization(self):
        """Test WebsocketSession initialization."""
        emit_mock = Mock()
        emit_call_mock = Mock()

        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=emit_mock,
            emit_call=emit_call_mock,
            user_env={},
            client_type="webapp",
        )

        assert session.id == "ws_id"
        assert session.socket_id == "socket_123"
        assert session.emit == emit_mock
        assert session.emit_call == emit_call_mock
        assert session.restored is False
        assert session.mcp_sessions == {}

    def test_websocket_session_language_detection(self):
        """Test WebsocketSession language detection from HTTP headers."""
        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
            environ={"HTTP_ACCEPT_LANGUAGE": "fr-FR,fr;q=0.9,en;q=0.8"},
        )

        assert session.language == "fr-FR"

    def test_websocket_session_default_language(self):
        """Test WebsocketSession defaults to en-US without language header."""
        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
            environ={},
        )

        assert session.language == "en-US"

    def test_websocket_session_restore(self):
        """Test WebsocketSession restore method."""
        from chainlit.session import ws_sessions_sid

        session = WebsocketSession(
            id="ws_id",
            socket_id="old_socket",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
        )

        assert ws_sessions_sid.get("old_socket") == session

        session.restore("new_socket")

        assert session.socket_id == "new_socket"
        assert session.restored is True
        assert ws_sessions_sid.get("old_socket") is None
        assert ws_sessions_sid.get("new_socket") == session

    @pytest.mark.asyncio
    async def test_websocket_session_delete(self):
        """Test WebsocketSession delete method."""
        from chainlit.session import ws_sessions_id, ws_sessions_sid

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chainlit.config.FILES_DIRECTORY", Path(tmpdir)):
                session = WebsocketSession(
                    id="ws_id",
                    socket_id="socket_123",
                    emit=Mock(),
                    emit_call=Mock(),
                    user_env={},
                    client_type="webapp",
                )

                # Create files directory
                session.files_dir.mkdir(exist_ok=True)

                assert ws_sessions_sid.get("socket_123") == session
                assert ws_sessions_id.get("ws_id") == session

                await session.delete()

                assert not session.files_dir.exists()
                assert ws_sessions_sid.get("socket_123") is None
                assert ws_sessions_id.get("ws_id") is None

    def test_websocket_session_get(self):
        """Test WebsocketSession.get class method."""
        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
        )

        retrieved = WebsocketSession.get("socket_123")
        assert retrieved == session

    def test_websocket_session_get_by_id(self):
        """Test WebsocketSession.get_by_id class method."""
        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
        )

        retrieved = WebsocketSession.get_by_id("ws_id")
        assert retrieved == session

    def test_websocket_session_require_success(self):
        """Test WebsocketSession.require with existing session."""
        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
        )

        retrieved = WebsocketSession.require("socket_123")
        assert retrieved == session

    def test_websocket_session_require_failure(self):
        """Test WebsocketSession.require raises error for missing session."""
        with pytest.raises(ValueError, match="Session not found"):
            WebsocketSession.require("nonexistent_socket")

    @pytest.mark.asyncio
    async def test_websocket_session_flush_method_queue(self):
        """Test WebsocketSession flush_method_queue."""
        from collections import deque

        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
        )

        # Create a mock async method
        mock_method = AsyncMock()

        # Add items to queue
        session.thread_queues["test_method"] = deque(
            [
                (mock_method, session, ("arg1",), {"kwarg1": "value1"}),
                (mock_method, session, ("arg2",), {"kwarg2": "value2"}),
            ]
        )

        await session.flush_method_queue()

        assert mock_method.call_count == 2
        assert len(session.thread_queues["test_method"]) == 0


class TestSessionEdgeCases:
    """Test suite for session edge cases."""

    def test_base_session_with_all_client_types(self):
        """Test BaseSession with different client types."""
        client_types = ["webapp", "copilot", "teams", "slack", "discord"]

        for client_type in client_types:
            session = BaseSession(
                id=f"test_{client_type}",
                client_type=client_type,
                thread_id=None,
                user=None,
                token=None,
                user_env=None,
            )
            assert session.client_type == client_type

    @pytest.mark.asyncio
    async def test_persist_file_with_mime_extension(self):
        """Test that persist_file adds correct file extension based on MIME type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chainlit.config.FILES_DIRECTORY", Path(tmpdir)):
                session = BaseSession(
                    id="test_id",
                    client_type="webapp",
                    thread_id=None,
                    user=None,
                    token=None,
                    user_env=None,
                )

                # Test with image MIME type
                result = await session.persist_file(
                    name="image.png",
                    mime="image/png",
                    content=b"fake image data",
                )

                file_id = result["id"]
                file_path = session.files[file_id]["path"]
                assert file_path.suffix == ".png"

    def test_clean_metadata_with_empty_dict(self):
        """Test clean_metadata with empty dictionary."""
        result = clean_metadata({})
        assert result == {}

    def test_websocket_session_with_chat_profile(self):
        """Test WebsocketSession with chat profile."""
        session = WebsocketSession(
            id="ws_id",
            socket_id="socket_123",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
            chat_profile="gpt-4",
        )

        assert session.chat_profile == "gpt-4"

    @pytest.mark.asyncio
    async def test_websocket_session_delete_with_mcp_sessions(self):
        """Test WebsocketSession delete with MCP sessions."""

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chainlit.config.FILES_DIRECTORY", Path(tmpdir)):
                session = WebsocketSession(
                    id="ws_id",
                    socket_id="socket_123",
                    emit=Mock(),
                    emit_call=Mock(),
                    user_env={},
                    client_type="webapp",
                )

                # Create a real McpSession with a completed task
                import asyncio

                stop = asyncio.Event()
                stop.set()  # already stopped

                async def _noop():
                    pass

                task = asyncio.create_task(_noop())
                await task  # let it finish

                mcp = McpSession(
                    name="mcp1",
                    client=Mock(),
                    task=task,
                    stop_event=stop,
                )
                session.mcp_sessions["mcp1"] = mcp

                await session.delete()

                assert "mcp1" not in session.mcp_sessions

    @pytest.mark.asyncio
    async def test_websocket_session_delete_with_hanging_mcp(self):
        """Test that session delete handles a slow MCP session gracefully."""
        import asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chainlit.config.FILES_DIRECTORY", Path(tmpdir)):
                session = WebsocketSession(
                    id="ws_id",
                    socket_id="socket_123",
                    emit=Mock(),
                    emit_call=Mock(),
                    user_env={},
                    client_type="webapp",
                )

                stop = asyncio.Event()

                async def _hang():
                    await stop.wait()

                task = asyncio.create_task(_hang())

                mcp = McpSession(
                    name="mcp1",
                    client=Mock(),
                    task=task,
                    stop_event=stop,
                )
                session.mcp_sessions["mcp1"] = mcp

                # delete() should close the session cleanly
                await session.delete()

                assert task.done()
                assert "mcp1" not in session.mcp_sessions


class TestMcpSession:
    """Test suite for the McpSession dataclass."""

    @pytest.mark.asyncio
    async def test_close_signals_stop_and_awaits_task(self):
        """close() sets the stop event and waits for the task."""
        import asyncio

        stop = asyncio.Event()

        async def _runner():
            await stop.wait()

        task = asyncio.create_task(_runner())
        mcp = McpSession(
            name="test",
            client=Mock(),
            task=task,
            stop_event=stop,
        )

        await mcp.close()

        assert stop.is_set()
        assert task.done()

    @pytest.mark.asyncio
    async def test_close_cancels_on_timeout(self):
        """close() cancels a task that doesn't respond to stop_event."""
        import asyncio

        stop = asyncio.Event()

        async def _stuck():
            # Ignore stop_event entirely
            await asyncio.sleep(3600)

        task = asyncio.create_task(_stuck())
        mcp = McpSession(
            name="stuck",
            client=Mock(),
            task=task,
            stop_event=stop,
        )

        # Temporarily reduce timeout for this test
        import chainlit.session as session_mod

        original_timeout = session_mod._CLOSE_TIMEOUT
        session_mod._CLOSE_TIMEOUT = 0.1
        try:
            await mcp.close()
        finally:
            session_mod._CLOSE_TIMEOUT = original_timeout

        assert task.done()

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Calling close() twice does not raise."""
        import asyncio

        stop = asyncio.Event()

        async def _runner():
            await stop.wait()

        task = asyncio.create_task(_runner())
        mcp = McpSession(
            name="test",
            client=Mock(),
            task=task,
            stop_event=stop,
        )

        await mcp.close()
        await mcp.close()  # second call should be safe

        assert task.done()

    @pytest.mark.asyncio
    async def test_stop_mcp_task_used_directly_without_an_mcp_session(self):
        """stop_mcp_task was extracted out of McpSession.close() so the /mcp
        connect handler in server.py can reuse the same bounded
        wait-then-cancel behavior on its timeout / blocked-destination /
        on_mcp_connect-failure paths, where there is no McpSession yet (only
        a bare task and stop_event). Verify it works standalone, not merely
        as a private helper behind McpSession.close()."""
        import asyncio

        from chainlit.session import stop_mcp_task

        stop = asyncio.Event()

        async def _runner():
            await stop.wait()

        task = asyncio.create_task(_runner())

        await stop_mcp_task(task, stop, "standalone")

        assert stop.is_set()
        assert task.done()


def _upload_override(enabled: bool):
    from chainlit.config import (
        ChainlitConfigOverrides,
        FeaturesSettings,
        SpontaneousFileUploadFeature,
    )

    return ChainlitConfigOverrides(
        features=FeaturesSettings(
            spontaneous_file_upload=SpontaneousFileUploadFeature(enabled=enabled)
        )
    )


class TestParseAcceptLanguage:
    @pytest.mark.parametrize(
        ("environ", "expected"),
        [
            ({"HTTP_ACCEPT_LANGUAGE": "fr-FR,fr;q=0.9"}, "fr-FR"),
            ({}, "en-US"),
            (None, "en-US"),
            ({"HTTP_ACCEPT_LANGUAGE": ";;"}, "en-US"),
        ],
    )
    def test_parse_accept_language(self, environ, expected):
        assert parse_accept_language(environ) == expected


class TestSelectChatProfile:
    """The client names its profile; a missing or unknown name falls back
    the way the frontend does, so it can't escape config_overrides."""

    def _profiles(self, default_name=None):
        from chainlit.types import ChatProfile

        return [
            ChatProfile(name=n, markdown_description=n, default=(n == default_name))
            for n in ("a", "b", "c")
        ]

    def test_exact_match(self):
        assert select_chat_profile(self._profiles("c"), "b").name == "b"

    @pytest.mark.parametrize("name", [None, "unknown", ""])
    def test_falls_back_to_default_profile(self, name):
        assert select_chat_profile(self._profiles("c"), name).name == "c"

    def test_falls_back_to_first_profile_without_default(self):
        assert select_chat_profile(self._profiles(), "unknown").name == "a"

    @pytest.mark.parametrize("profiles", [None, []])
    def test_no_profiles(self, profiles):
        assert select_chat_profile(profiles, "a") is None


class TestResolveSessionConfig:
    """resolve_session_config applies the chat profile's config_overrides,
    as /project/settings does for the UI (CVE-2026-110699)."""

    def _register(self, test_config, profiles_fn):
        from chainlit.utils import wrap_user_function

        test_config.code.set_chat_profiles = wrap_user_function(profiles_fn)

    def _profiles(self):
        from chainlit.types import ChatProfile

        return [
            ChatProfile(
                name="locked",
                markdown_description="",
                default=True,
                config_overrides=_upload_override(False),
            ),
            ChatProfile(name="open", markdown_description=""),
        ]

    @pytest.mark.asyncio
    async def test_without_chat_profiles_returns_global_config(self, test_config):
        test_config.code.set_chat_profiles = None
        assert await resolve_session_config(None, "en-US", "locked") is test_config

    @pytest.mark.asyncio
    async def test_applies_selected_profile_overrides(self, test_config):
        profiles = self._profiles()

        async def set_profiles(user, language):
            return profiles

        self._register(test_config, set_profiles)
        test_config.features.spontaneous_file_upload.enabled = True

        cfg = await resolve_session_config(None, "en-US", "locked")

        assert cfg is not test_config
        assert cfg.features.spontaneous_file_upload.enabled is False
        # the global config is not mutated
        assert test_config.features.spontaneous_file_upload.enabled is True
        # callbacks stay shared with the global config
        assert cfg.code is test_config.code

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", [None, "unknown"])
    async def test_missing_or_unknown_profile_uses_default(self, test_config, name):
        profiles = self._profiles()

        async def set_profiles(user, language):
            return profiles

        self._register(test_config, set_profiles)

        cfg = await resolve_session_config(None, "en-US", name)

        assert cfg.features.spontaneous_file_upload.enabled is False

    @pytest.mark.asyncio
    async def test_profile_without_overrides_returns_global_config(self, test_config):
        profiles = self._profiles()

        async def set_profiles(user, language):
            return profiles

        self._register(test_config, set_profiles)

        assert await resolve_session_config(None, "en-US", "open") is test_config

    @pytest.mark.asyncio
    async def test_passes_user_and_language_like_project_settings(self, test_config):
        calls = []
        profiles = self._profiles()

        async def set_profiles(user, language):
            calls.append((user, language))
            return profiles

        self._register(test_config, set_profiles)
        user = Mock(identifier="u")

        test_config.ui.language = None
        await resolve_session_config(user, "fr-FR", "locked")
        test_config.ui.language = "de-DE"
        await resolve_session_config(user, "fr-FR", "locked")

        assert calls == [(user, "fr-FR"), (user, "de-DE")]

    @pytest.mark.asyncio
    async def test_sync_and_single_argument_callbacks(self, test_config):
        profiles = self._profiles()

        def set_profiles(user):
            return profiles

        self._register(test_config, set_profiles)

        cfg = await resolve_session_config(None, "en-US", "locked")

        assert cfg.features.spontaneous_file_upload.enabled is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("registered_raw", [False, True])
    async def test_failing_callback_raises(self, test_config, registered_raw):
        """Fail closed: a client can make the callback raise (e.g. through
        the language), which must not drop the profile's restrictions."""

        async def set_profiles(user, language):
            raise RuntimeError("boom")

        if registered_raw:
            test_config.code.set_chat_profiles = set_profiles
        else:
            self._register(test_config, set_profiles)

        with pytest.raises(RuntimeError, match="boom"):
            await resolve_session_config(None, "zz", "locked")

    @pytest.mark.asyncio
    async def test_callback_returning_no_profiles_uses_global_config(self, test_config):
        async def set_profiles(user, language):
            return None

        self._register(test_config, set_profiles)

        assert await resolve_session_config(None, "en-US", "locked") is test_config

    @pytest.mark.asyncio
    async def test_directly_assigned_decorated_callback_runs_its_decorator(
        self, test_config
    ):
        """An app's own functools.wraps decorator (here: a permission filter)
        must not be skipped, or the session could pick a profile the user is
        not offered."""
        import functools

        from chainlit.types import ChatProfile

        all_profiles = [
            ChatProfile(name="locked", markdown_description="", default=True),
            ChatProfile(name="open", markdown_description=""),
        ]

        def only_locked(fn):
            @functools.wraps(fn)
            async def inner(user, language):
                return [p for p in await fn(user, language) if p.name == "locked"]

            return inner

        @only_locked
        async def set_profiles(user, language):
            return all_profiles

        test_config.code.set_chat_profiles = set_profiles
        all_profiles[0].config_overrides = _upload_override(False)

        # "open" isn't offered, so the default ("locked") applies
        cfg = await resolve_session_config(None, "en-US", "open")

        assert cfg.features.spontaneous_file_upload.enabled is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("signature", ["positional_only", "varargs"])
    async def test_directly_assigned_callback_is_called_positionally(
        self, test_config, signature
    ):
        profiles = self._profiles()
        calls = []

        async def positional_only(user, language, /):
            calls.append(language)
            return profiles

        async def varargs(*args):
            calls.append(args[1])
            return profiles

        set_profiles = {"positional_only": positional_only, "varargs": varargs}[
            signature
        ]
        test_config.code.set_chat_profiles = set_profiles

        cfg = await resolve_session_config(None, "en-US", "locked")

        assert calls == ["en-US"]
        assert cfg.features.spontaneous_file_upload.enabled is False

    @pytest.mark.asyncio
    async def test_app_decorators_on_the_callback_still_run(self, test_config):
        """Only `wrap_user_function`'s layer is skipped."""
        import functools

        calls = []
        profiles = self._profiles()

        def app_decorator(fn):
            @functools.wraps(fn)
            async def inner(user, language):
                calls.append(language)
                return await fn(user, language)

            return inner

        @app_decorator
        async def set_profiles(user, language):
            return profiles

        self._register(test_config, set_profiles)

        cfg = await resolve_session_config(None, "en-US", "locked")

        assert calls == ["en-US"]
        assert cfg.features.spontaneous_file_upload.enabled is False

    @pytest.mark.asyncio
    async def test_invalid_overrides_raise(self, test_config, monkeypatch):
        """Fail closed: /project/settings errors on them too, and the session
        must not silently run without the profile's restrictions."""
        profiles = self._profiles()

        async def set_profiles(user, language):
            return profiles

        self._register(test_config, set_profiles)
        monkeypatch.setattr(
            type(test_config),
            "with_overrides",
            Mock(side_effect=ValueError("bad override")),
        )

        with pytest.raises(ValueError, match="bad override"):
            await resolve_session_config(None, "en-US", "locked")


def _unregister(session):
    from chainlit.session import ws_sessions_id, ws_sessions_sid

    ws_sessions_id.pop(session.id, None)
    ws_sessions_sid.pop(session.socket_id, None)


class TestWebsocketSessionConfig:
    def test_uses_given_config(self):
        cfg = Mock()
        session = WebsocketSession(
            id="ws_cfg_id",
            socket_id="socket_cfg",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
            config=cfg,
        )
        try:
            assert session.config is cfg
            assert session.get_config() is cfg
        finally:
            _unregister(session)

    def test_defaults_to_global_config(self, test_config):
        session = WebsocketSession(
            id="ws_cfg_id2",
            socket_id="socket_cfg2",
            emit=Mock(),
            emit_call=Mock(),
            user_env={},
            client_type="webapp",
        )
        try:
            assert session.config is test_config
        finally:
            _unregister(session)
