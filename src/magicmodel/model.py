"""Base MagicModel class for DynamoDB entities."""

import re
from datetime import datetime
from typing import ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class MagicModel(BaseModel):
    """
    Base model for all DynamoDB entities.

    Automatically handles:
    - Type derivation from class name (snake_case)
    - UUID generation for ID
    - Timestamp management
    - Soft delete support

    Example:
        class Dog(MagicModel):
            name: str
            breed: str
            age: int = 0

        dog = Dog(name="Buddy", breed="Labrador")
        # dog.id, dog.type, dog.created_at, dog.updated_at are auto-managed
    """

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True,
        extra="allow",
    )

    # Primary key fields - use aliases to match Go's PascalCase in DynamoDB
    id: str = Field(default="", alias="ID")
    type: str = Field(default="", alias="Type")

    # Timestamp fields
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=None),
        alias="CreatedAt",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=None),
        alias="UpdatedAt",
    )
    deleted_at: datetime | None = Field(default=None, alias="DeletedAt")

    # Class-level table name override
    __table_name__: ClassVar[str | None] = None

    @classmethod
    def get_type_name(cls) -> str:
        """Get the DynamoDB Type value for this model (snake_case of class name)."""
        return to_snake_case(cls.__name__)

    def _prepare_for_create(self) -> None:
        """
        Set ID, Type, and timestamps before creation.

        Raises:
            ValueError: If model already has an ID (use save() for updates)
        """
        if self.id:
            raise ValueError("Cannot create: item already has an ID. Use save() for updates.")

        now = datetime.now(tz=None)
        self.id = str(uuid4())
        self.type = self.get_type_name()
        self.created_at = now
        self.updated_at = now

    def _prepare_for_save(self) -> None:
        """Set Type and timestamps for save (upsert) operation."""
        now = datetime.now(tz=None)
        if not self.id:
            self.id = str(uuid4())
            self.created_at = now
        self.type = self.get_type_name()
        self.updated_at = now

    @property
    def is_new(self) -> bool:
        """Check if this model has been persisted."""
        return not bool(self.id)

    @property
    def is_deleted(self) -> bool:
        """Check if this model has been soft-deleted."""
        return self.deleted_at is not None

    def to_dynamodb_item(self) -> dict[str, str | int | float | bool | None]:
        """Convert model to DynamoDB-compatible dict with aliases."""
        return self.model_dump(by_alias=True, exclude_none=False)
