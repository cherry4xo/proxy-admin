"""Tests for bridge-exit unlink functionality."""

import pytest
from unittest.mock import MagicMock

from bot.database.models import NodeLink
from bot.services.node_service import NodeService


@pytest.fixture()
def session_factory(mocker):
    """Create mock session factory."""
    return mocker.Mock()


@pytest.fixture()
def mock_session(mocker):
    """Create mock async session."""
    session = mocker.AsyncMock()
    session.__aenter__ = mocker.AsyncMock(return_value=session)
    session.__aexit__ = mocker.AsyncMock(return_value=False)
    return session


@pytest.fixture()
def node_service(mocker, session_factory, mock_session):
    """Create NodeService instance with mocked dependencies."""
    bitlaunch = mocker.Mock()
    yandex = mocker.Mock()
    cert_service = mocker.Mock()
    
    session_factory.return_value = mock_session
    
    return NodeService(
        bitlaunch=bitlaunch,
        yandex=yandex,
        session_factory=session_factory,
        cert_service=cert_service,
    )


@pytest.mark.asyncio
async def test_unlink_nodes_success(node_service, mock_session, mocker):
    """Test successful unlink of bridge from exit."""
    # Mock the delete result
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result
    
    result = await node_service.unlink_nodes(bridge_id=1, exit_id=2)
    
    assert result["success"] is True
    assert "Bridge #1 отвязан от Exit #2" in result["message"]
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_unlink_nodes_no_link_found(node_service, mock_session, mocker):
    """Test unlink when no link exists."""
    # Mock the delete result - no rows deleted
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_session.execute.return_value = mock_result
    
    result = await node_service.unlink_nodes(bridge_id=999)
    
    assert result["success"] is False
    assert result["error"] == "No link found to delete"


@pytest.mark.asyncio
async def test_unlink_nodes_bridge_only(node_service, mock_session, mocker):
    """Test unlink bridge from any exit (exit_id=None)."""
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result
    
    result = await node_service.unlink_nodes(bridge_id=1)
    
    assert result["success"] is True
    assert result["message"] == "Bridge #1 отвязан"


@pytest.mark.asyncio
async def test_unlink_nodes_multiple_links(node_service, mock_session, mocker):
    """Test unlink removes all matching links."""
    mock_result = MagicMock()
    mock_result.rowcount = 3  # Multiple links deleted
    mock_session.execute.return_value = mock_result
    
    result = await node_service.unlink_nodes(bridge_id=1)
    
    assert result["success"] is True
    assert "Bridge #1 отвязан" in result["message"]


@pytest.mark.asyncio
async def test_unlink_nodes_sql_query_structure(node_service, mock_session, mocker):
    """Test that the SQL query is structured correctly with aliases."""
    from sqlalchemy import delete as sql_delete
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result
    
    await node_service.unlink_nodes(bridge_id=1, exit_id=2)
    
    # Verify the query was called
    call_args = mock_session.execute.call_args
    query = call_args.args[0]
    
    # Query should be a delete statement for NodeLink
    assert isinstance(query, type(sql_delete(NodeLink)))
