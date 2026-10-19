def pytest_configure(config):
    config.addinivalue_line("markers", "ocr: real-PDF regression case that needs RapidOCR (slow); deselect with -m 'not ocr'")
