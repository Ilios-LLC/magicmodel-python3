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

VALID_OPERATORS = frozenset({"=", "!=", "<>", ">", ">=", "<", "<=", "between", "begins_with"})


@dataclass
class WhereCondition:
    """Represents a single where condition."""

    field_name: str
    field_values: list[Any] = field(default_factory=list)
    operator: str = "="


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
        *args: Any,
        chain: bool = False,
    ) -> QueryBuilder[T]:
        from .exceptions import ValidationError

        if len(args) == 1:
            op = "="
            field_value = args[0]
        elif len(args) == 2:
            op = args[0]
            field_value = args[1]
        else:
            raise ValidationError("where() takes (field, value) or (field, operator, value)")

        if op not in VALID_OPERATORS:
            raise ValidationError(f"Unsupported operator: {op!r}")

        if op == "between":
            if not isinstance(field_value, (list, tuple)) or len(field_value) != 2:
                raise ValidationError("between operator requires two values: [start, end]")
            values = list(field_value)
        elif op == "=" and isinstance(field_value, (list, tuple, set)) and not isinstance(
            field_value, str
        ):
            values = list(field_value)
        else:
            values = [field_value]

        self._conditions.append(
            WhereCondition(
                field_name=field_name,
                field_values=values,
                operator=op,
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

    def _resolve_field_path(
        self,
        condition: WhereCondition,
        index: Any,
        attr_names: dict[str, str],
    ) -> str:
        """Resolve a condition's field name to a DynamoDB expression path."""
        field_parts = condition.field_name.split(".")
        if len(field_parts) > 1:
            path_aliases = []
            for j, part in enumerate(field_parts):
                alias = f"#f{index}_{j}"
                db_name = self._resolve_db_field_name(part, j, field_parts)
                attr_names[alias] = db_name
                path_aliases.append(alias)
            return ".".join(path_aliases)
        else:
            field_alias = f"#f{index}"
            db_name = self._resolve_db_field_name(
                condition.field_name, 0, [condition.field_name]
            )
            attr_names[field_alias] = db_name
            return field_alias

    def _build_condition_expr(
        self,
        condition: WhereCondition,
        field_path: str,
        index: Any,
        attr_values: dict[str, Any],
    ) -> str:
        """Build a single condition expression string and populate attr_values."""
        op = condition.operator

        if op == "=" and len(condition.field_values) > 1:
            value_aliases = []
            for j, val in enumerate(condition.field_values):
                value_alias = f":v{index}_{j}"
                attr_values[value_alias] = self._operator._serializer.serialize_value(val)
                value_aliases.append(value_alias)
            return f"{field_path} IN ({', '.join(value_aliases)})"
        elif op == "between":
            start_alias = f":v{index}_start"
            end_alias = f":v{index}_end"
            attr_values[start_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            attr_values[end_alias] = self._operator._serializer.serialize_value(
                condition.field_values[1]
            )
            return f"{field_path} BETWEEN {start_alias} AND {end_alias}"
        elif op == "begins_with":
            value_alias = f":v{index}"
            attr_values[value_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            return f"begins_with({field_path}, {value_alias})"
        elif op in ("!=", "<>"):
            value_alias = f":v{index}"
            attr_values[value_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            return f"{field_path} <> {value_alias}"
        else:
            value_alias = f":v{index}"
            attr_values[value_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            return f"{field_path} {op} {value_alias}"

    def _find_gsi_match(
        self,
    ) -> tuple[str | None, list[WhereCondition], list[WhereCondition]]:
        """
        Check if any conditions can be served by a GSI.

        Returns:
            (index_name, gsi_conditions, remaining_conditions)
            or (None, [], self._conditions) if no GSI matches.
        """
        indexed_fields = getattr(self._model_class, "__indexed__", None)
        if not indexed_fields:
            return None, [], list(self._conditions)

        for field_name in indexed_fields:
            gsi_conds = [c for c in self._conditions if c.field_name == field_name]
            if gsi_conds:
                remaining = [c for c in self._conditions if c.field_name != field_name]
                return f"gsi_{field_name}", gsi_conds, remaining

        return None, [], list(self._conditions)

    def _execute_query(self) -> list[T]:
        """Build and execute the DynamoDB query, using GSI when available."""
        type_name = self._model_class.get_type_name()

        attr_names: dict[str, str] = {"#type": "Type", "#deleted": "DeletedAt"}
        attr_values: dict[str, Any] = {
            ":type": {"S": type_name},
            ":null": {"NULL": True},
        }

        # Check for GSI match
        index_name, gsi_conditions, remaining_conditions = self._find_gsi_match()

        # Build key condition
        key_parts = ["#type = :type"]

        if index_name and gsi_conditions:
            for i, condition in enumerate(gsi_conditions):
                field_path = self._resolve_field_path(condition, f"k{i}", attr_names)
                expr = self._build_condition_expr(
                    condition, field_path, f"k{i}", attr_values
                )
                key_parts.append(expr)

        key_condition = " AND ".join(key_parts)

        # Build filter expression from remaining conditions
        filter_parts: list[str] = []
        filter_parts.append("(attribute_not_exists(#deleted) OR #deleted = :null)")

        conditions_for_filter = remaining_conditions if index_name else self._conditions
        for i, condition in enumerate(conditions_for_filter):
            field_path = self._resolve_field_path(condition, i, attr_names)
            expr = self._build_condition_expr(condition, field_path, i, attr_values)
            filter_parts.append(expr)

        # Build query kwargs
        query_kwargs: dict[str, Any] = {
            "TableName": self._operator._table_name,
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeNames": attr_names,
            "ExpressionAttributeValues": attr_values,
        }

        if index_name:
            query_kwargs["IndexName"] = index_name

        if filter_parts:
            query_kwargs["FilterExpression"] = " AND ".join(filter_parts)

        items: list[dict[str, Any]] = []
        while True:
            response = self._operator._client.query(**query_kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query_kwargs["ExclusiveStartKey"] = last_key

        return [
            self._operator._deserializer.deserialize(item, self._model_class)
            for item in items
        ]
