"""AI Gelistirme Merkezi - kisitlanmis, denetlenen gelistirme ortami.

Bu paket, kullanicinin yapay zekaya kodlama gorevleri verebilmesini saglar.
Yuksek riskli bir yetenektir; bu yuzden **savunma katmanlari** ile kurulmustur:

1. :mod:`app.devcenter.policy` - komut politikasi (izin/yasak listesi, sandbox)
2. :mod:`app.devcenter.terminal` - kisitli calistirma (zaman asimi, cikti siniri)
3. :mod:`app.devcenter.workspace` - dosya degisikliklerini diff olarak hazirlar
4. :mod:`app.devcenter.git_guard` - kontrol noktasi, ayri dal, geri alma
5. :mod:`app.devcenter.quality` - format -> lint -> tip -> test -> guvenlik
6. :mod:`app.devcenter.session` - tum akisi yoneten oturum

Tasarim ilkesi
--------------
**Hicbir sey kullanici onayi olmadan degismez.** Yapay zeka yalnizca *oneri*
uretir: calistirilacak komut, uygulanacak yama. Kullanici gormeden ve
onaylamadan disk uzerinde tek bir bayt degismez.

Ikinci ilke: **her sey geri alinabilir.** Degisiklikler ayri bir Git dalinda
ve kontrol noktasi sonrasi uygulanir; testler gecmezse ana dala birlesmez.
"""

from __future__ import annotations

from app.devcenter.policy import (
    CommandDecision,
    CommandPolicy,
    RiskLevel,
    evaluate_command,
)

__all__ = ["CommandDecision", "CommandPolicy", "RiskLevel", "evaluate_command"]
