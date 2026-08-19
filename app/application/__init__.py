"""Uygulama katmani - use-case servisleri.

Bu katman arayuz ile domain arasindaki koprudur. Sorumluluklari:

* Yetki kontrolu (:func:`app.security.auth.require_permission`)
* Islem (transaction) sinirlarini yonetmek
* Repository'lerden veri toplayip domain kurallarina vermek
* Sonucu kalici hale getirmek ve denetim gunlugune yazmak

Domain kurallari burada **tekrarlanmaz**; yalnizca cagrilir.
"""

from __future__ import annotations
