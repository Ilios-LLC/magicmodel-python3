# Comparison Operators & GSI Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add comparison operators (>=, <=, >, <, between, begins_with, !=) to the query builder, and add GSI support so range queries on indexed fields use efficient KeyConditionExpression instead of FilterExpression.

**Architecture:** Two-phase approach. Phase 1 adds operator support to `QueryBuilder` using `FilterExpression` — works on any field, no schema changes. Phase 2 adds GSI support via `__indexed__` field list on models. When a field is listed in `__indexed__`, the operator creates a GSI (partition key = `Type`, sort key = that field) and the query builder auto-routes matching conditions to `KeyConditionExpression`. No new imports needed — just `__indexed__ = ["field_name"]`.

**Tech Stack:** Python 3.10+, Pydantic 2, boto3, pytest, testcontainers (LocalStack)

---

## Part 1: Comparison Operators

### Task 1: Write test model and failing tests for comparison operators

**Files:**
- Create: `tests/test_comparison_operators.py`

**Step 1: Write the test file**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_comparison_operators.py -v --tb=short 2>&1 | head -60`
Expected: FAIL — `where()` doesn't accept operator argument yet

**Step 3: Commit**

```bash
git add tests/test_comparison_operators.py
git commit -m "test: add failing tests for comparison operators"
```

---

### Task 2: Add operator support to WhereCondition and QueryBuilder

**Files:**
- Modify: `src/magicmodel/query.py`
- Modify: `src/magicmodel/operator.py`

**Step 1: Update WhereCondition to include operator**

In `query.py`, add `VALID_OPERATORS` constant and update `WhereCondition` (around line 19-24):

```python
VALID_OPERATORS = frozenset({"=", "!=", "<>", ">", ">=", "<", "<=", "between", "begins_with"})


@dataclass
class WhereCondition:
    """Represents a single where condition."""

    field_name: str
    field_values: list[Any] = field(default_factory=list)
    operator: str = "="
