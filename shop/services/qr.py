"""QR helpers (uses `qrcode` if installed; falls back to text payload)."""
from __future__ import annotations

import base64
import io


def qr_png_data_url(payload: str) -> str:
    """Return a data: URL for the QR PNG, or a tiny placeholder if qrcode is missing."""
    try:
        import qrcode  # type: ignore
        qr = qrcode.QRCode(box_size=4, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        encoded = base64.b64encode(buf.getvalue()).decode('ascii')
        return f'data:image/png;base64,{encoded}'
    except Exception:
        # Minimal 1x1 transparent png so <img> still renders without error.
        b = base64.b64encode(
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08'
            b'\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x03'
            b'\x00\x06\x00\x02\x9b\xa3\xfa\xfa\x00\x00\x00\x00IEND\xaeB`\x82'
        ).decode('ascii')
        return f'data:image/png;base64,{b}'
