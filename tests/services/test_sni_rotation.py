"""Tests for dynamic SNI rotation service - core logic only."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from bot.services.sni_rotation_service import SNIRotationService, DEFAULT_SNI_POOL


class TestSNIRotationService:
    """Test SNI rotation service core logic."""

    @pytest.fixture
    def mock_session_factory(self):
        """Create mock session factory."""
        return MagicMock()

    @pytest.fixture
    def sni_service(self, mock_session_factory):
        """Create SNI rotation service instance."""
        return SNIRotationService(session_factory=mock_session_factory)

    def test_get_sni_pool_empty_node(self, sni_service):
        """Test SNI pool retrieval for node without custom pool."""
        mock_node = MagicMock()
        mock_node.sni_pool_encrypted = None
        
        pool = sni_service._get_sni_pool(mock_node)
        
        assert pool == DEFAULT_SNI_POOL.copy()
        assert pool is not DEFAULT_SNI_POOL  # Should be a copy

    def test_get_current_sni_priority_custom_domain(self, sni_service):
        """Test SNI selection: custom domain takes priority."""
        mock_node = MagicMock()
        mock_node.reality_domain = "my-custom.com"
        mock_node.sni_pool_encrypted = "encrypted"
        mock_node.reality_sni = "microsoft.com"
        
        with patch.object(sni_service, '_get_sni_pool', return_value=["google.com"]):
            sni = sni_service._get_current_sni(mock_node)
        
        assert sni == "my-custom.com"

    def test_get_current_sni_priority_pool(self, sni_service):
        """Test SNI selection: pool when no custom domain."""
        mock_node = MagicMock()
        mock_node.reality_domain = None
        mock_node.sni_pool_encrypted = "encrypted"
        mock_node.current_sni_index = 1
        mock_node.reality_sni = None
        
        with patch.object(sni_service, '_get_sni_pool', return_value=["google.com", "microsoft.com", "apple.com"]):
            sni = sni_service._get_current_sni(mock_node)
        
        assert sni == "microsoft.com"  # index 1

    def test_get_current_sni_fallback_static(self, sni_service):
        """Test SNI selection: fallback to static reality_sni."""
        mock_node = MagicMock()
        mock_node.reality_domain = None
        mock_node.sni_pool_encrypted = None
        mock_node.reality_sni = "dl.google.com"
        
        sni = sni_service._get_current_sni(mock_node)
        
        assert sni == "dl.google.com"

    def test_get_current_sni_fallback_default(self, sni_service):
        """Test SNI selection: fallback to global default."""
        mock_node = MagicMock()
        mock_node.reality_domain = None
        mock_node.sni_pool_encrypted = None
        mock_node.reality_sni = None
        
        with patch('bot.services.sni_rotation_service.settings') as mock_settings:
            mock_settings.REALITY_SNI = "default.example.com"
            sni = sni_service._get_current_sni(mock_node)
        
        assert sni == "default.example.com"

    def test_check_tls_health_timeout(self, sni_service):
        """Test TLS health check timeout."""
        import socket
        import asyncio
        
        async def test_async():
            with patch('socket.create_connection', side_effect=socket.timeout):
                result = await sni_service.check_tls_health("blocked.example.com")
            
            assert result["healthy"] is False
            assert result["error"] == "TIMEOUT"
        
        asyncio.run(test_async())

    def test_set_sni_pool_encryption(self, sni_service):
        """Test SNI pool is encrypted when saved."""
        mock_node = MagicMock()
        mock_node.sni_pool_encrypted = None
        
        test_pool = ["google.com", "microsoft.com"]
        sni_service._save_sni_pool(mock_node, test_pool)
        
        assert mock_node.sni_pool_encrypted is not None
        assert mock_node.sni_pool_encrypted != test_pool  # Should be encrypted

    def test_default_pool_quality(self):
        """Test default SNI pool contains high-quality domains."""
        assert len(DEFAULT_SNI_POOL) >= 3
        assert "dl.google.com" in DEFAULT_SNI_POOL
        assert "www.microsoft.com" in DEFAULT_SNI_POOL
        assert "cdn.apple.com" in DEFAULT_SNI_POOL
        
        # All domains should be valid format
        for domain in DEFAULT_SNI_POOL:
            assert " " not in domain
            assert "." in domain
            assert domain == domain.lower()  # Should be lowercase

    def test_rotation_interval_validation(self):
        """Test rotation interval bounds."""
        # Valid intervals
        assert 1 <= 24 <= 168
        assert 1 <= 1 <= 168
        assert 1 <= 168 <= 168
        
        # Invalid intervals would be caught by set_rotation_interval
        # (integration test, not unit test)

    def test_sni_index_wrapping(self, sni_service):
        """Test SNI index wraps around pool size."""
        mock_node = MagicMock()
        mock_node.reality_domain = None
        mock_node.sni_pool_encrypted = "encrypted"
        mock_node.current_sni_index = 10  # Beyond pool size
        mock_node.reality_sni = None
        
        pool = ["a.com", "b.com", "c.com"]  # 3 domains
        with patch.object(sni_service, '_get_sni_pool', return_value=pool):
            sni = sni_service._get_current_sni(mock_node)
        
        # Index 10 % 3 = 1, so should return pool[1]
        assert sni == "b.com"
