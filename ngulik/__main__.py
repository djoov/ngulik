"""Entry point untuk `python -m ngulik`.

Disediakan agar sistem bisa dijalankan langsung dari folder project tanpa
perlu `pip install -e .` lebih dulu (NFR-001: harus jalan di komputer lokal
dengan friksi seminimal mungkin).
"""

from ngulik.cli import main

if __name__ == "__main__":
    main()
