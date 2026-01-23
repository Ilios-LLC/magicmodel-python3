"""Integration tests for nested/complex model serialization."""

from datetime import date
from enum import Enum
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from magicmodel import MagicModel, MagicModelOperator


class Status(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class Priority(int, Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


# Model for testing edge case types
class EdgeCaseModel(MagicModel):
    name: str
    # UUID field
    correlationId: UUID | None = None
    # date (not datetime)
    birthDate: date | None = None
    # Tuple field - Pydantic converts to list by default
    coordinates: tuple[float, float] | None = None
    # Deeply nested structure
    metadata: dict | None = None
    # List of tuples
    points: list[tuple[float, float]] | None = None


# Nested model (not a MagicModel, just a regular Pydantic BaseModel)
class OrchestratorStackOutputs(BaseModel):
    vpcId: str | None = None
    vpcCidr: str | None = None
    privateSubnetIds: list[str] = []
    publicSubnetIds: list[str] = []
    ecsClusterArn: str | None = None
    dynamoDbTableArn: str | None = None


class CiCdProvider(BaseModel):
    name: str
    apiKey: str | None = None
    enabled: bool = False


class Observability(BaseModel):
    provider: str | None = None
    apiKey: str | None = None
    endpoint: str | None = None
    status: Status | None = None
    priority: Priority | None = None


# Main model with nested fields
class Account(MagicModel):
    awsRegion: str
    awsAccountId: str
    name: str | None = None
    isMainAccount: bool | None = None
    ciCdProviders: list[CiCdProvider] | None = None
    observability: Observability | None = None
    orchestratorStackOutputs: OrchestratorStackOutputs | None = None


@pytest.fixture
def nested_operator(dynamodb_endpoint):
    """Create a MagicModelOperator for nested model tests."""
    return MagicModelOperator(
        table_name="NestedTestTable",
        endpoint_url=dynamodb_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def clean_nested_operator(nested_operator):
    """Operator with cleanup after each test."""
    yield nested_operator
    # Clean up all accounts after the test
    type_name = Account.get_type_name()
    try:
        response = nested_operator._client.query(
            TableName=nested_operator._table_name,
            KeyConditionExpression="#type = :type",
            ExpressionAttributeNames={"#type": "Type"},
            ExpressionAttributeValues={":type": {"S": type_name}},
        )
        for item in response.get("Items", []):
            nested_operator._client.delete_item(
                TableName=nested_operator._table_name,
                Key={"Type": item["Type"], "ID": item["ID"]},
            )
    except Exception:
        pass


class TestNestedModels:
    """Tests for nested Pydantic models."""

    def test_create_with_nested_model(self, clean_nested_operator):
        """Test creating a model with a nested Pydantic model."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="123456789012",
            name="Main Account",
            orchestratorStackOutputs=OrchestratorStackOutputs(
                vpcId="vpc-12345",
                vpcCidr="10.0.0.0/16",
                privateSubnetIds=["subnet-priv-1", "subnet-priv-2"],
                publicSubnetIds=["subnet-pub-1"],
            ),
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.awsRegion == "us-east-1"
        assert found.awsAccountId == "123456789012"
        assert found.orchestratorStackOutputs is not None
        assert found.orchestratorStackOutputs.vpcId == "vpc-12345"
        assert found.orchestratorStackOutputs.vpcCidr == "10.0.0.0/16"
        assert found.orchestratorStackOutputs.privateSubnetIds == ["subnet-priv-1", "subnet-priv-2"]
        assert found.orchestratorStackOutputs.publicSubnetIds == ["subnet-pub-1"]

    def test_create_with_nested_model_from_dict(self, clean_nested_operator):
        """Test creating a model with nested data passed as a dict."""
        account = Account(
            awsRegion="us-west-2",
            awsAccountId="987654321098",
            orchestratorStackOutputs={
                "vpcId": "vpc-dict-test",
                "privateSubnetIds": ["subnet-a"],
                "publicSubnetIds": ["subnet-b"],
            },
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.orchestratorStackOutputs.vpcId == "vpc-dict-test"
        assert found.orchestratorStackOutputs.privateSubnetIds == ["subnet-a"]

    def test_create_with_list_of_nested_models(self, clean_nested_operator):
        """Test creating a model with a list of nested models."""
        account = Account(
            awsRegion="eu-west-1",
            awsAccountId="111222333444",
            ciCdProviders=[
                CiCdProvider(name="GitHub", apiKey="gh-key-123", enabled=True),
                CiCdProvider(name="GitLab", apiKey="gl-key-456", enabled=False),
            ],
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.ciCdProviders is not None
        assert len(found.ciCdProviders) == 2
        assert found.ciCdProviders[0].name == "GitHub"
        assert found.ciCdProviders[0].apiKey == "gh-key-123"
        assert found.ciCdProviders[0].enabled is True
        assert found.ciCdProviders[1].name == "GitLab"
        assert found.ciCdProviders[1].enabled is False

    def test_create_with_multiple_nested_models(self, clean_nested_operator):
        """Test creating a model with multiple different nested models."""
        account = Account(
            awsRegion="ap-southeast-1",
            awsAccountId="555666777888",
            isMainAccount=True,
            observability=Observability(
                provider="datadog",
                apiKey="dd-api-key",
                endpoint="https://api.datadoghq.com",
            ),
            orchestratorStackOutputs=OrchestratorStackOutputs(
                vpcId="vpc-multi",
                ecsClusterArn="arn:aws:ecs:ap-southeast-1:555666777888:cluster/main",
                privateSubnetIds=["subnet-1"],
                publicSubnetIds=["subnet-2"],
            ),
            ciCdProviders=[
                CiCdProvider(name="CircleCI", enabled=True),
            ],
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.isMainAccount is True
        assert found.observability.provider == "datadog"
        assert found.observability.apiKey == "dd-api-key"
        assert found.orchestratorStackOutputs.vpcId == "vpc-multi"
        assert found.orchestratorStackOutputs.ecsClusterArn == "arn:aws:ecs:ap-southeast-1:555666777888:cluster/main"
        assert len(found.ciCdProviders) == 1
        assert found.ciCdProviders[0].name == "CircleCI"

    def test_update_nested_model(self, clean_nested_operator):
        """Test updating a nested model field."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="999888777666",
            orchestratorStackOutputs=OrchestratorStackOutputs(
                vpcId="vpc-original",
                privateSubnetIds=["subnet-old"],
                publicSubnetIds=[],
            ),
        )

        clean_nested_operator.create(account)

        # Update with new nested model
        clean_nested_operator.update(
            account,
            orchestratorStackOutputs=OrchestratorStackOutputs(
                vpcId="vpc-updated",
                vpcCidr="172.16.0.0/16",
                privateSubnetIds=["subnet-new-1", "subnet-new-2"],
                publicSubnetIds=["subnet-pub-new"],
            ),
        )

        found = clean_nested_operator.find(Account, account.id)
        assert found.orchestratorStackOutputs.vpcId == "vpc-updated"
        assert found.orchestratorStackOutputs.vpcCidr == "172.16.0.0/16"
        assert found.orchestratorStackOutputs.privateSubnetIds == ["subnet-new-1", "subnet-new-2"]

    def test_nested_model_with_none_values(self, clean_nested_operator):
        """Test that None nested models are handled correctly."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="000111222333",
            orchestratorStackOutputs=None,
            observability=None,
            ciCdProviders=None,
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.orchestratorStackOutputs is None
        assert found.observability is None
        assert found.ciCdProviders is None

    def test_nested_model_with_empty_lists(self, clean_nested_operator):
        """Test nested models with empty list fields."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="444555666777",
            orchestratorStackOutputs=OrchestratorStackOutputs(
                vpcId="vpc-empty-lists",
                privateSubnetIds=[],
                publicSubnetIds=[],
            ),
            ciCdProviders=[],
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.orchestratorStackOutputs.privateSubnetIds == []
        assert found.orchestratorStackOutputs.publicSubnetIds == []
        assert found.ciCdProviders == []

    def test_save_with_nested_model(self, clean_nested_operator):
        """Test save (upsert) with nested models."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="888999000111",
            observability=Observability(provider="newrelic"),
        )

        # Save creates new
        clean_nested_operator.save(account)
        account_id = account.id

        # Modify and save again
        account.observability = Observability(provider="prometheus", endpoint="http://prom:9090")
        clean_nested_operator.save(account)

        found = clean_nested_operator.find(Account, account_id)
        assert found.observability.provider == "prometheus"
        assert found.observability.endpoint == "http://prom:9090"


class TestEnumSerialization:
    """Tests for enum field serialization."""

    def test_string_enum_in_nested_model(self, clean_nested_operator):
        """Test that string enums serialize to their value, not 'Status.CREATED'."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="enum-test-001",
            observability=Observability(
                provider="datadog",
                status=Status.ACTIVE,
            ),
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.observability.status == Status.ACTIVE
        # The key test: ensure it deserializes back to the enum
        assert found.observability.status.value == "ACTIVE"

    def test_int_enum_in_nested_model(self, clean_nested_operator):
        """Test that int enums serialize correctly."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="enum-test-002",
            observability=Observability(
                provider="prometheus",
                priority=Priority.HIGH,
            ),
        )

        clean_nested_operator.create(account)

        found = clean_nested_operator.find(Account, account.id)
        assert found.observability.priority == Priority.HIGH
        assert found.observability.priority.value == 3

    def test_update_with_enum(self, clean_nested_operator):
        """Test updating a nested model containing enum fields."""
        account = Account(
            awsRegion="us-east-1",
            awsAccountId="enum-test-003",
            observability=Observability(
                provider="newrelic",
                status=Status.CREATED,
                priority=Priority.LOW,
            ),
        )

        clean_nested_operator.create(account)

        # Update the nested model with new enum values
        clean_nested_operator.update(
            account,
            observability=Observability(
                provider="newrelic",
                status=Status.ACTIVE,
                priority=Priority.HIGH,
            ),
        )

        found = clean_nested_operator.find(Account, account.id)
        assert found.observability.status == Status.ACTIVE
        assert found.observability.priority == Priority.HIGH


class TestEdgeCaseSerialization:
    """Tests for edge case type serialization."""

    @pytest.fixture
    def edge_operator(self, dynamodb_endpoint):
        """Create a MagicModelOperator for edge case tests."""
        return MagicModelOperator(
            table_name="EdgeCaseTestTable",
            endpoint_url=dynamodb_endpoint,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

    @pytest.fixture
    def clean_edge_operator(self, edge_operator):
        """Operator with cleanup after each test."""
        yield edge_operator
        type_name = EdgeCaseModel.get_type_name()
        try:
            response = edge_operator._client.query(
                TableName=edge_operator._table_name,
                KeyConditionExpression="#type = :type",
                ExpressionAttributeNames={"#type": "Type"},
                ExpressionAttributeValues={":type": {"S": type_name}},
            )
            for item in response.get("Items", []):
                edge_operator._client.delete_item(
                    TableName=edge_operator._table_name,
                    Key={"Type": item["Type"], "ID": item["ID"]},
                )
        except Exception:
            pass

    def test_uuid_field(self, clean_edge_operator):
        """Test that UUID fields serialize and deserialize correctly."""
        test_uuid = uuid4()
        model = EdgeCaseModel(
            name="uuid-test",
            correlationId=test_uuid,
        )

        clean_edge_operator.create(model)

        found = clean_edge_operator.find(EdgeCaseModel, model.id)
        assert found.correlationId == test_uuid
        assert isinstance(found.correlationId, UUID)

    def test_date_field(self, clean_edge_operator):
        """Test that date fields serialize and deserialize correctly."""
        test_date = date(2024, 6, 15)
        model = EdgeCaseModel(
            name="date-test",
            birthDate=test_date,
        )

        clean_edge_operator.create(model)

        found = clean_edge_operator.find(EdgeCaseModel, model.id)
        # Note: date may come back as datetime or string depending on serialization
        # The key is that it round-trips correctly
        assert found.birthDate == test_date

    def test_tuple_field(self, clean_edge_operator):
        """Test that tuple fields serialize correctly (Pydantic may convert to list)."""
        model = EdgeCaseModel(
            name="tuple-test",
            coordinates=(37.7749, -122.4194),
        )

        clean_edge_operator.create(model)

        found = clean_edge_operator.find(EdgeCaseModel, model.id)
        # Pydantic typically converts tuples to lists on deserialization
        # But the values should be preserved
        assert found.coordinates[0] == 37.7749
        assert found.coordinates[1] == -122.4194

    def test_deeply_nested_structure(self, clean_edge_operator):
        """Test deeply nested dict/list structures."""
        model = EdgeCaseModel(
            name="nested-test",
            metadata={
                "level1": {
                    "level2": {
                        "items": [
                            {"name": "item1", "values": [1, 2, 3]},
                            {"name": "item2", "values": [4, 5, 6]},
                        ],
                        "count": 2,
                    },
                    "active": True,
                },
                "tags": ["a", "b", "c"],
            },
        )

        clean_edge_operator.create(model)

        found = clean_edge_operator.find(EdgeCaseModel, model.id)
        assert found.metadata["level1"]["level2"]["count"] == 2
        assert found.metadata["level1"]["level2"]["items"][0]["name"] == "item1"
        assert found.metadata["level1"]["level2"]["items"][0]["values"] == [1, 2, 3]
        assert found.metadata["level1"]["active"] is True
        assert found.metadata["tags"] == ["a", "b", "c"]

    def test_list_of_tuples(self, clean_edge_operator):
        """Test list of tuples serialization."""
        model = EdgeCaseModel(
            name="list-tuples-test",
            points=[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)],
        )

        clean_edge_operator.create(model)

        found = clean_edge_operator.find(EdgeCaseModel, model.id)
        assert len(found.points) == 3
        assert found.points[0][0] == 1.0
        assert found.points[0][1] == 2.0


class TestNestedFieldWhere:
    """Tests for where() with dot notation on nested fields."""

    def test_where_nested_field_single_value(self, clean_nested_operator):
        """Test where with dot notation on a nested field."""
        a1 = Account(
            awsRegion="us-east-1",
            awsAccountId="100",
            observability=Observability(provider="datadog"),
        )
        a2 = Account(
            awsRegion="us-east-1",
            awsAccountId="200",
            observability=Observability(provider="prometheus"),
        )

        clean_nested_operator.create(a1)
        clean_nested_operator.create(a2)

        results = clean_nested_operator.where(
            Account, "observability.provider", "datadog"
        ).execute()

        assert len(results) == 1
        assert results[0].observability.provider == "datadog"

    def test_where_nested_field_multiple_values(self, clean_nested_operator):
        """Test where with dot notation and OR semantics."""
        a1 = Account(
            awsRegion="us-east-1",
            awsAccountId="300",
            observability=Observability(provider="datadog"),
        )
        a2 = Account(
            awsRegion="us-east-1",
            awsAccountId="400",
            observability=Observability(provider="prometheus"),
        )
        a3 = Account(
            awsRegion="us-east-1",
            awsAccountId="500",
            observability=Observability(provider="newrelic"),
        )

        clean_nested_operator.create(a1)
        clean_nested_operator.create(a2)
        clean_nested_operator.create(a3)

        results = clean_nested_operator.where(
            Account, "observability.provider", ["datadog", "prometheus"]
        ).execute()

        assert len(results) == 2
        providers = {r.observability.provider for r in results}
        assert providers == {"datadog", "prometheus"}

    def test_where_nested_field_chained_with_top_level(self, clean_nested_operator):
        """Test chaining a nested field where with a top-level field."""
        a1 = Account(
            awsRegion="us-east-1",
            awsAccountId="600",
            name="Account1",
            observability=Observability(provider="datadog"),
        )
        a2 = Account(
            awsRegion="us-west-2",
            awsAccountId="700",
            name="Account2",
            observability=Observability(provider="datadog"),
        )

        clean_nested_operator.create(a1)
        clean_nested_operator.create(a2)

        results = (
            clean_nested_operator.where(
                Account, "observability.provider", "datadog", chain=True
            )
            .where("awsRegion", "us-east-1")
            .execute()
        )

        assert len(results) == 1
        assert results[0].name == "Account1"

    def test_where_deeply_nested_field(self, clean_nested_operator):
        """Test where with a deeper nested path (orchestratorStackOutputs.vpcId)."""
        a1 = Account(
            awsRegion="us-east-1",
            awsAccountId="800",
            orchestratorStackOutputs=OrchestratorStackOutputs(
                vpcId="vpc-aaa",
                privateSubnetIds=[],
                publicSubnetIds=[],
            ),
        )
        a2 = Account(
            awsRegion="us-east-1",
            awsAccountId="900",
            orchestratorStackOutputs=OrchestratorStackOutputs(
                vpcId="vpc-bbb",
                privateSubnetIds=[],
                publicSubnetIds=[],
            ),
        )

        clean_nested_operator.create(a1)
        clean_nested_operator.create(a2)

        results = clean_nested_operator.where(
            Account, "orchestratorStackOutputs.vpcId", "vpc-aaa"
        ).execute()

        assert len(results) == 1
        assert results[0].orchestratorStackOutputs.vpcId == "vpc-aaa"
