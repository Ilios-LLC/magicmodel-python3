"""Custom exceptions for MagicModel."""


class MagicModelError(Exception):
    """Base exception for all MagicModel errors."""

    pass


class ItemNotFoundError(MagicModelError):
    """Raised when an item is not found in DynamoDB."""

    pass


class ItemAlreadyExistsError(MagicModelError):
    """Raised when attempting to create an item that already exists."""

    pass


class ValidationError(MagicModelError):
    """Raised when model validation fails."""

    pass


class TableCreationError(MagicModelError):
    """Raised when table creation fails."""

    pass


class SerializationError(MagicModelError):
    """Raised when serialization to DynamoDB format fails."""

    pass


class DeserializationError(MagicModelError):
    """Raised when deserialization from DynamoDB format fails."""

    pass
