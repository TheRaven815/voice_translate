# Güvenlik Politikası / Security Policy

## Desteklenen Sürümler / Supported Versions

| Sürüm / Version | Destek / Supported |
| :--- | :--- |
| 0.1.x | :white_check_mark: |

## API Anahtarı Güvenliği / API Key Security

- **Asla API anahtarınızı GitHub Issues, Pull Requests veya açık alanlarda paylaşmayın.**
- Ahenk, Windows üzerinde API anahtarını işletim sistemi düzeyinde DPAPI (`CryptProtectData`) ile kullanıcı hesabınıza özel şifreleyerek yerel diskte saklar (`%APPDATA%\Ahenk\config.json`).
- Git deposuna `.env` veya `config.json` dosyaları dahil edilmez (`.gitignore` koruması altındadır).

## Güvenlik Açığı Bildirimi / Reporting a Vulnerability

Bir güvenlik açığı keşfederseniz lütfen herkese açık bir Issue açmak yerine doğrudan geliştirici ile iletişime geçin. Bildiriniz incelendikten sonra en kısa sürede düzeltme yayınlanacaktır.
