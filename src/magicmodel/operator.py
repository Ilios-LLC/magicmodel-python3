"""MagicModelOperator for DynamoDB operations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeVar

import boto3
from botocore.exceptions import ClientError

from .exceptions import (
    ItemAlreadyExistsError,
    ItemNotFoundError,
    MagicModelError,
    TableCreationError,
)
from .model import MagicModel
from .query import QueryBuilder
from .serialization import Deserializer, Serializer

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

T = TypeVar("T", bound=MagicModel)


class MagicModelOperator:
    """
    Manages all DynamoDB interactions for MagicModel instances.

    Features:
    - Fluent method chaining
    - Native Python exception handling
    - WhereV4-style query building

    Example:
        mm = MagicModelOperator(table_name="MyTable")

        # Create
        dog = Dog(name="Buddy", breed="Labrador")
        mm.create(dog)

        # Find
        found_dog = mm.find(Dog, dog.id)

        # Query with WhereV4 semantics
        dogs = mm.where(Dog, "breed", ["Labrador", "Dalmatian"]).execute()

        # Error handling with try/except
        try:
            mm.create(dog).update(dog, name="Rex")
        except MagicModelError as e:
            print(f"Operation failed: {e}")
    """

    def __init__(
        self,
        table_name: str,
        endpoint_url: str | None = None,
        client: DynamoDBClient | None = None,
        region_name: str = "us-east-1",
        auto_create_table: bool = True,
        **boto_kwargs: Any,
    ) -> None:
        """
        Initialize the MagicModelOperator.

        Args:
            table_name: Name of the DynamoDB table
            endpoint_url: Optional endpoint URL (for LocalStack/local DynamoDB)
            client: Optional pre-configured DynamoDB client
            region_name: AWS region name
            auto_create_table: Whether to auto-create table if it doesn't exist
            **boto_kwargs: Additional kwargs passed to boto3 client
        """
        self._table_name = table_name
        self._endpoint_url = endpoint_url

        # Initialize client
        if client is not None:
            self._client: DynamoDBClient = client
        else:
            client_kwargs: dict[str, Any] = {"region_name": region_name, **boto_kwargs}
            if endpoint_url:
                client_kwargs["endpoint_url"] = endpoint_url
            self._client = boto3.client("dynamodb", **client_kwargs)

        # Initialize helpers
        self._serializer = Serializer()
        self._deserializer = Deserializer()
        self._checked_indexes: set[type] = set()

        # Auto-create table if configured
        if auto_create_table:
            self._ensure_table_exists()

    # ==================== Table Management ====================

    def _ensure_table_exists(self) -> None:
        """Create the DynamoDB table if it doesn't exist."""
        try:
            self._client.describe_table(TableName=self._table_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                self._create_table()
            else:
                raise TableCreationError(f"Failed to describe table: {e}") from e

    def _create_table(self) -> None:
        """Create the DynamoDB table with composite key schema."""
        try:
            self._client.create_table(
                TableName=self._table_name,
                AttributeDefinitions=[
                    {"AttributeName": "Type", "AttributeType": "S"},
                    {"AttributeName": "ID", "AttributeType": "S"},
                ],
                KeySchema=[
                    {"AttributeName": "Type", "KeyType": "HASH"},
                    {"AttributeName": "ID", "KeyType": "RANGE"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            # Wait for table to be active
            waiter = self._client.get_waiter("table_exists")
            waiter.wait(TableName=self._table_name)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                raise TableCreationError(f"Failed to create table: {e}") from e

    def _wait_for_table_active(self) -> None:
        """Wait until the table and all GSIs are ACTIVE."""
        import time

        for _ in range(120):
            desc = self._client.describe_table(TableName=self._table_name)
            table = desc["Table"]
            if table["TableStatus"] != "ACTIVE":
                time.sleep(0.5)
                continue
            # Also check that all GSIs are ACTIVE
            gsis = table.get("GlobalSecondaryIndexes", [])
            if all(g.get("IndexStatus") == "ACTIVE" for g in gsis):
                return
            time.sleep(0.5)
        raise MagicModelError(f"Table {self._table_name} did not become ACTIVE in time")

    # ==================== Index Management ====================

    @staticmethod
    def _get_dynamodb_attr_type(model_class: type[MagicModel], field_name: str) -> str:
        """Determine DynamoDB attribute type (S, N, B) from model field annotation."""
        from decimal import Decimal
        from typing import Union

        field_info = model_class.model_fields.get(field_name)
        if not field_info or not field_info.annotation:
            return "S"

        annotation = field_info.annotation
        origin = getattr(annotation, "__origin__", None)
        if origin is Union:
            args = [a for a in annotation.__args__ if a is not type(None)]
            annotation = args[0] if args else annotation

        if annotation in (int, float, Decimal):
            return "N"
        if annotation is bytes:
            return "B"
        return "S"

    @staticmethod
    def _resolve_field_db_name(model_class: type[MagicModel], field_name: str) -> str:
        """Resolve a Python field name to its DynamoDB attribute name."""
        field_info = model_class.model_fields.get(field_name)
        if field_info:
            if field_info.serialization_alias:
                return field_info.serialization_alias
            if field_info.alias:
                return field_info.alias
        alias_generator = model_class.model_config.get("alias_generator")
        if alias_generator and callable(alias_generator):
            return alias_generator(field_name)
        return field_name

    def _auto_ensure_indexes(self, model_class: type[MagicModel]) -> None:
        """Auto-create GSIs on first use of a model. Cached per model class."""
        if model_class in self._checked_indexes:
            return
        self._checked_indexes.add(model_class)
        self.ensure_indexes(model_class)

    def ensure_indexes(self, model_class: type[MagicModel]) -> MagicModelOperator:
        """
        Create any missing GSIs for fields listed in the model's __indexed__.

        Idempotent — safe to call multiple times. Skips indexes that already exist.
        Each indexed field gets a GSI named "gsi_{field_name}" with Type as partition
        key and the field as sort key.

        Called automatically on first use of a model with __indexed__. You only need
        to call this explicitly for migration scripts or eager setup.

        Args:
            model_class: The model class with __indexed__ field list

        Returns:
            Self for method chaining
        """
        indexed_fields = getattr(model_class, "__indexed__", None)
        if not indexed_fields:
            return self

        # Get existing GSI names
        try:
            desc = self._client.describe_table(TableName=self._table_name)
            existing = {
                g["IndexName"]
                for g in desc["Table"].get("GlobalSecondaryIndexes", [])
            }
        except Exception as e:
            raise MagicModelError(f"Failed to describe table for index check: {e}") from e

        for field_name in indexed_fields:
            index_name = f"gsi_{field_name}"
            if index_name in existing:
                continue

            db_attr_name = self._resolve_field_db_name(model_class, field_name)
            attr_type = self._get_dynamodb_attr_type(model_class, field_name)

            # Wait for table to be ACTIVE before creating index
            self._wait_for_table_active()

            try:
                self._client.update_table(
                    TableName=self._table_name,
                    AttributeDefinitions=[
                        {"AttributeName": "Type", "AttributeType": "S"},
                        {"AttributeName": db_attr_name, "AttributeType": attr_type},
                    ],
                    GlobalSecondaryIndexUpdates=[
                        {
                            "Create": {
                                "IndexName": index_name,
                                "KeySchema": [
                                    {"AttributeName": "Type", "KeyType": "HASH"},
                                    {"AttributeName": db_attr_name, "KeyType": "RANGE"},
                                ],
                                "Projection": {"ProjectionType": "ALL"},
                            }
                        }
                    ],
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "ValidationException":
                    raise MagicModelError(
                        f"Failed to create index {index_name}: {e}"
                    ) from e

        return self

    # ==================== CRUD Operations ====================

    def create(self, model: T) -> MagicModelOperator:
        """
        Create a new item in DynamoDB.

        Validates that the model doesn't already have an ID.
        Auto-generates ID, Type, and timestamps.

        Args:
            model: The MagicModel instance to create

        Returns:
            Self for method chaining

        Raises:
            MagicModelError: If the model already has an ID or creation fails
            ItemAlreadyExistsError: If an item with the same ID already exists
        """
        self._auto_ensure_indexes(type(model))

        try:
            model._prepare_for_create()
        except ValueError as e:
            raise MagicModelError(str(e)) from e

        try:
            item = self._serializer.serialize(model)
            self._client.put_item(
                TableName=self._table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(ID)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ItemAlreadyExistsError(
                    f"Item with ID {model.id} already exists"
                ) from e
            raise MagicModelError(f"Create failed: {e}") from e

        return self

    def find(self, model_class: type[T], id: str) -> T:
        """
        Find an item by ID.

        Args:
            model_class: The model class to find
            id: The item ID

        Returns:
            The found model instance

        Raises:
            ItemNotFoundError: If the item is not found
            MagicModelError: If the find operation fails
        """
        self._auto_ensure_indexes(model_class)

        try:
            type_name = model_class.get_type_name()
            response = self._client.get_item(
                TableName=self._table_name,
                Key={
                    "Type": {"S": type_name},
                    "ID": {"S": id},
                },
            )

            if "Item" not in response:
                raise ItemNotFoundError(f"Item not found: {id}")

            return self._deserializer.deserialize(response["Item"], model_class)
        except ItemNotFoundError:
            raise
        except Exception as e:
            raise MagicModelError(f"Find failed: {e}") from e

    def save(self, model: T) -> MagicModelOperator:
        """
        Save (upsert) a model to DynamoDB.

        Creates if new, updates if existing.

        Args:
            model: The MagicModel instance to save

        Returns:
            Self for method chaining

        Raises:
            MagicModelError: If the save operation fails
        """
        self._auto_ensure_indexes(type(model))

        try:
            model._prepare_for_save()
            item = self._serializer.serialize(model)

            self._client.put_item(
                TableName=self._table_name,
                Item=item,
            )
        except Exception as e:
            raise MagicModelError(f"Save failed: {e}") from e

        return self

    def update(self, model: T, **updates: Any) -> MagicModelOperator:
        """
        Update specific fields on an existing model.

        Args:
            model: The MagicModel instance to update
            **updates: Field names and their new values

        Returns:
            Self for method chaining

        Raises:
            MagicModelError: If the update operation fails
        """
        if not updates:
            return self

        try:
            # Build update expression
            set_parts: list[str] = []
            attr_names: dict[str, str] = {}
            attr_values: dict[str, Any] = {}

            # Always update updated_at
            now = datetime.now(tz=timezone.utc)
            updates["updated_at"] = now

            for field_name, value in updates.items():
                # Update the local model
                setattr(model, field_name, value)

                # Build expression parts
                attr_name = f"#{field_name}"
                attr_value = f":{field_name}"

                # Resolve to DynamoDB attribute name (matching model_dump(by_alias=True))
                field_info = type(model).model_fields.get(field_name)
                db_field_name = field_name
                if field_info:
                    if field_info.serialization_alias:
                        db_field_name = field_info.serialization_alias
                    elif field_info.alias:
                        db_field_name = field_info.alias
                    else:
                        alias_generator = type(model).model_config.get("alias_generator")
                        if alias_generator and callable(alias_generator):
                            db_field_name = alias_generator(field_name)

                attr_names[attr_name] = db_field_name
                attr_values[attr_value] = self._serializer.serialize_value(value)
                set_parts.append(f"{attr_name} = {attr_value}")

            update_expression = "SET " + ", ".join(set_parts)

            self._client.update_item(
                TableName=self._table_name,
                Key={
                    "Type": {"S": model.type},
                    "ID": {"S": model.id},
                },
                UpdateExpression=update_expression,
                ExpressionAttributeNames=attr_names,
                ExpressionAttributeValues=attr_values,
            )
        except Exception as e:
            raise MagicModelError(f"Update failed: {e}") from e

        return self

    def delete(self, model: T) -> MagicModelOperator:
        """
        Hard delete an item from DynamoDB.

        Args:
            model: The MagicModel instance to delete

        Returns:
            Self for method chaining

        Raises:
            MagicModelError: If the delete operation fails
        """
        try:
            self._client.delete_item(
                TableName=self._table_name,
                Key={
                    "Type": {"S": model.type},
                    "ID": {"S": model.id},
                },
            )
        except Exception as e:
            raise MagicModelError(f"Delete failed: {e}") from e

        return self

    def soft_delete(self, model: T) -> MagicModelOperator:
        """
        Soft delete an item by setting DeletedAt timestamp.

        Args:
            model: The MagicModel instance to soft-delete

        Returns:
            Self for method chaining

        Raises:
            MagicModelError: If the soft delete operation fails
        """
        now = datetime.now(tz=timezone.utc)

        try:
            self._client.update_item(
                TableName=self._table_name,
                Key={
                    "Type": {"S": model.type},
                    "ID": {"S": model.id},
                },
                UpdateExpression="SET #deleted = :deleted, #updated = :updated",
                ExpressionAttributeNames={
                    "#deleted": "DeletedAt",
                    "#updated": "UpdatedAt",
                },
                ExpressionAttributeValues={
                    ":deleted": {"S": now.isoformat()},
                    ":updated": {"S": now.isoformat()},
                },
            )
            model.deleted_at = now
            model.updated_at = now
        except Exception as e:
            raise MagicModelError(f"Soft delete failed: {e}") from e

        return self

    # ==================== Query Operations ====================

    def all(self, model_class: type[T]) -> list[T]:
        """
        Retrieve all items of a given model type.

        Excludes soft-deleted items.

        Args:
            model_class: The model class to query

        Returns:
            List of model instances

        Raises:
            MagicModelError: If the query fails
        """
        self._auto_ensure_indexes(model_class)

        try:
            type_name = model_class.get_type_name()

            response = self._client.query(
                TableName=self._table_name,
                KeyConditionExpression="#type = :type",
                FilterExpression="attribute_not_exists(#deleted) OR #deleted = :null",
                ExpressionAttributeNames={
                    "#type": "Type",
                    "#deleted": "DeletedAt",
                },
                ExpressionAttributeValues={
                    ":type": {"S": type_name},
                    ":null": {"NULL": True},
                },
            )

            return [
                self._deserializer.deserialize(item, model_class)
                for item in response.get("Items", [])
            ]
        except Exception as e:
            raise MagicModelError(f"All query failed: {e}") from e

    def where(
        self,
        model_class: type[T],
        field_name: str,
        *args: Any,
        chain: bool = False,
    ) -> QueryBuilder[T]:
        """
        Start a where query.

        Supports:
        - Equality: where(Dog, "breed", "Labrador")
        - OR: where(Dog, "breed", ["Labrador", "Dalmatian"])
        - Comparison: where(Dog, "age", ">=", 3)
        - Between: where(Dog, "age", "between", [1, 5])

        Args:
            model_class: The model class to query
            field_name: The field to filter on
            *args: (value,) for equality or (operator, value) for comparisons
            chain: If True, continue chaining

        Returns:
            QueryBuilder for further chaining or execution
        """
        self._auto_ensure_indexes(model_class)

        builder: QueryBuilder[T] = QueryBuilder(
            operator=self,
            model_class=model_class,
        )
        return builder.where(field_name, *args, chain=chain)
