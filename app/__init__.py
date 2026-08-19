"""Akilli Konaklama Yonetim Sistemi.

Modüler, katmanli mimariye sahip otel/PMS yazilimi.

Katmanlar
---------
``app.core``            Yapilandirma, loglama, sir yonetimi, ortak hatalar
``app.domain``          Saf is kurallari (framework bagimsiz)
``app.infrastructure``  Veritabani, repository, dis dunya ile temas
``app.application``     Use-case servisleri (UI ile domain arasindaki koprü)
``app.security``        Kimlik dogrulama, RBAC, denetim gunlugu
``app.reporting``       PDF / Excel / CSV rapor uretimi
``app.ai``              Yapay zeka saglayici adaptorleri ve is senaryolari
``app.devcenter``       AI Gelistirme Merkezi ve kisitli terminal
``app.api``             FastAPI servis katmani
``app.ui``              PySide6 masaustu arayuzu (is kurali icermez)
"""

from __future__ import annotations

__version__ = "0.1.0"
__app_name__ = "Akilli Konaklama Yonetim Sistemi"
__app_slug__ = "akilli-konaklama"

__all__ = ["__app_name__", "__app_slug__", "__version__"]
