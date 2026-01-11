"""Integration tests for query operations (WhereV4 semantics)."""

from .conftest import Cat, Dog


class TestAll:
    """Tests for all() operation."""

    def test_all_returns_all_items(self, clean_operator, dog_factory):
        """Test that all() returns all items of a type."""
        dogs = [
            dog_factory(name="Dog1"),
            dog_factory(name="Dog2"),
            dog_factory(name="Dog3"),
        ]
        for dog in dogs:
            clean_operator.create(dog)

        results = clean_operator.all(Dog)

        assert len(results) == 3
        names = {d.name for d in results}
        assert names == {"Dog1", "Dog2", "Dog3"}

    def test_all_returns_empty_for_no_items(self, clean_operator):
        """Test that all() returns empty list when no items exist."""
        results = clean_operator.all(Cat)

        assert results == []

    def test_all_filters_by_type(self, clean_operator, dog_factory, cat_factory):
        """Test that all() only returns items of the specified type."""
        dog = dog_factory(name="Rex")
        cat = cat_factory(name="Whiskers")

        clean_operator.create(dog)
        clean_operator.create(cat)

        dog_results = clean_operator.all(Dog)
        cat_results = clean_operator.all(Cat)

        assert len(dog_results) == 1
        assert dog_results[0].name == "Rex"

        assert len(cat_results) == 1
        assert cat_results[0].name == "Whiskers"


class TestWhereSingleValue:
    """Tests for where() with single value (equality)."""

    def test_where_single_value_match(self, clean_operator, dog_factory):
        """Test where with single value returns matching items."""
        dog1 = dog_factory(name="Max", breed="Labrador")
        dog2 = dog_factory(name="Rex", breed="German Shepherd")
        dog3 = dog_factory(name="Luna", breed="Labrador")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        results = clean_operator.where(Dog, "breed", "Labrador").execute()

        assert len(results) == 2
        names = {d.name for d in results}
        assert names == {"Max", "Luna"}

    def test_where_single_value_no_match(self, clean_operator, dog_factory):
        """Test where with no matches returns empty list."""
        dog = dog_factory(breed="Labrador")
        clean_operator.create(dog)

        results = clean_operator.where(Dog, "breed", "Poodle").execute()

        assert results == []

    def test_where_with_integer(self, clean_operator, dog_factory):
        """Test where with integer value."""
        dog1 = dog_factory(name="Puppy", age=1)
        dog2 = dog_factory(name="Adult", age=5)
        dog3 = dog_factory(name="Senior", age=10)

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        results = clean_operator.where(Dog, "age", 5).execute()

        assert len(results) == 1
        assert results[0].name == "Adult"

    def test_where_with_boolean(self, clean_operator, dog_factory):
        """Test where with boolean value."""
        dog1 = dog_factory(name="Good", is_good_boy=True)
        dog2 = dog_factory(name="Bad", is_good_boy=False)

        clean_operator.create(dog1)
        clean_operator.create(dog2)

        results = clean_operator.where(Dog, "is_good_boy", True).execute()

        assert len(results) == 1
        assert results[0].name == "Good"


class TestWhereMultipleValues:
    """Tests for where() with multiple values (OR semantics)."""

    def test_where_list_or_semantics(self, clean_operator, dog_factory):
        """Test that list values use OR semantics."""
        dog1 = dog_factory(name="Lab", breed="Labrador")
        dog2 = dog_factory(name="Dalm", breed="Dalmatian")
        dog3 = dog_factory(name="Pood", breed="Poodle")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        results = clean_operator.where(
            Dog, "breed", ["Labrador", "Dalmatian"]
        ).execute()

        assert len(results) == 2
        breeds = {d.breed for d in results}
        assert breeds == {"Labrador", "Dalmatian"}

    def test_where_tuple_or_semantics(self, clean_operator, dog_factory):
        """Test that tuple values also use OR semantics."""
        dog1 = dog_factory(name="Active", status="ACTIVE")
        dog2 = dog_factory(name="Pending", status="PENDING")
        dog3 = dog_factory(name="Inactive", status="INACTIVE")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        results = clean_operator.where(
            Dog, "status", ("ACTIVE", "PENDING")
        ).execute()

        assert len(results) == 2
        statuses = {d.status for d in results}
        assert statuses == {"ACTIVE", "PENDING"}

    def test_where_set_or_semantics(self, clean_operator, dog_factory):
        """Test that set values also use OR semantics."""
        dog1 = dog_factory(name="Dev", environment="dev")
        dog2 = dog_factory(name="Stage", environment="staging")
        dog3 = dog_factory(name="Prod", environment="prod")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        results = clean_operator.where(
            Dog, "environment", {"dev", "staging"}
        ).execute()

        assert len(results) == 2
        envs = {d.environment for d in results}
        assert envs == {"dev", "staging"}


