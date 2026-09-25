# Ngulik

Alat NLP yang berjalan sepenuhnya di laptop untuk **menemukan keyword secara
iteratif** dari teks Bahasa Indonesia, khususnya bahasa slang dan meme internet.

Cara kerjanya: kamu mulai dari beberapa *seed keyword*. Sistem mengumpulkan
komentar publik, membersihkannya, lalu mengusulkan kata-kata baru. Kamu yang
memutuskan kata mana yang disetujui, dan kata yang disetujui dipakai sebagai
seed di putaran berikutnya.

```
SEED -> COLLECT -> CLEAN -> ANALYZE -> DISCOVER -> REVIEW -> EXPAND -> (ulang)
```

Semua data disimpan di satu berkas SQLite (`data/ngulik.db`). Tidak butuh
server, tidak butuh VPS.

> **Bukan alat surveillance.** Sistem ini tidak menyimpan nama komentator,
> tidak memprofilkan orang, dan setiap keyword baru wajib disetujui manusia.

---

## Daftar isi

1. [Status fitur](#1-status-fitur)
2. [Instalasi](#2-instalasi)
3. [Mulai cepat (5 menit)](#3-mulai-cepat-5-menit)
4. [Konsol interaktif](#4-konsol-interaktif)
5. [Alur kerja lengkap](#5-alur-kerja-lengkap)
6. [Mengambil kata slang dari internet](#6-mengambil-kata-slang-dari-internet)
7. [Menyiapkan YouTube API Key](#7-menyiapkan-youtube-api-key)
8. [Memakai data sendiri](#8-memakai-data-sendiri)
9. [Daftar perintah](#9-daftar-perintah)
10. [Konfigurasi](#10-konfigurasi)
11. [Privasi dan etika](#11-privasi-dan-etika)
12. [Pemecahan masalah](#12-pemecahan-masalah)

---

## 1. Status fitur

| Tahap | Bisa dipakai? |
|---|---|
| Kelola seed keyword | Ya |
| Kumpulkan komentar dari berkas (JSON/JSONL/CSV) | Ya |
| Kumpulkan komentar dari YouTube (cari lewat keyword) | Ya, butuh API key |
| Kumpulkan komentar dari video YouTube tertentu | Ya, butuh API key |
| Tandai komentar yang memuat keyword di database | Ya, otomatis |
| Lihat komentar dan video yang terkumpul | Ya |
| Bersihkan komentar (normalisasi, slang, spam, duplikat) | Ya |
| Ambil kata slang dari kamus internet (kbbj.web.id) | Ya |
| Review kandidat dan promosi ke seed | Ya |
| Analisis frekuensi, n-gram, TF-IDF, co-occurrence | Ya |
| Kandidat kata baru otomatis dari komentar | Ya |

Kandidat keyword baru datang dari dua jalur: **analisis komentar** yang sudah
kamu kumpulkan (`discover`) dan **kamus slang online** (`lexicon fetch`).
Keduanya masuk ke antrean review yang sama.

---

## 2. Instalasi

Butuh **Python 3.11 atau lebih baru**. Panduan ini memakai **conda**.

```powershell
cd ngulik        # folder hasil clone atau unduhan project ini

conda create -n ngulik python=3.12 -y
conda activate ngulik
pip install -r requirements.txt
```

Opsional, supaya bisa mengetik `ngulik` saja dan bukan `python -m ngulik`:

```powershell
pip install -e .
```

Semua contoh di bawah memakai `python -m ngulik`. Kalau sudah menjalankan
`pip install -e .`, kamu boleh menggantinya dengan `ngulik`.

> Setiap kali membuka terminal baru, jalankan `conda activate ngulik` dulu.
> Kalau `conda activate` tidak jalan di PowerShell, jalankan sekali
> `conda init powershell`, lalu buka ulang terminalnya.

---

## 3. Mulai cepat (5 menit)

Contoh ini memakai data contoh yang sudah disediakan, jadi belum butuh API
key.

```powershell
python -m ngulik init                 # buat database
python -m ngulik keyword import       # muat seed dari config/keywords.yaml
python -m ngulik collect --path data/fixtures/sample_comments.json
python -m ngulik clean                # bersihkan komentar
python -m ngulik status               # lihat ringkasan
```

Lalu coba ambil kata slang dari internet dan review:

```powershell
python -m ngulik lexicon fetch --limit 10
python -m ngulik review
python -m ngulik iterate
```

Atau lakukan semuanya dari konsol interaktif:

```powershell
python -m ngulik
```

---

## 4. Konsol interaktif

Menjalankan `python -m ngulik` **tanpa argumen** membuka konsol bergaya
Metasploit:

```
       =[ ngulik v0.1.0                                                  ]
+ -- --=[ 6 modules ready - 5 coming - 2 collectors - 1 lexicon source  ]
+ -- --=[ 20 comments - 8 active keywords - 0 candidates pending        ]

ngulik >
```

### Dua cara menjalankan sesuatu

**a. Pakai modul** (`use`, `set`, `run`):

```
ngulik > show modules
ngulik > use lexicon/kbbj
ngulik lexicon(kbbj) > show options
ngulik lexicon(kbbj) > set LIMIT 20
ngulik lexicon(kbbj) > run
ngulik lexicon(kbbj) > back
```

Modul bisa juga dipilih lewat nomornya dari `show modules`, misalnya
`use 3`.

**b. Ketik perintah biasa.** Semua perintah di [bagian 9](#9-daftar-perintah)
bisa diketik langsung, tanpa `python -m ngulik` di depannya:

```
ngulik > status
ngulik > keyword add wkwk "ngakak parah"
ngulik > review --list
```

### Daftar modul

| Modul | Fungsi |
|---|---|
| `collector/file` | Impor komentar dari berkas lokal |
| `collector/youtube` | Kumpulkan komentar YouTube untuk keyword aktif |
| `collector/youtube-video` | Kumpulkan komentar dari video YouTube pilihanmu |
| `cleaning/pipeline` | Bersihkan komentar |
| `lexicon/kbbj` | Ambil kata slang dari kbbj.web.id |
| `discovery/review` | Setujui atau tolak kandidat |
| `discovery/iterate` | Promosikan kandidat yang disetujui menjadi seed |
| `analysis/all` | Jalankan keempat analisis sekaligus |
| `analysis/frequency`, `analysis/ngram`, `analysis/tfidf`, `analysis/cooccurrence` | Satu analisis saja |
| `discovery/candidates` | Usulkan kata baru dari komentar |

### Perintah konsol

| Perintah | Fungsi |
|---|---|
| `help` atau `?` | Daftar semua perintah |
| `show modules` | Daftar modul |
| `show options` | Opsi modul yang sedang dipilih |
| `use <modul>` | Pilih modul |
| `set <OPSI> <nilai>` / `unset <OPSI>` | Ubah atau kosongkan opsi |
| `run` atau `exploit` | Jalankan modul |
| `info` | Detail modul |
| `search <kata>` | Cari modul |
| `back` | Keluar dari modul |
| `history` | Riwayat perintah |
| `banner` | Tampilkan banner lain |
| `clear` | Bersihkan layar |
| `exit` atau `quit` | Keluar |

`Ctrl+C` tidak menutup konsol; ketik `exit` untuk keluar.

---

## 5. Alur kerja lengkap

### Langkah 1: Tentukan seed keyword

Buka `config/keywords.yaml` dan **ganti placeholder `contoh_...`** dengan topik
yang ingin kamu teliti. Minimal 5 seed.

```yaml
keywords:            # satu kata
  - gabut
  - mager
phrases:             # beberapa kata
  - "gabut parah"
hashtags:
  - "#gabut"
```

Lalu muat ke database. Perintah ini aman dijalankan berulang dan tidak
membuat data ganda:

```powershell
python -m ngulik keyword import
python -m ngulik keyword list
```

Keyword juga bisa ditambah atau dinonaktifkan langsung:

```powershell
python -m ngulik keyword add rek "ngasah linggis"
python -m ngulik keyword remove rek          # dinonaktifkan, bukan dihapus
python -m ngulik keyword list --all          # termasuk yang nonaktif
```

Setelah beberapa iterasi, keyword hasil persetujuan hanya ada di database.
Untuk menyimpannya ke berkas, misalnya untuk dibagikan atau dipakai di
laptop lain:

```powershell
python -m ngulik keyword export                          # ke data/exports/keywords.yaml
python -m ngulik keyword import --file data/exports/keywords.yaml
```

### Langkah 2: Kumpulkan komentar

Ada tiga cara. Semuanya aman diulang karena komentar yang sama tidak akan
tersimpan dua kali.

**a. YouTube, cari video lewat keyword** (butuh API key, lihat
[bagian 7](#7-menyiapkan-youtube-api-key)). Sistem mencari video untuk setiap
keyword aktif, lalu mengambil komentarnya:

```powershell
python -m ngulik collect --source youtube --limit 500
```

**b. YouTube, dari video tertentu saja.** Tempel URL atau ID videonya. Cara ini
**tidak memakai jatah pencarian** yang terbatas, dan tidak butuh seed keyword:

```powershell
python -m ngulik collect --video https://www.youtube.com/watch?v=XXXXXXXXXXX
python -m ngulik collect --video https://youtu.be/AAAAAAAAAAA --video BBBBBBBBBBB --pages 5
```

- Format yang diterima: `youtube.com/watch?v=...`, `youtu.be/...`,
  `/shorts/...`, `/live/...`, atau ID 11 karakter.
- `--video` boleh diulang untuk beberapa video sekaligus.
- `--pages` adalah jumlah halaman komentar per video (1 halaman = 100
  komentar). Default-nya 10.
- `--limit` tetap membatasi total komentar dalam satu run.

Di konsol:

```
ngulik > use collector/youtube-video
ngulik collector(youtube-video) > set VIDEOS https://youtu.be/AAAAAAAAAAA, BBBBBBBBBBB
ngulik collector(youtube-video) > set PAGES 5
ngulik collector(youtube-video) > run
```

**c. Dari berkas sendiri** (lihat [bagian 8](#8-memakai-data-sendiri)):

```powershell
python -m ngulik collect --source file --path data/komentar_saya.csv
```

**Pencocokan keyword otomatis.** Setelah setiap collect, sistem menandai
komentar mana yang memuat keyword yang sudah ada di database, termasuk kata
slang dari kamus yang sudah kamu setujui:

```
[+] 37 of 500 comments contain known keywords (12 active keywords checked)
```

Pencocokannya per kata utuh (`rek` cocok dengan "ayo rek", tapi tidak dengan
"rekam") dan tidak peka huruf besar/kecil. `#gabut` juga cocok dengan kata
"gabut". Komentar yang **tidak** memuat keyword tetap disimpan, karena justru
dari situlah kata baru ditemukan.

Pencocokan dijalankan ulang otomatis setelah `iterate`. Kalau kamu menambah
keyword secara manual, jalankan:

```powershell
python -m ngulik keyword match
```

### Melihat data yang terkumpul

```powershell
python -m ngulik videos list                           # video yang pernah diambil
python -m ngulik comments list                         # 20 komentar terbaru
python -m ngulik comments list --video XXXXXXXXXXX     # komentar dari satu video
python -m ngulik comments list --keyword rek           # komentar yang memuat "rek"
python -m ngulik comments list --matched               # yang memuat keyword apa pun
python -m ngulik comments list --search "ngakak"       # cari teks bebas
python -m ngulik comments list --usable --limit 100    # tanpa spam dan duplikat
python -m ngulik comments show 42                      # detail satu komentar
```

Saringan bisa digabung, misalnya `comments list --video XXXXXXXXXXX --matched`.
Tambahkan `--limit 0` untuk menampilkan semua, dan `--export hasil.csv` untuk
menyimpannya ke CSV yang bisa dibuka di Excel.

Kolom *State* di `comments list` berarti:

| State | Arti |
|---|---|
| `raw` | belum dibersihkan (jalankan `clean`) |
| `ok` | layak analisis |
| `spam` | ditandai spam; alasannya ada di `comments show` |
| `dup` | duplikat dari komentar lain |

### Langkah 3: Bersihkan

```powershell
python -m ngulik clean
```

Yang terjadi pada tiap komentar:

- huruf dikecilkan, URL/mention dibuang, `#gabut` menjadi `gabut`;
- huruf berulang dipendekkan (`bagusssss` menjadi `baguss`);
- slang dinormalisasi memakai `config/slang_id.csv`, dan stopword dibuang;
- **spam ditandai beserta alasannya**: nomor WA, terlalu banyak link/mention/
  hashtag, `aaaaaaaa`, kata diulang-ulang, terlalu pendek, atau copypasta dari
  banyak akun;
- **duplikat ditandai**, baik yang persis sama maupun yang nyaris sama.

Spam dan duplikat **tidak dihapus**, hanya dikeluarkan dari analisis. Teks
asli tidak pernah diubah.

Kalau kamu mengubah kamus slang, stopword, atau aturan spam, proses ulang
semua dari data mentah:

```powershell
python -m ngulik clean --reprocess
```

### Langkah 4: Analisis komentar

```powershell
python -m ngulik analyze                 # keempat analisis sekaligus
python -m ngulik analyze tfidf --show 30 # satu analisis, 30 baris per tabel
```

Yang ditampilkan:

| Analisis | Menjawab pertanyaan |
|---|---|
| **Frequency** | Kata apa yang paling sering muncul? |
| **N-gram** | Frasa 2–3 kata apa yang sering muncul bersama, misalnya "gabut parah"? |
| **TF-IDF** | Kata apa yang *khas*: cukup sering muncul, tapi tidak ada di semua komentar? |
| **Co-occurrence** | Kata apa yang sering muncul *berdekatan* (dalam jarak 5 kata)? Diukur dengan PMI: makin tinggi, makin kuat hubungannya. |

Hasil teratas tiap analisis juga disimpan ke database untuk dirujuk nanti.
Analisis hanya memakai komentar berstatus `ok`: spam dan duplikat tidak ikut.

### Langkah 5: Temukan kandidat kata baru

```powershell
python -m ngulik discover --dry-run   # lihat peringkatnya dulu, tanpa menyimpan
python -m ngulik discover             # simpan kandidat teratas untuk direview
```

Setiap kata dan frasa di komentar diberi skor dari empat sinyal:

| Sinyal | Bobot default | Artinya |
|---|---|---|
| TF-IDF | 0.35 | seberapa khas kata itu |
| Co-occurrence | 0.30 | seberapa kuat kata itu muncul **di dekat seed keyword kamu** |
| Frequency | 0.25 | seberapa sering muncul |
| N-gram | 0.10 | bonus untuk frasa multi-kata |

Sebelum diberi skor, ada saringan: kata harus muncul di minimal 3 komentar
dan panjangnya minimal 3 huruf. Kata yang sudah jadi keyword, sedang
menunggu review, atau pernah kamu tolak juga dilewati.

Kolom *Near seed* menunjukkan seed mana yang paling dekat dengan kandidat
itu. Kalau muncul peringatan **"None of your active keywords appear in the
cleaned comments"**, seed kamu tidak ada di komentar yang terkumpul. Sinyal
co-occurrence jadi mati dan kandidat hanya dinilai dari frekuensi dan TF-IDF.
Periksa seed-nya, atau kumpulkan komentar yang memang membahas topik itu.

Bobot dan saringan bisa diubah di bagian `discovery:` di `config/config.yaml`.

> Hasil discover makin bagus kalau komentarnya banyak (ratusan sampai
> ribuan) dan seed-nya memang muncul di komentar itu. Dengan puluhan
> komentar saja, kandidatnya cenderung kata umum.

### Langkah 6: Review, lalu iterasi

```powershell
python -m ngulik lexicon fetch     # opsional: kandidat tambahan dari kamus internet
python -m ngulik review            # putuskan satu per satu
python -m ngulik iterate           # yang disetujui jadi seed iterasi berikutnya
```

Saat review, setiap kandidat ditampilkan bersama **contoh komentar asli** yang
memuatnya, supaya kamu bisa melihat konteks pemakaiannya sebelum memutuskan.
Kolom *Origin* menjelaskan asal angkanya, misalnya
`docs=12; count=15; tfidf=1.84; near seed 'gabut' (pmi 2.10)`.

Setelah `iterate`, ulangi dari Langkah 2 (collect). Keyword baru ikut dipakai
dan nomor iterasinya naik. Asal setiap keyword tercatat, bisa dilihat di
kolom *Origin* pada `keyword list`.

### Cek kondisi kapan saja

```powershell
python -m ngulik status
```

---

## 6. Mengambil kata slang dari internet

Sumber yang didukung sekarang: **KBBJ (Kamus Besar Bahasa Jomok,
kbbj.web.id)**.

```powershell
python -m ngulik lexicon sources              # sumber yang tersedia
python -m ngulik lexicon fetch --limit 20     # unduh 20 entri
python -m ngulik lexicon list                 # lihat hasilnya
python -m ngulik lexicon list --category Plesetan
```

Aturan yang dipakai sistem:

- **Kata dari kamus tidak langsung jadi keyword.** Semuanya masuk sebagai
  kandidat yang harus kamu review.
- **Sopan terhadap situs:** ada jeda 2 detik antar-permintaan, robots.txt
  dipatuhi, dan sistem mengaku jujur sebagai "Ngulik".
- **Tidak mengunduh ulang:** entri yang diambil kurang dari 30 hari lalu
  dilewati. Pakai `--refresh` kalau ingin memaksa unduh ulang.
- **Tidak menyimpan data orang:** kategori "Nama Orang" dilewati, dan nama
  kontributor entri tidak pernah dibaca.

Unduhan pertama untuk seluruh kamus (sekitar 100 entri) memakan waktu
beberapa menit karena ada jeda antar-permintaan.

### Review kandidat

```powershell
python -m ngulik review
```

Untuk tiap kandidat kamu akan melihat istilah, kategori, definisi, contoh
pemakaian, dan **berapa kali istilah itu muncul di komentar yang sudah
terkumpul**. Lalu tekan:

| Tombol | Arti |
|---|---|
| `a` | setujui (approve) |
| `r` | tolak (reject) |
| `s` | lewati, putuskan nanti |
| `q` | selesai |

Kandidat yang ditolak **tidak akan ditawarkan lagi** di putaran berikutnya.

Tanpa mode interaktif:

```powershell
python -m ngulik review --list                        # hanya lihat daftar
python -m ngulik review --approve rek --reject "kingdom of bards"
```

> Beberapa entri KBBJ berisi konten vulgar (situsnya sendiri memberi
> peringatan soal ini). Itulah alasan setiap kata wajib lewat review.

---

## 7. Menyiapkan YouTube API Key

1. Buka [Google Cloud Console](https://console.cloud.google.com/) dan login.
2. Buat project baru, misalnya `ngulik-riset`.
3. Buka **APIs & Services > Library**, cari **YouTube Data API v3**, lalu klik
   **Enable**.
4. Buka **APIs & Services > Credentials**, klik **Create credentials > API
   key**, lalu salin key-nya.
5. Disarankan: klik **Restrict key**, lalu batasi ke **YouTube Data API v3**
   saja.
6. Di folder project, salin `.env.example` menjadi `.env`:

   ```powershell
   copy .env.example .env
   ```

7. Buka `.env` dan isi:

   ```
   YOUTUBE_API_KEY=isi_key_kamu_di_sini
   ```

`.env` sudah masuk `.gitignore`. **Jangan pernah membagikan atau meng-commit
key ini.**

### Soal kuota

YouTube membatasi pemakaian API per hari, dan kuotanya direset tengah malam
waktu Pacific (sekitar pukul 14.00–15.00 WIB).

- **Mencari video itu mahal:** jatahnya kecil. Sistem menyimpan hasil
  pencarian ke cache, jadi iterasi berikutnya tidak mencari ulang video yang
  sama.
- **Mengambil komentar itu murah.**
- **`collect --video` tidak memakai jatah pencarian sama sekali**, jadi pakai
  cara ini kalau kamu sudah tahu video mana yang mau diambil.
- `python -m ngulik status` menampilkan jumlah pencarian 24 jam terakhir.
- Kalau kuota habis di tengah jalan, komentar yang sudah terkumpul **tetap
  tersimpan**. Run ditandai `PARTIAL`, dan kamu bisa lanjut besok.

---

## 8. Memakai data sendiri

Format yang didukung: `.json`, `.jsonl`, dan `.csv` (UTF-8).

Kolom yang dikenali (cukup salah satu nama untuk tiap kolom):

| Isi | Nama kolom yang diterima |
|---|---|
| Teks komentar (**wajib**) | `text`, `text_raw`, `comment`, `komentar`, `content`, `body`, `message` |
| ID unik | `source_id`, `id`, `comment_id`, `cid` |
| Waktu | `created_at`, `published_at`, `date`, `timestamp`, `waktu` |
| Tautan | `url`, `link`, `permalink` |
| Nama sumber | `source`, `platform`, `sumber` |
| Keyword pemicu | `keyword`, `query`, `kata_kunci` |

Contoh CSV:

```csv
id,komentar,waktu
a1,"wkwk ngawi lagi ngawi lagi",2026-09-01
a2,"mas mas gabut muncul lagi",2026-09-02
```

Contoh JSON:

```json
[
  {"id": "a1", "text": "wkwk ngawi lagi ngawi lagi"},
  {"id": "a2", "text": "mas mas gabut muncul lagi"}
]
```

Lalu:

```powershell
python -m ngulik collect --path data/komentar_saya.csv
```

Sebaiknya sertakan kolom ID. Tanpa ID, sistem memakai nomor baris sebagai
ID. Mengimpor ulang berkas yang sama persis tetap aman, tapi kalau barisnya
kamu tambah atau urutannya berubah, komentar yang sama bisa tersimpan dua
kali.

---

## 9. Daftar perintah

Tambahkan `--help` di belakang perintah mana pun untuk melihat semua opsinya,
misalnya `python -m ngulik collect --help`.

| Perintah | Fungsi |
|---|---|
| `python -m ngulik` | Buka konsol interaktif |
| `init` | Buat database dan folder data |
| `status` | Ringkasan isi database dan kuota YouTube |
| `keyword import [--file F]` | Muat seed dari YAML |
| `keyword list [--all] [--type T]` | Lihat keyword |
| `keyword add TERM...` | Tambah keyword |
| `keyword remove TERM... [--hard]` | Nonaktifkan keyword (`--hard` = hapus permanen) |
| `keyword match [--top N]` | Cocokkan ulang semua komentar dengan keyword aktif |
| `keyword export [--file F]` | Simpan keyword aktif (seed + yang disetujui) ke YAML |
| `collect [--source file\|youtube] [--path F] [--limit N] [--iteration N]` | Kumpulkan komentar |
| `collect --video URL [--video URL] [--pages N]` | Kumpulkan komentar dari video YouTube tertentu |
| `videos list` | Video YouTube yang sudah diambil |
| `comments list [--video V] [--keyword K] [--matched] [--search T] [--usable] [--limit N] [--export F]` | Lihat dan saring komentar |
| `comments show ID` | Detail satu komentar |
| `clean [--reprocess]` | Bersihkan komentar |
| `lexicon sources` | Daftar sumber kamus |
| `lexicon fetch [--limit N] [--refresh]` | Unduh kata dari kamus |
| `lexicon list [--category K]` | Lihat kata yang sudah diunduh |
| `analyze [frequency\|ngram\|tfidf\|cooccurrence\|all] [--show N]` | Analisis komentar |
| `discover [--max N] [--dry-run]` | Usulkan kandidat kata baru dari komentar |
| `review [--list] [--method M] [--limit N] [--approve T] [--reject T]` | Review kandidat; `--method lexicon` atau `tfidf` dsb. untuk menyaring asal kandidat |
| `iterate` | Promosikan kandidat yang disetujui |

Opsi global: `-v` untuk log detail, `--config berkas.yaml` untuk memakai
konfigurasi lain.

---

## 10. Konfigurasi

Semua pengaturan ada di `config/config.yaml`. Yang paling sering diubah:

| Bagian | Contoh pengaturan |
|---|---|
| `collection` | `default_limit`, pengaturan YouTube (`max_videos_per_keyword`, `region_code`, `max_comment_pages_per_selected_video`) |
| `cleaning` | kamus slang, stopword, `max_repeated_chars` |
| `spam` | `max_urls`, `min_token_diversity`, `copypasta_min_authors`, dan lain-lain |
| `dedup` | `hamming_threshold` (makin kecil makin ketat) |
| `analysis` | `top_n` (hasil yang disimpan), ukuran n-gram, jendela dan metrik co-occurrence (`pmi`, `npmi`, `raw`) |
| `discovery` | bobot keempat sinyal, `min_doc_frequency`, `min_term_length`, `max_candidates` |
| `lexicon` | `request_delay`, `refetch_after_days`, `exclude_categories` |
| `ui` | `color`, `effects`, `tips` |
| `logging` | `level` dan lokasi berkas log |

Berkas pendukung yang bisa kamu edit:

- `config/slang_id.csv`: kamus slang, format `slang,normal`, satu per baris.
- `config/stopwords_id.txt`: kata yang diabaikan, satu per baris.

Setelah mengubah salah satunya, jalankan `python -m ngulik clean --reprocess`.

Variabel environment (di `.env`):

| Variabel | Fungsi |
|---|---|
| `YOUTUBE_API_KEY` | API key YouTube |
| `NGULIK_DATABASE` | Pakai berkas database lain, misalnya untuk uji coba |
| `NGULIK_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, atau `ERROR` |
| `NO_COLOR` | Isi apa saja untuk mematikan warna |

Log lengkap setiap proses tersimpan di `data/ngulik.log`.

---

## 11. Privasi dan etika

- **Nama tampilan komentator tidak pernah disimpan.** ID channel juga tidak,
  kecuali kamu sengaja menyalakan `collection.privacy.store_author_id`.
  Sebaiknya biarkan mati.
- **Data mentah tidak bisa diubah.** Database menolak perubahan pada teks
  asli komentar, jadi hasil selalu bisa dilacak ulang.
- **Keyword baru selalu lewat keputusan manusia.**
- **Entri tentang orang sungguhan dari kamus internet tidak diambil.**
- Pakai alat ini untuk memahami pola bahasa, **bukan** untuk melacak atau
  menarget individu.

---

## 12. Pemecahan masalah

**`conda activate` tidak dikenali di PowerShell.**
Jalankan `conda init powershell`, tutup terminal, lalu buka lagi.

**`[-] No active keywords`.**
Jalankan dulu `python -m ngulik keyword import` atau `keyword add ...`.

**`[-] YOUTUBE_API_KEY is not set`.**
Ikuti [bagian 7](#7-menyiapkan-youtube-api-key). Pastikan berkasnya bernama
`.env` (bukan `.env.txt`) dan berada di folder utama project.

**Status run `PARTIAL` dengan pesan kuota.**
Kuota YouTube hari ini habis. Data yang sudah terkumpul aman; lanjutkan
besok.

**Tampilan berantakan atau muncul kode aneh seperti `←[34m`.**
Terminal kamu tidak mendukung warna. Pakai Windows Terminal, atau matikan
warna di `config/config.yaml` (`ui: color: false`).

**Ingin mencoba tanpa mengotori data utama.**

```powershell
$env:NGULIK_DATABASE = "data/coba.db"
python -m ngulik init
```

Hapus variabel itu (`Remove-Item Env:NGULIK_DATABASE`) untuk kembali ke
database utama.

**Ingin mulai dari nol.**
Hapus berkas `data/ngulik.db`, lalu jalankan `python -m ngulik init` lagi.
Semua komentar, keyword, dan kandidat ikut hilang.

**Menjalankan test** (untuk pengembang):

```powershell
python -m pytest -q
```

---

## Lisensi

[MIT](LICENSE) © 2026 djoov. Bebas dipakai, diubah, dan dibagikan, termasuk
untuk keperluan komersial, selama pemberitahuan lisensi tetap disertakan.
