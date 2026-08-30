# Imported through its package: appending the package directory to sys.path
# and importing the module top-level broke its own relative imports.
from core.database import logging_database

print('Module imported successfully')