class TestWhereChaining:
    """Tests for chained where() calls (AND semantics)."""

    def test_chained_where_and_semantics(self, clean_operator, dog_factory):
        """Test that chained where calls use AND semantics."""
        dog1 = dog_factory(name="Lab-Dev", breed="Labrador", environment="dev")
        dog2 = dog_factory(name="Lab-Prod", breed="Labrador", environment="prod")
        dog3 = dog_factory(name="Pood-Dev", breed="Poodle", environment="dev")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)

        results = (
            clean_operator.where(Dog, "breed", "Labrador", chain=True)
            .where("environment", "dev")
            .execute()
        )

        assert len(results) == 1
        assert results[0].name == "Lab-Dev"

    def test_complex_query_or_and_combined(self, clean_operator, dog_factory):
        """Test combining OR (list) and AND (chain)."""
        dog1 = dog_factory(name="D1", breed="Labrador", status="ACTIVE", environment="dev")
        dog2 = dog_factory(name="D2", breed="Dalmatian", status="ACTIVE", environment="dev")
        dog3 = dog_factory(name="D3", breed="Labrador", status="PENDING", environment="dev")
        dog4 = dog_factory(name="D4", breed="Labrador", status="ACTIVE", environment="prod")

        clean_operator.create(dog1)
        clean_operator.create(dog2)
        clean_operator.create(dog3)
        clean_operator.create(dog4)

        # Find dogs that are (Labrador OR Dalmatian) AND ACTIVE AND in dev
        results = (
            clean_operator.where(Dog, "breed", ["Labrador", "Dalmatian"], chain=True)
            .where("status", "ACTIVE", chain=True)
            .where("environment", "dev")
            .execute()
        )

        assert len(results) == 2
        names = {d.name for d in results}
        assert names == {"D1", "D2"}

    def test_three_way_or(self, clean_operator, dog_factory):
        """Test OR with three values."""
        statuses = ["IN_PROGRESS", "QUEUED", "PENDING"]
        dogs = [
            dog_factory(name=f"Dog-{s}", status=s)
            for s in statuses + ["COMPLETED", "FAILED"]
        ]
        for dog in dogs:
            clean_operator.create(dog)

        results = clean_operator.where(
            Dog, "status", ["IN_PROGRESS", "QUEUED", "PENDING"]
        ).execute()

        assert len(results) == 3
        result_statuses = {d.status for d in results}
        assert result_statuses == {"IN_PROGRESS", "QUEUED", "PENDING"}


class TestQueryEdgeCases:
    """Tests for edge cases in query operations."""

    def test_where_no_results(self, clean_operator, dog_factory):
        """Test where with conditions that match nothing."""
        dog = dog_factory(breed="Labrador")
        clean_operator.create(dog)

        results = clean_operator.where(
            Dog, "breed", ["Poodle", "Dalmatian"]
        ).execute()

        assert results == []

    def test_where_on_empty_table(self, clean_operator):
        """Test where on table with no items of that type."""
        results = clean_operator.where(Cat, "color", "Orange").execute()

        assert results == []

    def test_multiple_where_queries(self, clean_operator, dog_factory):
        """Test running multiple independent where queries."""
        dog1 = dog_factory(name="Rex", breed="Labrador", age=3)
        dog2 = dog_factory(name="Max", breed="Poodle", age=5)

        clean_operator.create(dog1)
        clean_operator.create(dog2)

        # First query
        labs = clean_operator.where(Dog, "breed", "Labrador").execute()
        assert len(labs) == 1
        assert labs[0].name == "Rex"

        # Second query (independent)
        older = clean_operator.where(Dog, "age", 5).execute()
        assert len(older) == 1
        assert older[0].name == "Max"
