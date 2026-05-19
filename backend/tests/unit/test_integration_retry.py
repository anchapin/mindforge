
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from backend.tools.github import GitHubTool
from backend.tools.base import ToolResult

@pytest.mark.asyncio
async def test_github_retry_on_503():
    """Verify that GitHubTool retries on 503 errors."""
    tool = GitHubTool()
    
    # Mock response for 503
    mock_resp_503 = MagicMock(spec=httpx.Response)
    mock_resp_503.status_code = 503
    mock_resp_503.text = "Service Unavailable"
    
    # Mock response for 200
    mock_resp_200 = MagicMock(spec=httpx.Response)
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = []
    mock_resp_200.headers = {}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    
    # First call returns 503, second returns 200
    mock_client.get = AsyncMock(side_effect=[mock_resp_503, mock_resp_200])

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await tool.execute(action="commits", token="ghp_test", repo="test/repo")
    
    # If retry logic is implemented, it should eventually succeed
    assert result.success is True
    assert mock_client.get.call_count == 2

@pytest.mark.asyncio
async def test_github_retry_on_timeout():
    """Verify that GitHubTool retries on httpx timeout."""
    tool = GitHubTool()
    
    # Mock response for 200
    mock_resp_200 = MagicMock(spec=httpx.Response)
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = []
    mock_resp_200.headers = {}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    
    # First call raises TimeoutException, second returns 200
    mock_client.get = AsyncMock(side_effect=[httpx.TimeoutException("Timeout"), mock_resp_200])

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await tool.execute(action="commits", token="ghp_test", repo="test/repo")
    
    assert result.success is True
    assert mock_client.get.call_count == 2
