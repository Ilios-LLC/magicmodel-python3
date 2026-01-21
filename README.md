# MagicModel

A Python DynamoDB ORM inspired by [magicmodel-go](https://github.com/Ilios-LLC/magicmodel-go).

## Features

- **Pydantic-based models** with automatic validation and serialization
- **Composite key schema** (Type + ID) allowing multiple model types in one table
- **Auto-generated fields**: ID (UUID), Type (from class name), timestamps
- **Fluent API** with method chaining
- **Soft delete** support with automatic query filtering
- **WhereV4 query semantics**: OR (list values) and AND (chained calls)
- **Table auto-creation** on first use

## Installation

```bash
# Install from GitHub
pip install git+https://github.com/Ilios-LLC/magicmodel-python3.git

# Or with uv
uv add git+https://github.com/Ilios-LLC/magicmodel-python3.git

# Install from local clone
git clone https://github.com/Ilios-LLC/magicmodel-python3.git
cd magicmodel-python3
pip install .

# Or install in editable mode for development
pip install -e .
```

## Quick Start

```python
from magicmodel import MagicModel, MagicModelOperator

# Define your model
class Dog(MagicModel):
    name: str
    breed: str
    age: int = 0

# Create operator (auto-creates table if needed)
mm = MagicModelOperator(table_name="MyTable")

# Create
dog = Dog(name="Buddy", breed="Labrador", age=3)
mm.create(dog)
print(f"Created dog with ID: {dog.id}")

# Find by ID
found = mm.find(Dog, dog.id)
print(f"Found: {found.name}")

# Update
mm.update(dog, age=4, breed="Golden Retriever")

# Query with WhereV4 semantics
# Single value (equality)
labs = mm.where(Dog, "breed", "Labrador").execute()

# Multiple values (OR)
results = mm.where(Dog, "breed", ["Labrador", "Dalmatian"]).execute()

# Chained conditions (AND)
results = (mm.where(Dog, "breed", "Labrador", chain=True)
             .where("age", 3)
             .execute())

# Get all (excludes soft-deleted)
all_dogs = mm.all(Dog)

# Soft delete
mm.soft_delete(dog)
assert dog.is_deleted  # True

# Hard delete
mm.delete(dog)
```

## Using with LocalStack

For local development or testing:

```python
mm = MagicModelOperator(
    table_name="TestTable",
    endpoint_url="http://localhost:4566",
    region_name="us-east-1",
)
```

## Model Fields

All models automatically have these fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Auto-generated UUID |
| `type` | str | Snake_case of class name |
| `created_at` | datetime | Set on create |
| `updated_at` | datetime | Updated on every save/update |
| `deleted_at` | datetime \| None | Set on soft delete |

## Error Handling

MagicModel uses native Python exceptions for error handling:

```python
from magicmodel import ItemNotFoundError, MagicModelError

mm = MagicModelOperator(table_name="MyTable")

# Exceptions are raised on failure
try:
    mm.create(dog)
except MagicModelError as e:
    print(f"Create failed: {e}")

# Handle specific exceptions
try:
    dog = mm.find(Dog, "non-existent-id")
except ItemNotFoundError:
    print("Dog not found")

# Method chaining stops naturally on error
try:
    mm.create(dog).update(dog, name="Rex").save(dog)
except MagicModelError as e:
    print(f"Operation failed: {e}")
```

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Type check
uv run mypy src/

# Lint
uv run ruff check src/ tests/
```

## License

MIT
