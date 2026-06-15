"""Integration tests for CRUD operations."""

import pytest

from magicmodel import ItemNotFoundError, MagicModelError, MagicModel

from .conftest import Dog


class EventLog(MagicModel):
    """Model with a string field that looks like a date."""

    event_name: str
    date_label: str  # intentionally str, not datetime


class TestCreate:
    """Tests for create operation."""

    def test_create_sets_id(self, clean_operator, dog_factory):
        """Test that create auto-generates an ID."""
        dog = dog_factory(name="Buddy")
        assert dog.id == ""

        clean_operator.create(dog)

        assert dog.id != ""
        assert len(dog.id) == 36  # UUID format

    def test_create_sets_type(self, clean_operator, dog_factory):
        """Test that create sets the Type field to snake_case class name."""
        dog = dog_factory()

        clean_operator.create(dog)

        assert dog.type == "dog"

    def test_create_sets_timestamps(self, clean_operator, dog_factory):
        """Test that create sets created_at and updated_at."""
        dog = dog_factory()

        clean_operator.create(dog)

        assert dog.created_at is not None
        assert dog.updated_at is not None
        assert dog.created_at == dog.updated_at

    def test_create_fails_if_already_has_id(self, clean_operator, dog_factory):
        """Test that create fails if model already has an ID."""
        dog = dog_factory()
        dog.id = "existing-id"
        dog.type = "dog"

        with pytest.raises(MagicModelError, match="already has an ID"):
            clean_operator.create(dog)


class TestFind:
    """Tests for find operation."""

    def test_find_returns_model(self, clean_operator, dog_factory):
        """Test that find returns the correct model."""
        dog = dog_factory(name="Rex", breed="German Shepherd")
        clean_operator.create(dog)
        dog_id = dog.id

        found = clean_operator.find(Dog, dog_id)

        assert found is not None
        assert found.id == dog_id
        assert found.name == "Rex"
        assert found.breed == "German Shepherd"

    def test_find_raises_for_missing(self, clean_operator):
        """Test that find raises ItemNotFoundError for non-existent ID."""
        with pytest.raises(ItemNotFoundError):
            clean_operator.find(Dog, "non-existent-id")

    def test_find_preserves_all_fields(self, clean_operator, dog_factory):
        """Test that find preserves all model fields."""
        dog = dog_factory(
            name="Max",
            breed="Dalmatian",
            age=5,
            status="RETIRED",
            environment="prod",
            is_good_boy=True,
        )
        clean_operator.create(dog)

        found = clean_operator.find(Dog, dog.id)

        assert found is not None
        assert found.name == "Max"
        assert found.breed == "Dalmatian"
        assert found.age == 5
        assert found.status == "RETIRED"
        assert found.environment == "prod"
        assert found.is_good_boy is True


class TestSave:
    """Tests for save (upsert) operation."""

    def test_save_creates_new(self, clean_operator, dog_factory):
        """Test that save creates a new item if ID is empty."""
        dog = dog_factory(name="Luna")

        clean_operator.save(dog)

        assert dog.id != ""

        found = clean_operator.find(Dog, dog.id)
        assert found is not None
        assert found.name == "Luna"

    def test_save_updates_existing(self, clean_operator, dog_factory):
        """Test that save updates an existing item."""
        dog = dog_factory(name="Spot")
        clean_operator.create(dog)
        original_created_at = dog.created_at

        # Modify and save
        dog.name = "Spot Jr."
        dog.age = 4
        clean_operator.save(dog)

        found = clean_operator.find(Dog, dog.id)
        assert found is not None
        assert found.name == "Spot Jr."
        assert found.age == 4
        # created_at should be preserved
        assert found.created_at == original_created_at


