"""Tests for comparison operators in where queries."""

from datetime import datetime, timezone, timedelta

import pytest

from magicmodel import MagicModel, MagicModelOperator


class Transaction(MagicModel):
    account_id: str
    transaction_date: datetime
    amount: float
    description: str = ""


@pytest.fixture
def txn_operator(dynamodb_endpoint):
    return MagicModelOperator(
        table_name="ComparisonTestTable",
        endpoint_url=dynamodb_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def clean_txn_operator(txn_operator):
    yield txn_operator
    _cleanup(txn_operator, Transaction)


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


def _seed_transactions(operator):
    """Create 5 transactions across different dates."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    txns = []
    for i in range(5):
        txn = Transaction(
            account_id="acct-1",
            transaction_date=base + timedelta(days=i * 10),
            amount=100.0 * (i + 1),
            description=f"txn-{i}",
        )
        operator.create(txn)
        txns.append(txn)
    return txns  # dates: Jan 1, Jan 11, Jan 21, Jan 31, Feb 10


class TestGreaterThanOrEqual:
    def test_gte_filters_correctly(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        cutoff = datetime(2026, 1, 21, tzinfo=timezone.utc)
        results = clean_txn_operator.where(
            Transaction, "transaction_date", ">=", cutoff
        ).execute()
        assert len(results) == 3
        for r in results:
            assert r.transaction_date >= cutoff


class TestLessThanOrEqual:
    def test_lte_filters_correctly(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        cutoff = datetime(2026, 1, 21, tzinfo=timezone.utc)
        results = clean_txn_operator.where(
            Transaction, "transaction_date", "<=", cutoff
        ).execute()
        assert len(results) == 3
        for r in results:
            assert r.transaction_date <= cutoff


class TestGreaterThan:
    def test_gt_filters_correctly(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        cutoff = datetime(2026, 1, 21, tzinfo=timezone.utc)
        results = clean_txn_operator.where(
            Transaction, "transaction_date", ">", cutoff
        ).execute()
        assert len(results) == 2
        for r in results:
            assert r.transaction_date > cutoff


class TestLessThan:
    def test_lt_filters_correctly(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        cutoff = datetime(2026, 1, 21, tzinfo=timezone.utc)
        results = clean_txn_operator.where(
            Transaction, "transaction_date", "<", cutoff
        ).execute()
        assert len(results) == 2
        for r in results:
            assert r.transaction_date < cutoff


class TestBetween:
    def test_between_inclusive(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        start = datetime(2026, 1, 11, tzinfo=timezone.utc)
        end = datetime(2026, 1, 31, tzinfo=timezone.utc)
        results = clean_txn_operator.where(
            Transaction, "transaction_date", "between", [start, end]
        ).execute()
        assert len(results) == 3
        for r in results:
            assert start <= r.transaction_date <= end


class TestNotEqual:
    def test_ne_filters_correctly(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        target_amount = 300.0
        results = clean_txn_operator.where(
            Transaction, "amount", "!=", target_amount
        ).execute()
        assert len(results) == 4
        for r in results:
            assert r.amount != target_amount


class TestBeginsWith:
    def test_begins_with_string(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        results = clean_txn_operator.where(
            Transaction, "description", "begins_with", "txn-"
        ).execute()
        assert len(results) == 5

    def test_begins_with_partial(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        results = clean_txn_operator.where(
            Transaction, "description", "begins_with", "txn-0"
        ).execute()
        assert len(results) == 1
        assert results[0].description == "txn-0"


class TestComparisonWithChaining:
    def test_gte_and_lte_date_range(self, clean_txn_operator):
        """The cash flow use case: all transactions between date X and Y."""
        txns = _seed_transactions(clean_txn_operator)
        start = datetime(2026, 1, 11, tzinfo=timezone.utc)
        end = datetime(2026, 1, 31, tzinfo=timezone.utc)
        results = (
            clean_txn_operator.where(
                Transaction, "transaction_date", ">=", start, chain=True
            )
            .where("transaction_date", "<=", end)
            .execute()
        )
        assert len(results) == 3
        for r in results:
            assert start <= r.transaction_date <= end

    def test_comparison_with_equality_filter(self, clean_txn_operator):
        """Range on date + equality on another field."""
        txns = _seed_transactions(clean_txn_operator)
        cutoff = datetime(2026, 1, 21, tzinfo=timezone.utc)
        results = (
            clean_txn_operator.where(
                Transaction, "transaction_date", ">=", cutoff, chain=True
            )
            .where("account_id", "acct-1")
            .execute()
        )
        assert len(results) == 3


class TestComparisonWithNumericValues:
    def test_gte_on_amount(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        results = clean_txn_operator.where(
            Transaction, "amount", ">=", 300.0
        ).execute()
        assert len(results) == 3

    def test_between_on_amount(self, clean_txn_operator):
        txns = _seed_transactions(clean_txn_operator)
        results = clean_txn_operator.where(
            Transaction, "amount", "between", [200.0, 400.0]
        ).execute()
        assert len(results) == 3


class TestInvalidOperator:
    def test_invalid_operator_raises(self, clean_txn_operator):
        with pytest.raises(Exception, match="[Uu]nsupported operator"):
            clean_txn_operator.where(
                Transaction, "amount", "LIKE", "foo"
            ).execute()

    def test_between_requires_two_values(self, clean_txn_operator):
        with pytest.raises(Exception, match="[Bb]etween.*two"):
            clean_txn_operator.where(
                Transaction, "amount", "between", 100.0
            ).execute()
