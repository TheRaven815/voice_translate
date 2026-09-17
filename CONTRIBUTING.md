# Katkı Kılavuzu / Contributing Guide

Ahenk projesine katkıda bulunmak istediğiniz için teşekkürler!

## Geliştirme Ortamı Kurulumu

1. Python 3.11 veya üzerinin kurulu olduğundan emin olun (`python --version`).
2. Depoyu klonlayın:
   ```bash
   git clone https://github.com/your-username/voice_translate.git
   cd voice_translate
   ```
3. Sanal ortamı oluşturun ve bağımlılıkları yükleyin:
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   pip install pytest
   ```
   *Veya Windows üzerinde doğrudan `ahenk.bat` çalıştırarak geliştirici menüsünü kullanabilirsiniz.*

## Testleri Çalıştırma

Tüm birim ve entegrasyon testlerini çalıştırmak için:
```cmd
pytest
```

## Kod Standartları

- Kodlar Python 3.11+ `asyncio.TaskGroup` standartlarına uygun olmalıdır.
- GUI değişiklikleri `gui/theme.py` tasarım sistemine sadık kalmalıdır.
- Yeni bir özellik veya hata düzeltmesi eklerken ilgili `tests/` dosyasında test eklemeyi unutmayın.
- Commit mesajlarında Conventional Commits formatı tercih edilir.
