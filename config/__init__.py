"""
Torin Configuration Module  
Provides access to the main torin configuration
"""

# Import the main configuration
try:
    import os
    exec(open(os.path.join(os.path.dirname(__file__), "torin_config.py")).read())
except Exception as e:
    print(f"Warning: Could not load torin_config.py: {e}")

__all__ = []
