"""Render de exportación: magia PDF/PNG y enlace sin PII. Ref: 3.BE.13, RF-22."""

from app.modules.routing.export_render import navigation_url, render_pdf, render_png, tour_points


def test_navigation_url_is_coords_only() -> None:
    url = navigation_url([(43.263, -2.935), (43.27, -2.94)])
    assert url.startswith("https://www.google.com/maps/dir/")
    assert "43.26300,-2.93500" in url
    assert "PAC-" not in url
    assert "Bilbao" not in url
    assert "Calle" not in url


def test_pdf_and_png_magic_without_patient_text() -> None:
    points = [(43.263, -2.935), (43.27, -2.94), (43.28, -2.93)]
    pdf = render_pdf(points)
    png = render_png(points)
    assert pdf.startswith(b"%PDF")
    assert b"43.26300,-2.93500" in pdf
    assert b"Calle" not in pdf
    assert b"PAC-" not in pdf
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_tour_points_include_origin_stops_destination() -> None:
    snapshot = {
        "origin": {"lat": 43.26, "lon": -2.93},
        "destination": {"lat": 43.26, "lon": -2.93},
        "order": [
            {"lat": 43.27, "lon": -2.94, "sequence": 1},
            {"lat": 43.28, "lon": -2.95, "sequence": 2},
        ],
    }
    points = tour_points(snapshot)
    assert points[0] == (43.26, -2.93)
    assert points[-1] == (43.26, -2.93)
    assert len(points) == 4
