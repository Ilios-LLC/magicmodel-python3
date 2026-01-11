"""Type definitions and protocols for MagicModel."""

from typing import Any, Protocol


class DynamoDBClientProtocol(Protocol):
    """
    Protocol defining the DynamoDB operations required by MagicModel.

    This matches the Go implementation's DynamoDBAPI interface,
    enabling both real boto3 clients and mock implementations.
    """

    def create_table(
        self,
        *,
        TableName: str,
        AttributeDefinitions: list[dict[str, str]],
        KeySchema: list[dict[str, str]],
        BillingMode: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def describe_table(
        self,
        *,
        TableName: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def put_item(
        self,
        *,
        TableName: str,
        Item: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def get_item(
        self,
        *,
        TableName: str,
        Key: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def delete_item(
        self,
        *,
        TableName: str,
        Key: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def update_item(
        self,
        *,
        TableName: str,
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeNames: dict[str, str] | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def query(
        self,
        *,
        TableName: str,
        KeyConditionExpression: str,
        ExpressionAttributeNames: dict[str, str] | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        FilterExpression: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def scan(
        self,
        *,
        TableName: str,
        FilterExpression: str | None = None,
        ExpressionAttributeNames: dict[str, str] | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def get_waiter(self, waiter_name: str) -> Any: ...
