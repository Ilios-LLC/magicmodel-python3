"""MagicModel - Python DynamoDB ORM inspired by magicmodel-go."""

from .exceptions import (
    DeserializationError,
    ItemAlreadyExistsError,
    ItemNotFoundError,
    MagicModelError,
    SerializationError,
    TableCreationError,
    ValidationError,
)
from .model import MagicModel
from .operator import MagicModelOperator
from .query import QueryBuilder

__all__ = [
    # Core
    "MagicModel",
    "MagicModelOperator",
    "QueryBuilder",
    # Exceptions
    "MagicModelError",
    "ItemNotFoundError",
    "ItemAlreadyExistsError",
    "ValidationError",
    "TableCreationError",
    "SerializationError",
    "DeserializationError",
]

__version__ = "0.1.0"
