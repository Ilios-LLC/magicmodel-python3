"""Query builder with WhereV4 semantics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar, Union

from pydantic import BaseModel

from .model import MagicModel

if TYPE_CHECKING:
    from .operator import MagicModelOperator

T = TypeVar("T", bound=MagicModel)


@dataclass
class WhereCondition:
    """Represents a single where condition."""

    field_name: str
    field_values: list[Any] = field(default_factory=list)


class QueryBuilder(Generic[T]):
    """
    Builds and executes DynamoDB queries with WhereV4 semantics.

    Supports:
    - Single value equality: where("breed", "Labrador")
    - OR within field: where("breed", ["Labrador", "Dalmatian"])
    - AND across fields: .where(..., chain=True).where(..., chain=False)

    Example:
        # Find dogs that are (Labrador OR Dalmatian) AND in dev environment
        results = (mm.where(Dog, "breed", ["Labrador", "Dalmatian"], chain=True)
                    .where("environment", "dev")
                    .execute())
    """

    def __init__(
        self,
        operator: MagicModelOperator,
        model_class: type[T],
    ) -> None:
        self._operator = operator
        self._model_class = model_class
        self._conditions: list[WhereCondition] = []
        self._is_chain: bool = False

    def where(
        self,
        field_name: str,
        field_value: Any | Sequence[Any],
        chain: bool = False,
    ) -> QueryBuilder[T]:
        """
        Add a where condition.

        Args:
            field_name: The field to filter on
            field_value: Single value or list of values (list = OR)
            chain: If True, more conditions follow; if False, ready to execute

        Returns:
            Self for method chaining
        """
        # Normalize to list
        if isinstance(field_value, (list, tuple, set)) and not isinstance(field_value, str):
            values = list(field_value)
        else:
            values = [field_value]

        self._conditions.append(
            WhereCondition(
                field_name=field_name,
                field_values=values,
            )
        )

        self._is_chain = chain
        return self

    def _resolve_db_field_name(self, part: str, depth: int, full_path: list[str]) -> str:
        """Resolve a Python field name to its DynamoDB attribute name (matching model_dump(by_alias=True))."""
        model_class = self._model_class

        if depth > 0:
            # For nested paths, try to get the nested model's class
            model_class = self._get_nested_model_class(full_path[:depth])
            if not model_class:
                return part

        field_info = model_class.model_fields.get(part)
        if field_info:
            if field_info.serialization_alias:
                return field_info.serialization_alias
            if field_info.alias:
                return field_info.alias
        alias_generator = model_class.model_config.get("alias_generator")
        if alias_generator and callable(alias_generator):
            return alias_generator(part)
        return part

    def _get_nested_model_class(self, path: list[str]) -> type | None:
        """Walk the field path to find the nested model class."""
        current_class: type = self._model_class
        for part in path:
            field_info = current_class.model_fields.get(part)
            if not field_info or not field_info.annotation:
                return None
            annotation = field_info.annotation
            # Unwrap Optional[X] (Union[X, None])
            origin = getattr(annotation, "__origin__", None)
            if origin is Union:
                args = [a for a in annotation.__args__ if a is not type(None)]
                annotation = args[0] if args else annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                current_class = annotation
            else:
                return None
        return current_class

    def execute(self) -> list[T]:
        """
        Execute the query and return results.

        Returns:
            List of model instances matching all conditions

        Raises:
            ValidationError: If no conditions are specified
            MagicModelError: If the query fails
        """
        if not self._conditions:
            from .exceptions import ValidationError

            raise ValidationError("No conditions specified for where query")

        try:
            return self._execute_query()
        except Exception as e:
            from .exceptions import MagicModelError

            raise MagicModelError(f"Query failed: {e}") from e

    def _execute_query(self) -> list[T]:
        """Build and execute the DynamoDB query."""
        type_name = self._model_class.get_type_name()

        # Build expression components
        key_condition = "#type = :type"
        filter_parts: list[str] = []
        attr_names: dict[str, str] = {"#type": "Type", "#deleted": "DeletedAt"}
        attr_values: dict[str, Any] = {
            ":type": {"S": type_name},
            ":null": {"NULL": True},
        }

        # Add soft delete filter
        filter_parts.append("(attribute_not_exists(#deleted) OR #deleted = :null)")

        # Add field conditions
        for i, condition in enumerate(self._conditions):
            # Handle dot notation for nested fields
            field_parts = condition.field_name.split(".")
            if len(field_parts) > 1:
                # Nested field: "observability.provider" -> "#f0_0.#f0_1"
                path_aliases = []
                for j, part in enumerate(field_parts):
                    alias = f"#f{i}_{j}"
                    db_name = self._resolve_db_field_name(part, j, field_parts)
                    attr_names[alias] = db_name
                    path_aliases.append(alias)
                field_path = ".".join(path_aliases)
            else:
                # Simple field - resolve alias to match model_dump(by_alias=True)
                field_alias = f"#f{i}"
                db_name = self._resolve_db_field_name(condition.field_name, 0, [condition.field_name])
                attr_names[field_alias] = db_name
                field_path = field_alias

            if len(condition.field_values) == 1:
                # Single value - equality
                value_alias = f":v{i}"
                attr_values[value_alias] = self._operator._serializer.serialize_value(
                    condition.field_values[0]
                )
                filter_parts.append(f"{field_path} = {value_alias}")
            else:
                # Multiple values - IN operator
                value_aliases = []
                for j, val in enumerate(condition.field_values):
                    value_alias = f":v{i}_{j}"
                    attr_values[value_alias] = self._operator._serializer.serialize_value(val)
                    value_aliases.append(value_alias)

                in_clause = ", ".join(value_aliases)
                filter_parts.append(f"{field_path} IN ({in_clause})")

        # Combine filter expressions with AND
        filter_expression = " AND ".join(filter_parts)

        # Execute query
        response = self._operator._client.query(
            TableName=self._operator._table_name,
            KeyConditionExpression=key_condition,
            FilterExpression=filter_expression,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

        return [
            self._operator._deserializer.deserialize(item, self._model_class)
            for item in response.get("Items", [])
        ]
