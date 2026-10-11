import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.backend import main

main.app.dependency_overrides[main.require_admin] = lambda: None


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c

        # Clean up only test records in the guarded test database.
        with main.SessionLocal() as db:
            ids = db.scalars(
                select(main.Medicine.id).where(main.Medicine.name == "TestMed")
            ).all()
            if ids:
                db.execute(
                    delete(main.StockMovement).where(
                        main.StockMovement.medicine_id.in_(ids)
                    )
                )
                db.execute(
                    delete(main.Medicine).where(main.Medicine.id.in_(ids))
                )
                db.commit()


def make(client, qty=10):
    response = client.post("/api/medicines", json={
        "name": "TestMed",
        "batch_number": "T-" + uuid.uuid4().hex[:12],
        "quantity": qty,
        "unit_price": "1.50",
        "expiry_date": str(date.today() + timedelta(days=365)),
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_opening_movement(client):
    medicine_id = make(client, 10)
    response = client.get(f"/api/medicines/{medicine_id}/movements")
    assert response.status_code == 200
    assert [row["change"] for row in response.json()] == [10]
    assert response.json()[0]["type"] == "opening"


def test_adjust_and_history(client):
    medicine_id = make(client, 10)

    response = client.post(
        f"/api/medicines/{medicine_id}/stock",
        json={"change": 5, "reason": "stock recount"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 15

    response = client.post(
        f"/api/medicines/{medicine_id}/stock",
        json={"change": -3, "reason": "damaged stock"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 12

    history = client.get(
        f"/api/medicines/{medicine_id}/movements"
    ).json()
    assert [row["change"] for row in history] == [-3, 5, 10]


def test_blank_stock_reason_is_rejected(client):
    medicine_id = make(client, 10)
    response = client.post(
        f"/api/medicines/{medicine_id}/stock",
        json={"change": 1, "reason": "   "},
    )
    assert response.status_code == 422


def test_no_negative_stock(client):
    medicine_id = make(client, 2)
    response = client.post(
        f"/api/medicines/{medicine_id}/stock",
        json={"change": -3, "reason": "stock correction"},
    )
    assert response.status_code == 409


def test_zero_and_missing_medicine(client):
    medicine_id = make(client, 2)

    response = client.post(
        f"/api/medicines/{medicine_id}/stock",
        json={"change": 0, "reason": "no change"},
    )
    assert response.status_code == 422

    response = client.post(
        "/api/medicines/999999/stock",
        json={"change": 1, "reason": "stock found"},
    )
    assert response.status_code == 404


def test_quantity_edit_with_reason_records_movement(client):
    medicine_id = make(client, 10)
    medicine = next(
        item for item in client.get("/api/medicines").json()
        if item["id"] == medicine_id
    )
    medicine["quantity"] = 13
    medicine["stock_change_reason"] = "physical recount"

    response = client.put(
        f"/api/medicines/{medicine_id}",
        json=medicine,
    )
    assert response.status_code == 200, response.text

    history = client.get(
        f"/api/medicines/{medicine_id}/movements"
    ).json()
    assert history[0]["change"] == 3
    assert history[0]["reason"] == "physical recount"


def test_cannot_delete_medicine_with_movement_history(client):
    medicine_id = make(client, 10)
    response = client.delete(f"/api/medicines/{medicine_id}")
    assert response.status_code == 409


def test_quantity_cannot_change_through_medicine_edit(client):
    medicine_id = make(client, 10)
    medicine = next(
        item for item in client.get("/api/medicines").json()
        if item["id"] == medicine_id
    )
    medicine["quantity"] = 11

    response = client.put(
        f"/api/medicines/{medicine_id}",
        json=medicine,
    )
    assert response.status_code == 409
