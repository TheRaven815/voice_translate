"""Tkinter bağımsız hata sınıflandırma, yerelleştirme ve ortak yeniden bağlanma motoru."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable

from i18n import get_ui_lang

_PERMANENT_LIVE_ERRORS = (
    "api_key_invalid",
    "api key not valid",
    "permission_denied",
    "forbidden",
    "denied access",
    "resource_exhausted",
    "quota",
    "not_found",
)


def _live_error_code(err: BaseException) -> int | None:
    code = getattr(err, "code", None)
    received = getattr(err, "rcvd", None)
    code = getattr(received, "code", None) or code
    if isinstance(code, int):
        return code
    if re.search(r"\b1008\b", str(err)):
        return 1008
    return None


def _is_planned_renewal(err: BaseException) -> bool:
    """Sunucunun ~10 dk bağlantı sınırında istediği yenileme; ağ kopması değil."""
    return "goaway" in str(err).lower()


def _is_retryable_error(err: BaseException, *, session_established: bool = False) -> bool:
    code = _live_error_code(err)
    msg = str(err).lower()
    if code in {400, 401, 403, 404, 429} or any(token in msg for token in _PERMANENT_LIVE_ERRORS):
        return False
    session_expired = any(token in msg for token in (
        "session expired", "session has expired", "session duration",
        "session time limit", "maximum session", "max session",
        "connection duration", "maximum connection", "deadline exceeded",
    ))
    if code == 1008:
        # 1008 genel bir WebSocket politika kodudur; tek başına erişim reddi değildir.
        # Açık erişim/anahtar/kota hataları yukarıda elenir. Belirsiz kapanış
        # yalnızca zaten açılmış oturumda sınırlı yeniden denemeye alınır.
        return session_expired or session_established
    if session_expired:
        return True
    if code in {1000, 1001, 1006, 1011, 1012, 1013} or (isinstance(code, int) and 500 <= code < 600):
        return True
    if isinstance(err, (ConnectionError, TimeoutError)):
        return True
    kind = " ".join(cls.__name__.lower() for cls in type(err).__mro__)
    return any(token in kind or token in msg for token in (
        "connection", "socket", "timeout", "gaierror", "network", "transporterror",
        "remoteprotocolerror", "keepalive ping", "service unavailable",
    ))


def _worker_error(err: BaseException) -> BaseException:
    """TaskGroup içindeki asıl hatayı bul; kalıcı hatalar önceliklidir."""
    if isinstance(err, BaseExceptionGroup):
        errors = [_worker_error(child) for child in err.exceptions]
        return next((child for child in errors if not _is_retryable_error(child)), errors[0])
    return err


def format_user_error(err: BaseException) -> str:
    """Teknik istisnaları geçerli arayüz dilinde (TR/EN) anlaşılır mesaja çevirir."""
    msg = str(err)
    err_type = type(err).__name__
    msg_lower = msg.lower()
    en = get_ui_lang() == "en"

    if isinstance(err, AssertionError) or (not msg.strip() and err_type == "AssertionError"):
        if en:
            return (
                "Could not open the audio device (WASAPI mix format mismatch). "
                "Try setting Default Format to '48000 Hz' in Windows Sound → Recording → "
                "Microphone → Properties → Advanced, or switch back to a [System] input."
            )
        return (
            "Ses aygıtı açılamadı (soundcard WASAPI uyumsuzluğu — bazı mikrofonların "
            "sürücü mix biçimi desteklenmiyor). Windows Ses → Kayıt → Mikrofon → "
            "Özellikler → Gelişmiş → Varsayılan Biçimi '48000 Hz' yapıp yeniden dene; "
            "olmazsa çalışan bir [Sistem] girişine dön."
        )
    if not msg.strip():
        return (
            f"{err_type} (no details; check the log file)."
            if en
            else f"{err_type} (ayrıntı yok; dosya günlüğüne bakın)."
        )
    if isinstance(err, ProcessLookupError) or "application process" in msg_lower:
        if en:
            return "The selected app closed or restarted. Reopen it, click Refresh, and select it again."
        return "Seçili uygulama kapandı veya yeniden başladı. Uygulamayı açın, Yenile'ye basıp yeniden seçin."
    if "mix bi" in msg_lower and "48000" in msg:
        return f"Audio device error: {msg}" if en else f"Ses aygıtı hatası: {msg}"
    if "denied access" in msg_lower:
        if en:
            return "Your Google project was denied Gemini Live access (1008). Create a key in another project in Google AI Studio or contact Google support."
        return "Google projesinin Gemini Live erişimi reddedildi (1008). Google AI Studio'da başka bir proje/anahtar oluşturun veya proje erişimi için Google desteğe başvurun."
    if "api_key_invalid" in msg_lower or "api key not valid" in msg_lower:
        if en:
            return "Invalid API key. Check your Google AI Studio key (https://aistudio.google.com/apikey)."
        return "Geçersiz API anahtarı. Lütfen Google AI Studio anahtarınızı kontrol edin (https://aistudio.google.com/apikey)."
    if "429" in msg or "resource_exhausted" in msg_lower or "quota" in msg_lower:
        if en:
            return "Gemini API quota exceeded (429 Resource Exhausted). Wait briefly or check your quota."
        return "Gemini API kota sınırı aşıldı (429 Resource Exhausted). Lütfen biraz bekleyin veya kotanızı kontrol edin."
    if "404" in msg or "not_found" in msg_lower:
        if en:
            return "The specified Gemini model was not found (404 Not Found). Check the model name."
        return "Belirtilen Gemini modeli bulunamadı (404 Not Found). Model adını kontrol edin."
    if "403" in msg or "permission_denied" in msg_lower or "forbidden" in msg_lower:
        if en:
            return "Gemini API permission denied (403). Check whether your key has Gemini Live API access."
        return "Gemini API erişim izni reddedildi (403). Anahtarınızın Gemini Live API yetkisini kontrol edin."
    if "goaway" in msg_lower:
        if en:
            return "Gemini Live session reached its duration limit and is renewing. This is not a network drop."
        return (
            "Gemini Live bağlantısı süre sınırına ulaştı; oturum yenileniyor. "
            "Bu bir internet kopması değildir."
        )
    if _live_error_code(err) == 1008:
        if en:
            return f"Gemini Live session was closed by the server (1008). Server detail: {msg}"
        return f"Gemini Live oturumu sunucu tarafından kapatıldı (1008). Bu kod tek başına proje erişiminin reddedildiğini göstermez. Sunucu ayrıntısı: {msg}"
    if any(k in err_type.lower() or k in msg_lower for k in ("connection", "socket", "timeout", "gaierror", "network")):
        if en:
            return f"Network connection error ({err_type}): Check your internet connection and firewall."
        return f"Ağ bağlantısı hatası ({err_type}): İnternet bağlantınızı ve güvenlik duvarınızı kontrol edin."
    if "ses aygıtı" in msg_lower or "soundcard" in msg_lower:
        return f"Audio device error: {msg}" if en else f"Ses aygıtı hatası: {msg}"
    return f"{err_type}: {msg}"


def clone_loop_for_retry(old_loop, base_kwargs: dict, loop_factory: Callable):
    """Çalışma anında değişen ses/durum alanlarını koruyarak yeni oturum kurar."""
    kwargs = dict(base_kwargs)
    if old_loop is not None:
        old_vars = vars(old_loop)
        for name in ("source_mic", "output_speaker", "volume", "muted", "vad_threshold"):
            if name in old_vars:
                kwargs[name] = getattr(old_loop, name)
    new_loop = loop_factory(**kwargs)
    if old_loop is not None:
        if getattr(old_loop, "is_paused", False):
            new_loop.pause()
        if getattr(old_loop, "_dub_exclude", False):
            new_loop.set_dub_exclude(True)
        set_capture_gain = getattr(new_loop, "set_capture_gain", None)
        if set_capture_gain is not None:
            set_capture_gain(getattr(old_loop, "_capture_gain", 1.0))
    new_loop._announce_reconnect = True
    return new_loop


def run_with_retries(
    get_loop: Callable,
    *,
    rebuild_loop: Callable | None = None,
    stopping=None,
    max_retries: int = 3,
    on_error: Callable[[BaseException, bool], None] | None = None,
    on_permanent: Callable[[BaseException], None] | None = None,
    on_reconnecting: Callable[[int, int], None] | None = None,
    on_exhausted: Callable[[BaseException], None] | None = None,
) -> BaseException | None:
    """GUI ve CLI için ortak sınırlı yeniden bağlanma döngüsü.

    Normal bitişte veya durdurma olayında None, kullanıcı kesintisinde
    KeyboardInterrupt/CancelledError, kalıcı/tükenen hatada ilgili istisnayı döndürür.
    """
    retries = 0
    while stopping is None or not stopping.is_set():
        current = get_loop()
        try:
            asyncio.run(current.run())
            return None
        except (KeyboardInterrupt, asyncio.CancelledError) as stopped:
            return stopped
        except BaseException as exc:
            if stopping is not None and stopping.is_set():
                return None
            root_err = _worker_error(exc)
            if isinstance(root_err, (KeyboardInterrupt, asyncio.CancelledError)):
                return root_err
            connected_at = getattr(current, "connected_at", 0.0)
            session_established = isinstance(connected_at, (int, float)) and connected_at > 0
            renewal = _is_planned_renewal(root_err) or (
                getattr(current, "_renew_requested", False)
                and _is_retryable_error(root_err, session_established=session_established)
            )
            if on_error is not None:
                on_error(root_err, renewal)
            if not _is_retryable_error(root_err, session_established=session_established):
                if on_permanent is not None:
                    on_permanent(root_err)
                return root_err
            if session_established and time.monotonic() - connected_at >= 30.0:
                retries = 0
            retries += 1
            if retries <= max_retries:
                if on_reconnecting is not None:
                    on_reconnecting(retries, max_retries)
                delay = 0.5 if renewal else 2
                if stopping is not None:
                    if stopping.wait(delay) or stopping.is_set():
                        return None
                else:
                    try:
                        time.sleep(delay)
                    except KeyboardInterrupt as interrupted:
                        return interrupted
                if rebuild_loop is not None and (stopping is None or not stopping.is_set()):
                    rebuild_loop()
            else:
                if on_exhausted is not None:
                    on_exhausted(root_err)
                return root_err
    return None