class TestUpdate:
    """Tests for update operation."""

    def test_update_single_field(self, clean_operator, dog_factory):
        """Test updating a single field."""
        dog = dog_factory(name="Charlie", breed="Beagle")
        clean_operator.create(dog)

        clean_operator.update(dog, breed="Mixed")

        assert dog.breed == "Mixed"

        found = clean_operator.find(Dog, dog.id)
        assert found is not None
        assert found.breed == "Mixed"

    def test_update_multiple_fields(self, clean_operator, dog_factory):
        """Test updating multiple fields."""
        dog = dog_factory(name="Duke", age=2)
        clean_operator.create(dog)

        clean_operator.update(dog, name="Duke Jr.", age=3, status="SENIOR")

        assert dog.name == "Duke Jr."
        assert dog.age == 3
        assert dog.status == "SENIOR"

    def test_update_updates_timestamp(self, clean_operator, dog_factory):
        """Test that update changes updated_at."""
        dog = dog_factory()
        clean_operator.create(dog)
        original_updated_at = dog.updated_at

        clean_operator.update(dog, name="Updated")

        assert dog.updated_at > original_updated_at

    def test_update_field_to_none_removes_attribute(self, clean_operator):
        """Updating an Optional field to None should remove the attribute, not write NULL."""
        from magicmodel import MagicModel

        class Task(MagicModel):
            title: str
            assignee: str | None = None

        event = Task(title="do thing", assignee="alice")
        clean_operator.create(event)

        clean_operator.update(event, assignee=None)
        assert event.assignee is None

        found = clean_operator.find(Task, event.id)
        assert found.assignee is None

        # Verify the attribute was actually removed (not set to NULL)
        raw = clean_operator._client.get_item(
            TableName=clean_operator._table_name,
            Key={"Type": {"S": "task"}, "ID": {"S": event.id}},
        )
        assert "assignee" not in raw["Item"]


class TestDelete:
    """Tests for hard delete operation."""

    def test_delete_removes_item(self, clean_operator, dog_factory):
        """Test that delete removes the item from DynamoDB."""
        dog = dog_factory(name="Rocky")
        clean_operator.create(dog)
        dog_id = dog.id

        clean_operator.delete(dog)

        with pytest.raises(ItemNotFoundError):
            clean_operator.find(Dog, dog_id)

    def test_delete_is_idempotent(self, clean_operator, dog_factory):
        """Test that deleting a non-existent item doesn't error."""
        dog = dog_factory()
        clean_operator.create(dog)

        # Delete twice - should not raise
        clean_operator.delete(dog)
        clean_operator.delete(dog)


class TestMethodChaining:
    """Tests for fluent method chaining."""

    def test_chain_create_and_update(self, clean_operator, dog_factory):
        """Test chaining create and update operations."""
        dog = dog_factory(name="Chained")

        clean_operator.create(dog).update(dog, status="UPDATED")

        assert dog.status == "UPDATED"

    def test_error_stops_chain(self, clean_operator, dog_factory):
        """Test that an error stops the chain."""
        dog = dog_factory()
        dog.id = "preset-id"
        dog.type = "dog"

        # This should fail because of preset ID and stop the chain
        with pytest.raises(MagicModelError, match="already has an ID"):
            clean_operator.create(dog).update(dog, name="Should not update")

        # Update should not have been applied
        assert dog.name != "Should not update"


class TestStringDateRoundTrip:
    """Regression: deserializer must not coerce date-like strings to datetime."""

    def test_date_string_stays_string(self, clean_operator):
        """A str field containing '2024-06-15' should round-trip as str, not datetime."""
        event = EventLog(event_name="launch", date_label="2024-06-15")
        clean_operator.create(event)

        found = clean_operator.find(EventLog, event.id)
        assert found.date_label == "2024-06-15"
        assert isinstance(found.date_label, str)

    def test_iso_datetime_string_stays_string(self, clean_operator):
        """A str field containing a full ISO datetime should also stay str."""
        event = EventLog(event_name="deploy", date_label="2024-06-15T10:30:00+00:00")
        clean_operator.create(event)

        found = clean_operator.find(EventLog, event.id)
        assert found.date_label == "2024-06-15T10:30:00+00:00"
        assert isinstance(found.date_label, str)