```

**Step 2: Update QueryBuilder.where() to accept operator argument**

Replace the `where` method (lines 53-84) with `*args` signature:

```python
def where(
    self,
    field_name: str,
    *args: Any,
    chain: bool = False,
) -> QueryBuilder[T]:
    """
    Add a where condition.

    Args:
        field_name: The field to filter on
        *args: Either (value,) for equality or (operator, value) for comparisons.
               Operators: =, !=, >, >=, <, <=, between, begins_with
        chain: If True, more conditions follow; if False, ready to execute

    Returns:
        Self for method chaining
    """
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
```

**Step 3: Update _execute_query() condition-building loop**

Replace lines 166-201 (the condition-building `for` loop) with operator-aware logic:

```python
    # Add field conditions
    for i, condition in enumerate(self._conditions):
        # Handle dot notation for nested fields
        field_parts = condition.field_name.split(".")
        if len(field_parts) > 1:
            path_aliases = []
            for j, part in enumerate(field_parts):
                alias = f"#f{i}_{j}"
                db_name = self._resolve_db_field_name(part, j, field_parts)
                attr_names[alias] = db_name
                path_aliases.append(alias)
            field_path = ".".join(path_aliases)
        else:
            field_alias = f"#f{i}"
            db_name = self._resolve_db_field_name(
                condition.field_name, 0, [condition.field_name]
            )
            attr_names[field_alias] = db_name
            field_path = field_alias

        op = condition.operator

        if op == "=" and len(condition.field_values) > 1:
            # Multiple values — IN operator (existing behavior)
            value_aliases = []
            for j, val in enumerate(condition.field_values):
                value_alias = f":v{i}_{j}"
                attr_values[value_alias] = self._operator._serializer.serialize_value(val)
                value_aliases.append(value_alias)
            in_clause = ", ".join(value_aliases)
            filter_parts.append(f"{field_path} IN ({in_clause})")
        elif op == "between":
            start_alias = f":v{i}_start"
            end_alias = f":v{i}_end"
            attr_values[start_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            attr_values[end_alias] = self._operator._serializer.serialize_value(
                condition.field_values[1]
            )
            filter_parts.append(f"{field_path} BETWEEN {start_alias} AND {end_alias}")
        elif op == "begins_with":
            value_alias = f":v{i}"
            attr_values[value_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            filter_parts.append(f"begins_with({field_path}, {value_alias})")
        elif op in ("!=", "<>"):
            value_alias = f":v{i}"
            attr_values[value_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            filter_parts.append(f"{field_path} <> {value_alias}")
        else:
            # =, >, >=, <, <=
            value_alias = f":v{i}"
            attr_values[value_alias] = self._operator._serializer.serialize_value(
                condition.field_values[0]
            )
            filter_parts.append(f"{field_path} {op} {value_alias}")
```

**Step 4: Update MagicModelOperator.where() to pass through *args**

In `operator.py`, replace the `where` method (lines 408-436):

```python
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
    builder: QueryBuilder[T] = QueryBuilder(
        operator=self,
        model_class=model_class,
    )
    return builder.where(field_name, *args, chain=chain)
```

**Step 5: Run comparison operator tests**

Run: `python -m pytest tests/test_comparison_operators.py -v`
Expected: ALL PASS

**Step 6: Run full test suite for regressions**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add src/magicmodel/query.py src/magicmodel/operator.py
git commit -m "feat: add comparison operators (>=, <=, >, <, between, begins_with, !=) to query builder"
```

---

## Part 2: GSI Support

### Task 3: Write failing tests for GSI support

**Files:**
- Create: `tests/test_gsi.py`

**Step 1: Write the GSI test file**

Note: GSI declaration uses `__indexed__` — a simple list of field names on the model.
No new imports needed beyond `MagicModel`.

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gsi.py -v --tb=short 2>&1 | head -40`
Expected: FAIL — `ensure_indexes` doesn't exist yet

**Step 3: Commit**

```bash
git add tests/test_gsi.py
git commit -m "test: add failing tests for GSI support"
```

---

### Task 4: Implement auto-indexing on MagicModelOperator

**Files:**
- Modify: `src/magicmodel/operator.py`

**Step 1: Add `_checked_indexes` set to `__init__`**

In `__init__`, after `self._deserializer = Deserializer()`, add:

```python
self._checked_indexes: set[type] = set()
```

**Step 2: Add helper methods and ensure_indexes()**

Add these methods to `MagicModelOperator`, after the table management section (after `_create_table`):

```python
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
            waiter = self._client.get_waiter("table_exists")
            waiter.wait(TableName=self._table_name)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ValidationException":
                raise MagicModelError(
                    f"Failed to create index {index_name}: {e}"
                ) from e

    return self
```

**Step 3: Add `_auto_ensure_indexes` calls to CRUD and query methods**

Add `self._auto_ensure_indexes(type(model))` as the first line in:
- `create()` — `self._auto_ensure_indexes(type(model))`
- `save()` — `self._auto_ensure_indexes(type(model))`

Add `self._auto_ensure_indexes(model_class)` as the first line in:
- `find()` — `self._auto_ensure_indexes(model_class)`
- `all()` — `self._auto_ensure_indexes(model_class)`
- `where()` — `self._auto_ensure_indexes(model_class)`

**Step 4: Run ensure_indexes tests**

Run: `python -m pytest tests/test_gsi.py::TestEnsureIndexes -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/magicmodel/operator.py
git commit -m "feat: auto-create GSIs on first use of model with __indexed__"
```

---

### Task 5: Update QueryBuilder to auto-route to GSIs

**Files:**
- Modify: `src/magicmodel/query.py`

**Step 1: Add _resolve_field_path helper method**

Add to `QueryBuilder`, before `_execute_query`:

```python
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
```

**Step 2: Add _build_condition_expr helper method**

```python
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
```

**Step 3: Add _find_gsi_match method**

```python
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

    indexed_set = set(indexed_fields)

    for field_name in indexed_fields:
        gsi_conds = [c for c in self._conditions if c.field_name == field_name]
        if gsi_conds:
            remaining = [c for c in self._conditions if c.field_name != field_name]
            return f"gsi_{field_name}", gsi_conds, remaining

    return None, [], list(self._conditions)
```

**Step 4: Refactor _execute_query() to support GSI routing**

Replace the entire `_execute_query` method:

```python
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

    response = self._operator._client.query(**query_kwargs)

    return [
        self._operator._deserializer.deserialize(item, self._model_class)
        for item in response.get("Items", [])
    ]
```

**Step 5: Run all GSI tests**

Run: `python -m pytest tests/test_gsi.py -v`
Expected: ALL PASS

**Step 6: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS — no regressions

**Step 7: Commit**

```bash
git add src/magicmodel/query.py
git commit -m "feat: auto-route queries to GSI when indexed field is queried"
```

---

### Task 6: Final verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 2: Commit if any remaining changes**

```bash
git add -A
git commit -m "feat: comparison operators and GSI support for efficient range queries"
```

---

## User-Facing API Summary

### Without indexing (works on any field, less efficient at scale):
```python
class Transaction(MagicModel):
    account_id: str
    transaction_date: datetime
    amount: float

# Range query — uses FilterExpression (reads all Transactions, filters server-side)
results = (
    mm.where(Transaction, "transaction_date", ">=", start_date, chain=True)
      .where("transaction_date", "<=", end_date)
      .execute()
)
```

### With indexing (add when you need efficiency):
```python
class Transaction(MagicModel):
    __indexed__ = ["transaction_date"]   # <-- just add this line

    account_id: str
    transaction_date: datetime
    amount: float

# That's it. GSI is created automatically on first create() or where().
# Same query code — automatically uses GSI, only reads matching date range.
results = (
    mm.where(Transaction, "transaction_date", ">=", start_date, chain=True)
      .where("transaction_date", "<=", end_date)
      .execute()
)
```

The query code never changes. Just add `__indexed__` — everything else is automatic.
