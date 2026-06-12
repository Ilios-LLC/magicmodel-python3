"""Tests for Global Secondary Index support."""

from datetime import datetime, timezone, timedelta
from typing import ClassVar

import pytest

from magicmodel import MagicModel, MagicModelOperator


class IndexedTransaction(MagicModel):
    __indexed__: ClassVar[list[str]] = ["transaction_date"]

    account_id: str
    transaction_date: datetime
    amount: float
    description: str = ""


class UnindexedTransaction(MagicModel):
    """Same fields, no index — for comparison."""

    account_id: str
    transaction_date: datetime
    amount: float
    description: str = ""


class MultiIndexModel(MagicModel):
    __indexed__: ClassVar[list[str]] = ["created_date", "category"]

    name: str
    created_date: datetime
    category: str


@pytest.fixture
def gsi_operator(dynamodb_endpoint):
    return MagicModelOperator(
        table_name="GSITestTable",
        endpoint_url=dynamodb_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def clean_gsi_operator(gsi_operator):
    yield gsi_operator
    _cleanup(gsi_operator, IndexedTransaction)
    _cleanup(gsi_operator, UnindexedTransaction)
    _cleanup(gsi_operator, MultiIndexModel)


def _cleanup(operator, model_class):
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
                Key={"Type": item["Type"], "ID": item["ID"]},
            )
    except Exception:
        pass


def _seed_indexed_transactions(operator):
    """Create 5 transactions across dates."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    txns = []
    for i in range(5):
        txn = IndexedTransaction(
            account_id="acct-1",
            transaction_date=base + timedelta(days=i * 10),
            amount=100.0 * (i + 1),
            description=f"txn-{i}",
        )
        operator.create(txn)
        txns.append(txn)
    return txns


class TestIndexedDeclaration:
    def test_model_has_indexed_fields(self):
        assert IndexedTransaction.__indexed__ == ["transaction_date"]

    def test_model_multiple_indexed_fields(self):
        assert MultiIndexModel.__indexed__ == ["created_date", "category"]

    def test_model_without_indexed(self):
        assert not hasattr(UnindexedTransaction, "__indexed__")


class TestEnsureIndexes:
    def test_ensure_indexes_creates_gsi(self, clean_gsi_operator):
        """ensure_indexes should create GSIs for __indexed__ fields."""
        clean_gsi_operator.ensure_indexes(IndexedTransaction)
        desc = clean_gsi_operator._client.describe_table(
            TableName=clean_gsi_operator._table_name
        )
        gsi_names = [
            g["IndexName"]
            for g in desc["Table"].get("GlobalSecondaryIndexes", [])
        ]
        assert "gsi_transaction_date" in gsi_names

    def test_ensure_indexes_idempotent(self, clean_gsi_operator):
        """Calling ensure_indexes twice should not error."""
        clean_gsi_operator.ensure_indexes(IndexedTransaction)
        clean_gsi_operator.ensure_indexes(IndexedTransaction)

    def test_ensure_indexes_multiple(self, clean_gsi_operator):
        """Model with multiple indexed fields should create all GSIs."""
        clean_gsi_operator.ensure_indexes(MultiIndexModel)
        desc = clean_gsi_operator._client.describe_table(
            TableName=clean_gsi_operator._table_name
        )
        gsi_names = {
            g["IndexName"]
            for g in desc["Table"].get("GlobalSecondaryIndexes", [])
        }
        assert "gsi_created_date" in gsi_names
        assert "gsi_category" in gsi_names

    def test_ensure_indexes_no_indexed_fields(self, clean_gsi_operator):
        """Model without __indexed__ should be a no-op."""
        clean_gsi_operator.ensure_indexes(UnindexedTransaction)


class TestGSIQueryRouting:
    def test_range_query_uses_gsi(self, clean_gsi_operator):
        """Range query on indexed field — GSI created automatically on first create()."""
        _seed_indexed_transactions(clean_gsi_operator)

        start = datetime(2026, 1, 11, tzinfo=timezone.utc)
        end = datetime(2026, 1, 31, tzinfo=timezone.utc)
        results = clean_gsi_operator.where(
            IndexedTransaction, "transaction_date", "between", [start, end]
        ).execute()
        assert len(results) == 3
        for r in results:
            assert start <= r.transaction_date <= end

    def test_gte_query_on_gsi(self, clean_gsi_operator):
        _seed_indexed_transactions(clean_gsi_operator)

        cutoff = datetime(2026, 1, 21, tzinfo=timezone.utc)
        results = clean_gsi_operator.where(
            IndexedTransaction, "transaction_date", ">=", cutoff
        ).execute()
        assert len(results) == 3

    def test_gsi_query_with_additional_filter(self, clean_gsi_operator):
        """GSI sort key in KeyCondition + extra field in FilterExpression."""
        _seed_indexed_transactions(clean_gsi_operator)

        cutoff = datetime(2026, 1, 21, tzinfo=timezone.utc)
        results = (
            clean_gsi_operator.where(
                IndexedTransaction, "transaction_date", ">=", cutoff, chain=True
            )
            .where("amount", ">=", 400.0)
            .execute()
        )
        # >= Jan 21 gives amounts 300, 400, 500; >= 400 filters to 2
        assert len(results) == 2

    def test_equality_on_non_indexed_field_stays_filter(self, clean_gsi_operator):
        """Equality on non-indexed field should still use FilterExpression."""
        _seed_indexed_transactions(clean_gsi_operator)

        results = clean_gsi_operator.where(
            IndexedTransaction, "account_id", "acct-1"
        ).execute()
        assert len(results) == 5

    def test_no_index_still_works(self, clean_gsi_operator):
        """Model without __indexed__ still supports comparison via FilterExpression."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(3):
            txn = UnindexedTransaction(
                account_id="acct-1",
                transaction_date=base + timedelta(days=i * 10),
                amount=100.0 * (i + 1),
            )
            clean_gsi_operator.create(txn)

        results = clean_gsi_operator.where(
            UnindexedTransaction, "amount", ">=", 200.0
        ).execute()
        assert len(results) == 2
