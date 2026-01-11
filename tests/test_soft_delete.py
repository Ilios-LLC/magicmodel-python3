"""Integration tests for soft delete functionality."""

from .conftest import Dog


class TestSoftDelete:
    """Tests for soft delete operation."""

    def test_soft_delete_sets_deleted_at(self, clean_operator, dog_factory):
        """Test that soft_delete sets the deleted_at timestamp."""
        dog = dog_factory(name="Fluffy")
        clean_operator.create(dog)

        assert dog.deleted_at is None

        clean_operator.soft_delete(dog)

        assert clean_operator.error is None
        assert dog.deleted_at is not None

    def test_soft_delete_item_still_exists(self, clean_operator, dog_factory):
        """Test that soft-deleted item still exists in DynamoDB."""
        dog = dog_factory(name="Shadow")
        clean_operator.create(dog)

        clean_operator.soft_delete(dog)

        # Direct find should still return the item
        found = clean_operator.find(Dog, dog.id)

        assert found is not None
        assert found.id == dog.id
        assert found.deleted_at is not None

    def test_soft_deleted_excluded_from_all(self, clean_operator, dog_factory):
        """Test that soft-deleted items are excluded from all() query."""
        # Create multiple dogs
        dog1 = dog_factory(name="Active1")
        dog2 = dog_factory(name="Active2")
        dog3 = dog_factory(name="Deleted")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        # Soft delete one
        clean_operator.soft_delete(dog3)

        # Query all
        all_dogs = clean_operator.all(Dog)

        # Should only get the non-deleted dogs
        assert len(all_dogs) == 2
        names = {d.name for d in all_dogs}
        assert "Active1" in names
        assert "Active2" in names
        assert "Deleted" not in names

    def test_soft_delete_updates_timestamp(self, clean_operator, dog_factory):
        """Test that soft_delete updates the updated_at timestamp."""
        dog = dog_factory()
        clean_operator.create(dog)
        original_updated_at = dog.updated_at

        clean_operator.soft_delete(dog)

        assert dog.updated_at > original_updated_at

    def test_is_deleted_property(self, clean_operator, dog_factory):
        """Test the is_deleted property."""
        dog = dog_factory()
        clean_operator.create(dog)

        assert dog.is_deleted is False

        clean_operator.soft_delete(dog)

        assert dog.is_deleted is True

    def test_soft_deleted_excluded_from_where(self, clean_operator, dog_factory):
        """Test that soft-deleted items are excluded from where queries."""
        # Create dogs with same breed
        dog1 = dog_factory(name="Buddy1", breed="Labrador")
        dog2 = dog_factory(name="Buddy2", breed="Labrador")
        dog3 = dog_factory(name="Buddy3", breed="Labrador")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        # Soft delete one
        clean_operator.soft_delete(dog2)

        # Query by breed
        results = clean_operator.where(Dog, "breed", "Labrador").execute()

        # Should only get the non-deleted dogs
        assert len(results) == 2
        ids = {d.id for d in results}
        assert dog1.id in ids
        assert dog3.id in ids
        assert dog2.id not in ids
