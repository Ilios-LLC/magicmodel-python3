"""Integration tests for CRUD operations."""

from magicmodel import ItemNotFoundError

from .conftest import Dog


class TestCreate:
    """Tests for create operation."""

    def test_create_sets_id(self, clean_operator, dog_factory):
        """Test that create auto-generates an ID."""
        dog = dog_factory(name="Buddy")
        assert dog.id == ""

        clean_operator.create(dog)

        assert clean_operator.error is None
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

        clean_operator.create(dog)

        assert clean_operator.error is not None
        assert "already has an ID" in str(clean_operator.error)


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

    def test_find_returns_none_for_missing(self, clean_operator):
        """Test that find returns None for non-existent ID."""
        found = clean_operator.find(Dog, "non-existent-id")

        assert found is None
        assert isinstance(clean_operator.error, ItemNotFoundError)

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

        assert clean_operator.error is None
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

        assert clean_operator.error is None

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

        assert clean_operator.error is None
        assert dog.breed == "Mixed"

        found = clean_operator.find(Dog, dog.id)
        assert found is not None
        assert found.breed == "Mixed"

    def test_update_multiple_fields(self, clean_operator, dog_factory):
        """Test updating multiple fields."""
        dog = dog_factory(name="Duke", age=2)
        clean_operator.create(dog)

        clean_operator.update(dog, name="Duke Jr.", age=3, status="SENIOR")

        assert clean_operator.error is None
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


class TestDelete:
    """Tests for hard delete operation."""

    def test_delete_removes_item(self, clean_operator, dog_factory):
        """Test that delete removes the item from DynamoDB."""
        dog = dog_factory(name="Rocky")
        clean_operator.create(dog)
        dog_id = dog.id

        clean_operator.delete(dog)

        assert clean_operator.error is None

        # Clear error to check find
        clean_operator._clear_error()
        found = clean_operator.find(Dog, dog_id)

        assert found is None
        assert isinstance(clean_operator.error, ItemNotFoundError)

    def test_delete_is_idempotent(self, clean_operator, dog_factory):
        """Test that deleting a non-existent item doesn't error."""
        dog = dog_factory()
        clean_operator.create(dog)

        # Delete twice
        clean_operator.delete(dog)
        clean_operator.delete(dog)

        assert clean_operator.error is None


class TestMethodChaining:
    """Tests for fluent method chaining."""

    def test_chain_create_and_update(self, clean_operator, dog_factory):
        """Test chaining create and update operations."""
        dog = dog_factory(name="Chained")

        clean_operator.create(dog).update(dog, status="UPDATED")

        assert clean_operator.error is None
        assert dog.status == "UPDATED"

    def test_error_stops_chain(self, clean_operator, dog_factory):
        """Test that an error stops the chain."""
        dog = dog_factory()
        dog.id = "preset-id"
        dog.type = "dog"

        # This should fail because of preset ID
        clean_operator.create(dog).update(dog, name="Should not update")

        assert clean_operator.error is not None
        # Update should not have been applied
        assert dog.name != "Should not update"
