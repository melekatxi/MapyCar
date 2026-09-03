"""Servicio de geocodificación contra Postgres real (RLS) y caché fakeredis. Ref: 1.BE.8-1.BE.13."""
from __future__ import annotations

import asyncio
import base64
import os

import fakeredis
import httpx
import pytest
from sqlalchemy.orm import Session

from app.adapters.geocoder.fake import FakeGeocoder
from app.adapters.geocoder.interface import GeocodeCandidate
from app.core.crypto import EnvKeyProvider, FieldCipher
from app.modules.geocoding import service
from app.modules.geocoding.cache import GeocodeCache
from app.modules.geocoding.models import GeocodeAttempt
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, User
from app.modules.imports.models import Address, Patient


@pytest.fixture()
def cipher(monkeypatch: pytest.MonkeyPatch) -> FieldCipher:
    from app.core.config import get_settings

    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_ACTIVE_KEY_ID", "k1")
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_KEYS", f"k1:{key}")
    get_settings.cache_clear()
    return FieldCipher(EnvKeyProvider())


@pytest.fixture()
def cache() -> GeocodeCache:
    return GeocodeCache(fakeredis.FakeStrictRedis())


def _create_address(db: Session, cipher: FieldCipher, *, direccion: str = "Calle Mayor 1, 3º") -> Address:
    org = Organization(name="Org geocodificación")
    db.add(org)
    db.flush()
    identity_service.set_current_organization_context(db, organization_id=org.id)
    patient = Patient(organization_id=org.id, external_ref="PAC-900", display_ref="Paciente 900")
    db.add(patient)
    db.flush()
    address = Address(
        organization_id=org.id,
        patient_id=patient.id,
        address_ciphertext=cipher.encrypt(direccion),
        postal_code="48001",
        municipality="Bilbao",
        province="Bizkaia",
    )
    db.add(address)
    db.commit()
    return address


def test_geocode_address_matched_updates_status_and_location(db_session: Session, cipher: FieldCipher, cache: GeocodeCache) -> None:
    address = _create_address(db_session, cipher)
    geocoder = FakeGeocoder(
        [
            GeocodeCandidate(
                latitude=43.263,
                longitude=-2.935,
                display_label="Calle Mayor 1, Bilbao",
                score=0.8,
                place_class="building",
                postal_code="48001",
                municipality="Bilbao",
                house_number="1",
            )
        ]
    )

    updated = asyncio.run(service.geocode_address(db_session, geocoder, cache, cipher, address=address))

    assert updated.geocode_status == "matched"
    assert updated.confidence is not None and updated.confidence >= 0.55
    assert updated.location is not None
    assert geocoder.calls == ["Calle Mayor 1"]  # piso/puerta ya retirado antes de consultar


def test_geocode_address_not_found_when_no_candidates(db_session: Session, cipher: FieldCipher, cache: GeocodeCache) -> None:
    address = _create_address(db_session, cipher, direccion="Calle Inexistente 999")
    geocoder = FakeGeocoder([])

    updated = asyncio.run(service.geocode_address(db_session, geocoder, cache, cipher, address=address))

    assert updated.geocode_status == "not_found"
    assert updated.location is None


def test_geocode_address_uses_cache_on_second_call(db_session: Session, cipher: FieldCipher, cache: GeocodeCache) -> None:
    address = _create_address(db_session, cipher)
    geocoder = FakeGeocoder(
        [
            GeocodeCandidate(
                latitude=43.263,
                longitude=-2.935,
                display_label="Calle Mayor 1, Bilbao",
                score=0.8,
                place_class="building",
                postal_code="48001",
                municipality="Bilbao",
                house_number="1",
            )
        ]
    )

    asyncio.run(service.geocode_address(db_session, geocoder, cache, cipher, address=address))
    address.geocode_status = "pending"  # simula una nueva dirección con el mismo texto normalizado
    db_session.commit()
    asyncio.run(service.geocode_address(db_session, geocoder, cache, cipher, address=address))

    assert len(geocoder.calls) == 1  # la segunda vez se sirvió desde caché


