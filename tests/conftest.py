"""Pytest fixtures for MagicModel tests using LocalStack."""

import boto3
import pytest
from testcontainers.localstack import LocalStackContainer

from magicmodel import MagicModel, MagicModelOperator


# Test models
class Dog(MagicModel):
    """Test model representing a dog."""

    name: str
    breed: str
    age: int = 0
    status: str = "ACTIVE"
    environment: str = "dev"
    is_good_boy: bool = True


class Cat(MagicModel):
    """Test model representing a cat."""

    name: str
    color: str
    lives: int = 9


@pytest.fixture(scope="session")
def localstack():
    """Start LocalStack container for the test session."""
    with LocalStackContainer(image="localstack/localstack:latest") as container:
        yield container


@pytest.fixture(scope="session")
def dynamodb_endpoint(localstack):
    """Get the DynamoDB endpoint URL from LocalStack."""
    return localstack.get_url()


@pytest.fixture(scope="session")
def dynamodb_client(dynamodb_endpoint):
    """Create a boto3 DynamoDB client connected to LocalStack."""
    return boto3.client(
        "dynamodb",
        endpoint_url=dynamodb_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def operator(dynamodb_endpoint):
    """Create a MagicModelOperator connected to LocalStack."""
    return MagicModelOperator(
        table_name="TestTable",
        endpoint_url=dynamodb_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def clean_operator(operator):
    """Operator with cleanup after each test."""
    yield operator
    # Clean up all dogs and cats after the test
    _cleanup_items(operator, Dog)
    _cleanup_items(operator, Cat)


def _cleanup_items(operator: MagicModelOperator, model_class: type[MagicModel]) -> None:
    """Delete all items of a given model type."""
    # Get all items including soft-deleted
    type_name = model_class.get_type_name()
    try:
        response = operator._client.query(
            TableName=operator._table_name,
            KeyConditionExpression="#type = :type",
            ExpressionAttributeNames={"#type": "Type"},
            ExpressionAttributeValues={":type": {"S": type_name}},
        )

        for item in response.get("Items", []):
            operator._client.delete_item(
                TableName=operator._table_name,
                Key={
                    "Type": item["Type"],
                    "ID": item["ID"],
                },
            )
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture
def dog_factory():
    """Factory for creating test dogs."""

    def _create(**kwargs) -> Dog:
        defaults = {
            "name": "Buddy",
            "breed": "Labrador",
            "age": 3,
            "status": "ACTIVE",
            "environment": "dev",
            "is_good_boy": True,
        }
        defaults.update(kwargs)
        return Dog(**defaults)

    return _create


@pytest.fixture
def cat_factory():
    """Factory for creating test cats."""

    def _create(**kwargs) -> Cat:
        defaults = {
            "name": "Whiskers",
            "color": "Orange",
            "lives": 9,
        }
        defaults.update(kwargs)
        return Cat(**defaults)

    return _create
