"""Integration tests for nested/complex model serialization."""

import pytest
from pydantic import BaseModel

from magicmodel import MagicModel, MagicModelOperator


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