def test_geocode_address_retries_on_429_then_succeeds(db_session: Session, cipher: FieldCipher, cache: GeocodeCache) -> None:
    address = _create_address(db_session, cipher)
    candidate = GeocodeCandidate(
        latitude=43.263,
        longitude=-2.935,
        display_label="Calle Mayor 1, Bilbao",
        score=0.8,
        place_class="building",
        postal_code="48001",
        municipality="Bilbao",
        house_number="1",
    )

    class FlakyGeocoder(FakeGeocoder):
        def __init__(self) -> None:
            super().__init__([candidate])
            self.attempts = 0

        async def geocode(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                request = httpx.Request("GET", "http://nominatim.test/search")
                response = httpx.Response(429, request=request)
                raise httpx.HTTPStatusError("rate limited", request=request, response=response)
            return await super().geocode(**kwargs)

    geocoder = FlakyGeocoder()

    updated = asyncio.run(service.geocode_address(db_session, geocoder, cache, cipher, address=address))

    assert geocoder.attempts == 2
    assert updated.geocode_status == "matched"


def test_geocode_address_overlay_fills_missing_housenumber(
    db_session: Session, cipher: FieldCipher, cache: GeocodeCache
) -> None:
    from app.modules.geocoding.overlay import HousenumberOverlay, OverlayPoint

    address = _create_address(db_session, cipher, direccion="Calle Rekalde 33, 2º Izq")
    overlay = HousenumberOverlay.from_records(
        [
            OverlayPoint(
                street="Recalde",
                house_number="33",
                municipality="Bilbao",
                postal_code="48009",
                latitude=43.26357,
                longitude=-2.934599,
                source="eustat-callejero-bizkaia",
                aliases=("rekalde",),
            )
        ]
    )

    updated = asyncio.run(
        service.geocode_address(
            db_session, FakeGeocoder([]), cache, cipher, address=address, overlay=overlay
        )
    )

    assert updated.geocode_status == "matched"
    assert updated.location is not None
    attempt = db_session.query(GeocodeAttempt).filter(GeocodeAttempt.address_id == address.id).one()
    assert attempt.outcome == "matched"
    assert attempt.result_location is not None


def test_geocode_address_skips_municipality_fallback_when_overlay_hits(
    db_session: Session, cipher: FieldCipher, cache: GeocodeCache
) -> None:
    from app.modules.geocoding.overlay import HousenumberOverlay, OverlayPoint

    address = _create_address(db_session, cipher, direccion="Calle Mazarredo 15")
    overlay = HousenumberOverlay.from_records(
        [
            OverlayPoint(
                street="Mazarredo",
                house_number="15",
                municipality="Bilbao",
                postal_code="48001",
                latitude=43.264488,
                longitude=-2.929373,
                source="eustat-callejero-bizkaia",
            )
        ]
    )

    class RecordingGeocoder(FakeGeocoder):
        async def geocode(self, **kwargs):
            self.calls.append(kwargs["address_text"])
            return []

    geocoder = RecordingGeocoder()
    updated = asyncio.run(
        service.geocode_address(db_session, geocoder, cache, cipher, address=address, overlay=overlay)
    )

    assert updated.geocode_status == "matched"
    assert geocoder.calls == ["Calle Mazarredo 15"]  # no fallback a "Bilbao"


def test_select_candidate_manual_sets_manual_status_and_records_reason(db_session: Session, cipher: FieldCipher) -> None:
    address = _create_address(db_session, cipher)
    reviewer = User(email_normalized="reviewer@example.com", display_name="Revisora")
    db_session.add(reviewer)
    db_session.commit()

    updated = service.select_candidate(
        db_session,
        address=address,
        candidate_index=None,
        manual_latitude=43.26,
        manual_longitude=-2.93,
        reason="Portal sin numerar visible en catastro",
        reviewed_by=reviewer.id,
    )

    assert updated.geocode_status == "manual"
    assert updated.confidence == 1.0
    attempt = db_session.query(GeocodeAttempt).filter(GeocodeAttempt.address_id == address.id).one()
    assert attempt.candidate_json_minimized == [{"manual_reason": "Portal sin numerar visible en catastro"}]
