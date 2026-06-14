"""Serialization and deserialization for DynamoDB AttributeValue format."""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

from .exceptions import DeserializationError, SerializationError

T = TypeVar("T", bound=BaseModel)


class Serializer:
    """Serializes Python values to DynamoDB AttributeValue format."""

    def serialize(self, model: BaseModel) -> dict[str, Any]:
        """
        Serialize a Pydantic model to DynamoDB item format.

        Args:
            model: The model to serialize

        Returns:
            Dict in DynamoDB AttributeValue format
        """
        try:
            data = model.model_dump(by_alias=True)
            skip = self._indexed_attr_names(model)
            return {
                k: self.serialize_value(v)
                for k, v in data.items()
                if not (v is None and k in skip)
            }
        except Exception as e:
            raise SerializationError(f"Failed to serialize model: {e}") from e

    @staticmethod
    def _indexed_attr_names(model: BaseModel) -> frozenset[str]:
        """Return DynamoDB attribute names for __indexed__ fields.

        None values on GSI sort key attributes must be omitted entirely —
        DynamoDB GSI keys only accept scalar types (S, N, B), not NULL.
        """
        indexed = getattr(model, "__indexed__", None)
        if not indexed:
            return frozenset()
        names: set[str] = set()
        model_cls = type(model)
        alias_gen = model_cls.model_config.get("alias_generator")
        for field_name in indexed:
            fi = model_cls.model_fields.get(field_name)
            if fi and fi.serialization_alias:
                names.add(fi.serialization_alias)
            elif fi and fi.alias:
                names.add(fi.alias)
            elif alias_gen and callable(alias_gen):
                names.add(alias_gen(field_name))
            else:
                names.add(field_name)
        return frozenset(names)

    def serialize_value(self, value: Any) -> dict[str, Any]:
        """
        Serialize a single Python value to DynamoDB AttributeValue.

        Args:
            value: The value to serialize

        Returns:
            Dict in DynamoDB AttributeValue format
        """
        if value is None:
            return {"NULL": True}
        elif isinstance(value, Enum):
            # Check Enum before int/str since IntEnum/StrEnum inherit from those
            return self.serialize_value(value.value)
        elif isinstance(value, bool):
            return {"BOOL": value}
        elif isinstance(value, str):
            return {"S": value}
        elif isinstance(value, int):
            return {"N": str(value)}
        elif isinstance(value, float):
            return {"N": str(value)}
        elif isinstance(value, Decimal):
            return {"N": str(value)}
        elif isinstance(value, bytes):
            return {"B": value}
        elif isinstance(value, datetime):
            # Ensure timezone info is always present (RFC3339 compat for Go)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return {"S": value.isoformat()}
        elif isinstance(value, (list, tuple)):
            return {"L": [self.serialize_value(v) for v in value]}
        elif isinstance(value, dict):
            return {"M": {k: self.serialize_value(v) for k, v in value.items()}}
        elif isinstance(value, set):
            if not value:
                return {"L": []}
            sample = next(iter(value))
            if isinstance(sample, str):
                return {"SS": sorted(value)}
            elif isinstance(sample, (int, float, Decimal)):
                return {"NS": sorted(str(v) for v in value)}
            elif isinstance(sample, bytes):
                return {"BS": list(value)}
            else:
                return {"L": [self.serialize_value(v) for v in value]}
        elif isinstance(value, BaseModel):
            # Handle nested Pydantic models
            data = value.model_dump(by_alias=True)
            return {"M": {k: self.serialize_value(v) for k, v in data.items()}}

        # Fallback: serialize as string
        return {"S": str(value)}


class Deserializer:
    """Deserializes DynamoDB AttributeValue format to Python values."""

    def deserialize(self, item: dict[str, Any], model_class: type[T]) -> T:
        """
        Deserialize a DynamoDB item to a Pydantic model.

        Args:
            item: DynamoDB item in AttributeValue format
            model_class: The model class to deserialize to

        Returns:
            Instance of the model class
        """
        try:
            data = {k: self.deserialize_value(v) for k, v in item.items()}
            return model_class.model_validate(data)
        except Exception as e:
            raise DeserializationError(
                f"Failed to deserialize to {model_class.__name__}: {e}"
            ) from e

    def deserialize_value(self, attr_value: dict[str, Any]) -> Any:
        """
        Deserialize a single DynamoDB AttributeValue to Python value.

        Args:
            attr_value: DynamoDB AttributeValue dict

        Returns:
            Python value
        """
        if "NULL" in attr_value:
            return None
        elif "BOOL" in attr_value:
            return attr_value["BOOL"]
        elif "S" in attr_value:
            # Try to parse as datetime
            s_value = attr_value["S"]
            try:
                return datetime.fromisoformat(s_value)
            except ValueError:
                return s_value
        elif "N" in attr_value:
            n_value = attr_value["N"]
            if "." in n_value:
                return float(n_value)
            return int(n_value)
        elif "B" in attr_value:
            return attr_value["B"]
        elif "L" in attr_value:
            return [self.deserialize_value(v) for v in attr_value["L"]]
        elif "M" in attr_value:
            return {k: self.deserialize_value(v) for k, v in attr_value["M"].items()}
        elif "SS" in attr_value:
            return set(attr_value["SS"])
        elif "NS" in attr_value:
            return {float(v) if "." in v else int(v) for v in attr_value["NS"]}
        elif "BS" in attr_value:
            return set(attr_value["BS"])
        else:
            raise DeserializationError(f"Unknown AttributeValue type: {attr_value}")
