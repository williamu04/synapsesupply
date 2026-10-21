import pytest
from fastapi.testclient import TestClient

from synapse.mock_s4.app import ODATA_ROOT, create_app
from synapse.mock_s4.store import Store, load_seed

PO = f"{ODATA_ROOT}/API_PURCHASEORDER_PROCESS_SRV"
STOCK = f"{ODATA_ROOT}/API_MATERIAL_STOCK_SRV"
INB = f"{ODATA_ROOT}/API_INBOUND_DELIVERY_SRV;v=0002"
Z = f"{ODATA_ROOT}/ZSCM_SYNAPSE_SRV"


@pytest.fixture(scope="session")
def seed() -> dict:
    return load_seed()


@pytest.fixture
def store(seed) -> Store:
    return Store(seed)


@pytest.fixture
def client(seed) -> TestClient:
    return TestClient(create_app(seed, rng_seed=0))


@pytest.fixture
def csrf(client) -> dict:
    r = client.get(f"{PO}/A_PurchaseOrder?$top=1", headers={"x-csrf-token": "Fetch"})
    return {"x-csrf-token": r.headers["x-csrf-token"]}
