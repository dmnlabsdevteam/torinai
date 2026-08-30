import sys, pytest
import os
sys.path.insert(0, '/Users/stefan/Dominion Labs/TorinAI')
from core.reasoning.context_config import ContextConfig

# Test invalid environment variable values
def test_invalid_env_vars():
    # Mock invalid environment variables
    os.environ['CONTEXT_COMPRESSION_INTERVAL'] = 'invalid'
    os.environ['CONTEXT_PRESERVE_RECENT'] = 'invalid'
    os.environ['CONTEXT_COMPRESSION_RATIO'] = 'invalid'
    os.environ['CONTEXT_SAFETY_MARGIN'] = 'invalid'
    os.environ['CONTEXT_WINDOW_SIZE'] = 'invalid'
    os.environ['COMPRESSION_TIMEOUT'] = 'invalid'
    os.environ['MAX_COMPRESSION_RETRIES'] = 'invalid'

    # Capture warnings
    with pytest.warns(UserWarning):
        config = ContextConfig()

    # Verify default values are used
    assert config.compression_interval == 5
    assert config.preserve_recent == 3
    assert config.target_compression_ratio == 0.5
    assert config.safety_margin == 500
    assert config.n_ctx == 4096
    assert config.compression_timeout_seconds == 30
    assert config.max_compression_retries == 2

# Test valid environment variable values
def test_valid_env_vars():
    # Mock valid environment variables
    os.environ['CONTEXT_COMPRESSION_INTERVAL'] = '10'
    os.environ['CONTEXT_PRESERVE_RECENT'] = '4'
    os.environ['CONTEXT_COMPRESSION_RATIO'] = '0.6'
    os.environ['CONTEXT_SAFETY_MARGIN'] = '600'
    os.environ['CONTEXT_WINDOW_SIZE'] = '5120'
    os.environ['COMPRESSION_TIMEOUT'] = '45'
    os.environ['MAX_COMPRESSION_RETRIES'] = '3'

    config = ContextConfig()

    # Verify values are correctly parsed
    assert config.compression_interval == 10
    assert config.preserve_recent == 4
    assert config.target_compression_ratio == 0.6
    assert config.safety_margin == 600
    assert config.n_ctx == 5120
    assert config.compression_timeout_seconds == 45
    assert config.max_compression_retries == 3
