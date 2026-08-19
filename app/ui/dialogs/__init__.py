"""Modal diyaloglar (yeni rezervasyon, check-in, folyo, misafir...).

Diyaloglar da sayfalar gibi **is kurali icermez**: dogrulama ve kayit
:mod:`app.application.services` uzerinden yapilir. Diyalogun sorumlulugu
veriyi toplamak, servisi cagirmak ve sonucu/hatasi kullaniciya gostermektir.
"""

from __future__ import annotations
