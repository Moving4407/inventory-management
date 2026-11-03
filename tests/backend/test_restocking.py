"""
Tests for restocking endpoints (recommendations, order submission, submitted orders).
"""
import pytest

import mock_data


@pytest.fixture(autouse=True)
def reset_submitted_orders():
    """Submitted orders live in a shared in-memory list, so clear it around every test
    to keep tests independent of execution order."""
    mock_data.submitted_orders.clear()
    yield
    mock_data.submitted_orders.clear()


def get_recommendations(client, budget):
    response = client.get(f"/api/restocking/recommendations?budget={budget}")
    assert response.status_code == 200
    return response.json()


class TestRestockRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_structure(self, client):
        data = get_recommendations(client, 25000)
        for key in ("budget", "items", "total_cost", "remaining_budget", "lead_time_days"):
            assert key in data
        assert len(data["items"]) > 0
        for field in ("item_sku", "item_name", "trend", "demand_gap", "quantity",
                      "unit_cost", "line_total", "lead_time_days", "supplier_name"):
            assert field in data["items"][0]

    @pytest.mark.parametrize("budget", [0, 1, 500, 5000, 25000, 100000, 1000000])
    def test_never_exceeds_budget(self, client, budget):
        data = get_recommendations(client, budget)
        assert data["total_cost"] <= budget
        assert data["remaining_budget"] >= 0
        assert data["total_cost"] + data["remaining_budget"] == pytest.approx(budget, abs=0.01)

    def test_zero_budget_returns_nothing(self, client):
        data = get_recommendations(client, 0)
        assert data["items"] == []
        assert data["total_cost"] == 0
        assert data["lead_time_days"] == 0

    def test_negative_budget_rejected(self, client):
        response = client.get("/api/restocking/recommendations?budget=-1")
        assert response.status_code == 422

    def test_missing_budget_rejected(self, client):
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 422

    def test_only_items_with_demand_gap(self, client):
        data = get_recommendations(client, 1000000)
        for item in data["items"]:
            assert item["demand_gap"] > 0
            assert 0 < item["quantity"] <= item["demand_gap"]
        # MTR-304 has decreasing forecast demand so it must never be recommended
        assert "MTR-304" not in [i["item_sku"] for i in data["items"]]

    def test_rising_trend_and_largest_gap_first(self, client):
        data = get_recommendations(client, 1000000)
        priority = {"increasing": 0, "stable": 1, "decreasing": 2}
        keys = [(priority[i["trend"]], -i["demand_gap"]) for i in data["items"]]
        assert keys == sorted(keys)

    def test_large_budget_covers_every_gap(self, client):
        data = get_recommendations(client, 1000000)
        assert all(i["quantity"] == i["demand_gap"] for i in data["items"])

    def test_small_budget_partially_funds_top_item(self, client):
        # Budget buys only part of the first-ranked item
        data = get_recommendations(client, 1000)
        first = data["items"][0]
        assert first["quantity"] < first["demand_gap"]

    def test_line_totals_and_lead_time(self, client):
        data = get_recommendations(client, 25000)
        for item in data["items"]:
            assert item["line_total"] == pytest.approx(item["quantity"] * item["unit_cost"], abs=0.01)
        assert data["lead_time_days"] == max(i["lead_time_days"] for i in data["items"])


class TestCreateRestockOrder:
    """Test suite for POST /api/restocking/orders."""

    def test_create_order(self, client):
        recs = get_recommendations(client, 25000)
        payload = {
            "budget": 25000,
            "items": [{"item_sku": i["item_sku"], "quantity": i["quantity"]} for i in recs["items"]],
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["total_cost"] == pytest.approx(recs["total_cost"], abs=0.01)
        # Lead time of the order is that of its slowest item
        assert order["lead_time_days"] == recs["lead_time_days"]
        assert order["expected_delivery_date"] > order["created_date"]
        assert len(order["items"]) == len(recs["items"])

    def test_prices_come_from_server(self, client):
        """The request has no price field; cost is always computed from forecast data."""
        recs = get_recommendations(client, 100000)
        item = recs["items"][0]
        response = client.post("/api/restocking/orders", json={
            "budget": 100000,
            "items": [{"item_sku": item["item_sku"], "quantity": 1, "unit_cost": 0.01}],
        })
        assert response.status_code == 201
        assert response.json()["items"][0]["unit_cost"] == item["unit_cost"]

    def test_empty_order_rejected(self, client):
        response = client.post("/api/restocking/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_unknown_sku_rejected(self, client):
        response = client.post("/api/restocking/orders", json={
            "budget": 1000, "items": [{"item_sku": "NOPE-999", "quantity": 1}]})
        assert response.status_code == 400

    def test_over_budget_rejected(self, client):
        sku = get_recommendations(client, 1000000)["items"][0]["item_sku"]
        response = client.post("/api/restocking/orders", json={
            "budget": 1, "items": [{"item_sku": sku, "quantity": 100}]})
        assert response.status_code == 400
        assert mock_data.submitted_orders == []

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_non_positive_quantity_rejected(self, client, quantity):
        sku = get_recommendations(client, 1000000)["items"][0]["item_sku"]
        response = client.post("/api/restocking/orders", json={
            "budget": 100000, "items": [{"item_sku": sku, "quantity": quantity}]})
        assert response.status_code == 422


class TestSubmittedOrders:
    """Test suite for GET /api/orders/submitted."""

    def place_order(self, client, quantity):
        sku = get_recommendations(client, 1000000)["items"][0]["item_sku"]
        response = client.post("/api/restocking/orders", json={
            "budget": 100000, "items": [{"item_sku": sku, "quantity": quantity}]})
        assert response.status_code == 201
        return response.json()

    def test_empty_by_default(self, client):
        response = client.get("/api/orders/submitted")
        assert response.status_code == 200
        assert response.json() == []

    def test_newest_first_and_unique_ids(self, client):
        first = self.place_order(client, 1)
        second = self.place_order(client, 2)
        assert first["id"] != second["id"]

        listed = client.get("/api/orders/submitted").json()
        assert [o["id"] for o in listed] == [second["id"], first["id"]]

    def test_not_shadowed_by_order_id_route(self, client):
        """'/api/orders/submitted' must not be treated as an order id (which would be a 404)."""
        assert client.get("/api/orders/submitted").status_code == 200

    def test_existing_orders_unaffected(self, client):
        before = client.get("/api/orders").json()
        self.place_order(client, 1)
        assert client.get("/api/orders").json() == before
