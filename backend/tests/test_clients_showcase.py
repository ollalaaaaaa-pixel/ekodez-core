import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base, Client, Contract, InspectionReport, Object, Transaction


class ClientsShowcaseTest(unittest.TestCase):
    def setUp(self):
        self.old_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.api = TestClient(main.app)
        with Session(self.engine) as session:
            client = Client(
                name="ООО Тест",
                client_type="legal_entity",
                inn_masked="12***90",
                encrypted_requisites="must-not-leak",
            )
            contract = Contract(
                number="TEST-1", price=Decimal("100.00"), periodicity="monthly"
            )
            obj = Object(
                name="Офис",
                address="***",
                type="office",
                area_sqm=Decimal("10"),
                client=client,
                contract=contract,
            )
            session.add_all(
                [
                    obj,
                    Object(
                        name="Склад",
                        address="***",
                        type="other",
                        area_sqm=Decimal("20"),
                        client=client,
                    ),
                    Client(name="ИП Пример", client_type="sole_proprietor"),
                    Client(name="Физлицо", client_type="individual"),
                ]
            )
            session.flush()
            session.add_all(
                [
                    InspectionReport(
                        contract_id=contract.id, report_month=date(2026, 9, 1)
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 9, 1),
                        amount=Decimal("100.00"),
                        kind="income",
                        object_id=obj.id,
                    ),
                ]
            )
            session.commit()

    def tearDown(self):
        self.api.close()
        main.engine = self.old_engine
        self.engine.dispose()

    def test_list_search_type_and_masking(self):
        self.assertEqual(len(self.api.get("/api/clients").json()), 2)
        result = self.api.get(
            "/api/clients", params={"q": "тест", "client_type": "legal_entity"}
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()), 1)
        self.assertEqual(result.json()[0]["inn"], "12***90")
        self.assertNotIn("must-not-leak", result.text)

    def test_card_multiple_objects_and_related_data(self):
        response = self.api.get("/api/clients/1")
        self.assertEqual(response.status_code, 200)
        card = response.json()
        self.assertEqual(len(card["objects"]), 2)
        self.assertEqual(len(card["contracts"]), 1)
        self.assertEqual(card["transactions"][0]["amount"], "100.00")
        self.assertEqual(len(card["inspections"]), 1)
        self.assertNotIn("encrypted", response.text)
        self.assertEqual(self.api.get("/api/clients/999").status_code, 404)

    def test_health_on_isolated_database(self):
        self.assertEqual(self.api.get("/health").status_code, 200)
        self.assertEqual(self.api.get("/health/db").status_code, 200)
